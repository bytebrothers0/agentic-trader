package main

// gateway.go — relay core. The upstream is the OpenCode inference gateway
// (opencode.ai/inference/openai/v1), OpenAI-chat-compatible on the wire, but
// gated by a client fingerprint established by request-isolation experiments
// against the real gateway (HAR + vendored CLI source, 2026-10-18):
//
//   - Authorization: the oc_sk_ API key (the only credential this proxy uses)
//   - User-Agent / x-opencode-client / x-opencode-project: CLI identity
//   - x-opencode-session[-id] / x-session-affinity / x-session-id:
//     CLI-format minted session ids (see ids.go)
//   - tools: the canonical CLI `read` tool must be present in the tools array
//     (tools=[read] alone → 200; no tools / foreign tools → 403 FreeTierError)
//   - body parity: stream:true + stream_options.include_usage +
//     max_completion_tokens (the CLI never sends tool_choice)
//
// Concurrency design (multi-tool parallel load):
//   - net/http serves one goroutine per connection; every handler below is
//     goroutine-safe (no shared mutable state; ids are mutex-guarded)
//   - upstream requests share one connection POOL (main.go Transport tuning)
//     so parallel callers reuse TLS sessions instead of re-handshaking
//   - a -max-up semaphore bounds concurrent upstream calls; extra requests
//     QUEUE (with client disconnect honored) instead of stampeding
//   - SSE pumps poll synchronously (no producer goroutines) and stop when the
//     upstream ends or the client disconnects — no goroutine leaks
//   - r.Context() propagates client cancellation to the upstream request

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"sort"
	"strings"
	"sync/atomic"
	"time"
)

const (
	defaultUpstream  = "https://opencode.ai/inference/openai/v1"
	consoleConfigURL = "https://opencode.ai/console/api/v2/config"
	cliUA            = "opencode/latest/2.0.32/cli"
	defaultModel     = "deepseek-v4.1-flash-free"
)

// canonicalReadTool is the CLI's `read` tool verbatim (HAR-recovered). The
// gateway scans every inference request for this exact object. Read-only
// after init: concurrent map reads are safe.
var canonicalReadTool = map[string]any{
	"type": "function",
	"function": map[string]any{
		"name": "read",
		"description": "Read the contents of a file or directory. Supports text files, images, and PDFs. " +
			"Images and PDFs are presented directly to the model. Each text line is prefixed by its 1-based line " +
			"number as <line>: <content>. The prefix is for reference and is not part of the file content. " +
			"Directory entries are returned one per line. Use offset and limit to read large files or directories " +
			"in sections. Prefer one larger read over many small slices, and use grep to find specific content in large files.",
		"parameters": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path":   map[string]any{"type": "string", "description": "File or directory to read"},
				"offset": map[string]any{"type": "integer", "minimum": 0, "description": "The line or directory entry to start reading from (1-based)"},
				"limit":  map[string]any{"type": "integer", "minimum": 0, "description": "The maximum number of lines or directory entries to read (defaults to and capped at 2000)"},
			},
			"required":             []any{"path"},
			"additionalProperties": false,
		},
		"strict": false,
	},
}

// injectRead appends the canonical read tool unless a tool named `read`
// already exists (idempotent, additive-only, defensive copy — client tools
// are never altered).
func injectRead(tools []any) []any {
	for _, t := range tools {
		if m, ok := t.(map[string]any); ok {
			if fn, ok := m["function"].(map[string]any); ok && fn["name"] == "read" {
				return tools
			}
		}
	}
	return append(append(tools[:0:0], tools...), canonicalReadTool)
}

func buildHeaders(key, project string) http.Header {
	ses := MintSessionID()
	return http.Header{
		"Authorization":         {"Bearer " + key},
		"Content-Type":          {"application/json"},
		"Accept":                {"*/*"},
		"User-Agent":            {cliUA},
		"x-opencode-client":     {"cli"},
		"x-opencode-project":    {project},
		"x-opencode-session":    {ses},
		"x-opencode-session-id": {ses},
		"x-session-affinity":    {ses},
		"x-session-id":          {ses},
	}
}

// prepareUpstream mutates a per-request parsed body into the CLI-parity
// upstream shape. Only touches body data — safe for parallel requests.
func prepareUpstream(body map[string]any, inject bool) bool {
	clientStream, ok := body["stream"].(bool)
	if !ok {
		clientStream = false
	}

	if m, exists := body["model"].(string); !exists || m == "" {
		body["model"] = defaultModel
	}

	// max_tokens (client convention) -> max_completion_tokens (CLI convention);
	// default 32000 (model catalog output limit).
	if _, has := body["max_completion_tokens"]; !has {
		if mt, has := body["max_tokens"]; has {
			body["max_completion_tokens"] = mt
		} else {
			body["max_completion_tokens"] = 32000
		}
	}
	delete(body, "max_tokens")

	body["stream"] = true
	body["stream_options"] = map[string]any{"include_usage": true}

	if inject {
		tools, _ := body["tools"].([]any)
		body["tools"] = injectRead(tools)
	}
	return clientStream
}

// openaiError renders a gateway failure in OpenAI error format.
func openaiError(status int, msg string) []byte {
	body, _ := json.Marshal(map[string]any{
		"error": map[string]any{"message": msg, "type": "proxy_error", "code": status},
	})
	return body
}

// gatewayKey resolves credential precedence:
//   1. the client's OWN oc_sk_ key, presented via Authorization (or, when
//      -auth is on and the Authorization slot is owned by the proxy token,
//      via the x-opencode-key header)
//   2. the proxy-configured key (fallback for clients that send nothing)
// Returns the key, its source label, and whether one was resolvable.
func (px *Proxy) gatewayKey(r *http.Request) (string, string, bool) {
	var headerKey string
	if px.cfg.ClientAuth != "" {
		if k := strings.TrimSpace(r.Header.Get("x-opencode-key")); k != "" {
			headerKey = k
		}
	} else if tok := strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")); strings.HasPrefix(tok, "oc_sk_") {
		headerKey = tok
	}
	if headerKey != "" {
		return headerKey, "client-key", true
	}
	if px.cfg.Key != "" {
		return px.cfg.Key, "proxy-key", true
	}
	return "", "", false
}

// doUpstream posts the body (context-bound, caller-resolved key) and reports
// the response, upstream status, and raw error text on non-2xx statuses.
func (px *Proxy) doUpstream(ctx context.Context, key, path string, body []byte) (*http.Response, int, string) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, px.cfg.Upstream+path, bytes.NewReader(body))
	if err != nil {
		return nil, 500, err.Error()
	}
	head := buildHeaders(key, px.cfg.Project)
	for k, v := range head {
		req.Header[k] = v
	}
	resp, err := px.client.Do(req)
	if err != nil {
		return nil, 502, err.Error()
	}
	if resp.StatusCode/100 == 2 {
		return resp, resp.StatusCode, ""
	}
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<10))
	resp.Body.Close()
	return nil, resp.StatusCode, fmt.Sprintf("gateway %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
}

// ---------- SSE plumbing (synchronous, leak-free) ----------

// streamSSE invokes fn for every upstream `data:` payload, verbatim, until
// [DONE] or stream end. Comments/keep-alives are skipped.
func streamSSE(r io.Reader, fn func(payload string) error) error {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 0, 64*1024), 8<<20)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if err := fn(payload); err != nil {
			return err
		}
		if payload == "[DONE]" {
			return nil
		}
	}
	return sc.Err()
}

// ---------- streaming relay ----------

// relayStream copies upstream SSE straight to the client, flushing per event.
// Synchronous polling stops naturally when the client disconnects (write
// error) or the upstream closes — nothing to leak.
func relayStream(w http.ResponseWriter, resp *http.Response) bool {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)
	flusher, _ := w.(http.Flusher)

	err := streamSSE(resp.Body, func(payload string) error {
		if _, werr := io.WriteString(w, "data: "+payload+"\n\n"); werr != nil {
			return errClientGone(werr)
		}
		if flusher != nil {
			flusher.Flush()
		}
		return nil
	})
	resp.Body.Close()
	if err != nil && !isClientGone(err) {
		log.Printf("[stream] upstream read error: %v", err)
		return false
	}
	return true
}

type clientGoneError struct{ err error }

func (e *clientGoneError) Error() string { return "client gone: " + e.err.Error() }
func errClientGone(err error) error      { return &clientGoneError{err: err} }
func isClientGone(err error) bool {
	_, ok := err.(*clientGoneError)
	return ok
}

// ---------- non-streaming aggregation ----------

type chunkToolCall struct {
	Index    int    `json:"index"`
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type chatChunk struct {
	Choices []struct {
		Index int `json:"index"`
		Delta struct {
			Content   string          `json:"content"`
			Reasoning string          `json:"reasoning_content"`
			ToolCalls []chunkToolCall `json:"tool_calls"`
		} `json:"delta"`
		FinishReason any `json:"finish_reason"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
}

// aggregate consumes the upstream SSE and builds a complete OpenAI response.
func aggregate(resp *http.Response, model string) []byte {
	var content, reasoning strings.Builder
	toolAcc := map[int]*chunkToolCall{}
	var order []int
	var finish any
	var usage map[string]any

	_ = streamSSE(resp.Body, func(payload string) error {
		if payload == "" || payload == "[DONE]" {
			return nil
		}
		var chunk chatChunk
		if json.Unmarshal([]byte(payload), &chunk) != nil {
			return nil // non-chat frame
		}
		for _, choice := range chunk.Choices {
			content.WriteString(choice.Delta.Content)
			reasoning.WriteString(choice.Delta.Reasoning)
			for _, tc := range choice.Delta.ToolCalls {
				acc, exists := toolAcc[tc.Index]
				if !exists {
					acc = &chunkToolCall{Index: tc.Index, Type: "function", ID: tc.ID}
					toolAcc[tc.Index] = acc
					order = append(order, tc.Index)
				}
				if tc.ID != "" {
					acc.ID = tc.ID
				}
				if tc.Function.Name != "" {
					acc.Function.Name += tc.Function.Name
				}
				acc.Function.Arguments += tc.Function.Arguments
			}
			if choice.FinishReason != nil && choice.FinishReason != "" {
				finish = choice.FinishReason
			}
		}
		if chunk.Usage != nil && (chunk.Usage.PromptTokens > 0 || chunk.Usage.TotalTokens > 0) {
			usage = map[string]any{
				"prompt_tokens":     chunk.Usage.PromptTokens,
				"completion_tokens": chunk.Usage.CompletionTokens,
				"total_tokens":      chunk.Usage.TotalTokens,
			}
		}
		return nil
	})
	resp.Body.Close()

	toolCalls := make([]any, 0, len(order))
	for _, i := range order {
		acc := toolAcc[i]
		toolCalls = append(toolCalls, map[string]any{
			"id":       acc.ID,
			"type":     "function",
			"function": map[string]any{"name": acc.Function.Name, "arguments": acc.Function.Arguments},
		})
	}

	message := map[string]any{"role": "assistant", "content": content.String()}
	if reasoning.Len() > 0 {
		message["reasoning_content"] = reasoning.String()
	}
	if len(toolCalls) > 0 {
		message["tool_calls"] = toolCalls
		if finish == nil {
			finish = "tool_calls"
		}
	}
	if finish == nil {
		finish = "stop"
	}

	respBody := map[string]any{
		"id":      "chatcmpl-" + MintSessionID(),
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   model,
		"choices": []any{map[string]any{
			"index":         0,
			"message":       message,
			"finish_reason": finish,
		}},
	}
	if usage != nil {
		respBody["usage"] = usage
	}
	out, _ := json.Marshal(respBody)
	return out
}

// ---------- handlers ----------

// chatCompletions relays /v1/chat/completions with the full gate fingerprint.
// Concurrency: bounded upstream slots (-max-up); queued requests respect
// client disconnects via context cancellation.
func (px *Proxy) chatCompletions(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(io.LimitReader(r.Body, 32<<20))
	if err != nil {
		writeJSON(w, 400, openaiError(400, "unreadable request body: "+err.Error()))
		return
	}
	if !px.authorize(w, r) {
		return
	}
	key, keySource, ok := px.gatewayKey(r)
	if !ok {
		writeJSON(w, 401, openaiError(401, "[opencode-proxy] no opencode API key: send your own as 'Authorization: Bearer oc_sk_...' (or set one on the proxy via OPENCODE_API_KEY/-key)"))
		return
	}

	var body map[string]any
	if json.Unmarshal(raw, &body) != nil {
		writeJSON(w, 400, openaiError(400, "invalid JSON body"))
		return
	}
	clientStream := prepareUpstream(body, px.cfg.InjectRead)
	upstreamBody, _ := json.Marshal(body)
	model, _ := body["model"].(string)

	ctx, cancel := context.WithTimeout(r.Context(), px.cfg.Timeout)
	defer cancel()

	px.stats.total.Add(1)
	px.stats.inflight.Add(1)
	defer px.stats.inflight.Add(-1)
	if clientStream {
		px.stats.streams.Add(1)
	}

	// Concurrency slot: queue until free or the client gives up.
	select {
	case px.limiter <- struct{}{}:
		defer func() { <-px.limiter }()
	case <-ctx.Done():
		writeJSON(w, http.StatusRequestTimeout, openaiError(408, "[opencode-proxy] request queued too long (upstream slots busy)"))
		return
	}

	const maxAttempts = 3
	var resp *http.Response
	lastStatus, lastText := 0, ""
	for attempt := 0; attempt < maxAttempts; attempt++ {
		if attempt > 0 {
			px.stats.retries.Add(1)
			select {
			case <-time.After(time.Duration(attempt) * 800 * time.Millisecond):
			case <-ctx.Done():
				return // client hung up while we back off
			}
		}
		var errText string
		resp, lastStatus, errText = px.doUpstream(ctx, key, "/chat/completions", upstreamBody)
		if resp != nil {
			break
		}
		log.Printf("[attempt %d/%d] %d: %s", attempt+1, maxAttempts, lastStatus, errText)
		lastText = errText
		// Retry only transient gateway rejects (free-tier gate / throttle).
		if lastStatus != 429 && !strings.Contains(errText, "FreeTierError") {
			break
		}
	}
	if resp == nil {
		writeJSON(w, lastStatus, openaiError(lastStatus, "[opencode-proxy] "+lastText))
		return
	}

	if clientStream {
		relayStream(w, resp)
		return
	}
	log.Printf("[chat] model=%s key=%s", model, keySource)
	writeBody(w, http.StatusOK, "application/json", aggregate(resp, model))
}

// models serves the live gateway catalog (Console v2 config accepts the API
// key); the curated static list is the offline fallback.
func (px *Proxy) models(w http.ResponseWriter, r *http.Request) {
	if !px.authorize(w, r) {
		return
	}
	key, _, ok := px.gatewayKey(r)
	if !ok {
		writeJSON(w, 401, openaiError(401, "[opencode-proxy] no opencode API key: send 'Authorization: Bearer oc_sk_...' or configure one on the proxy"))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, consoleConfigURL, nil)
	if err != nil {
		writeJSON(w, 500, openaiError(500, err.Error()))
		return
	}
	head := buildHeaders(key, px.cfg.Project)
	for k, v := range head {
		req.Header[k] = v
	}
	req.Header.Set("Accept", "application/json")
	if resp, err := px.client.Do(req); err == nil {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
		resp.Body.Close()
		if resp.StatusCode == 200 {
			if ids := extractCatalogIDs(raw); len(ids) > 0 {
				data := make([]any, 0, len(ids))
				for _, id := range ids {
					data = append(data, map[string]any{"id": id, "object": "model", "owned_by": "opencode"})
				}
				writeJSON(w, 200, []byte(mustJSON(map[string]any{"object": "list", "data": data})))
				return
			}
		}
	}
	writeJSON(w, 200, staticModels())
}

// statsJSON exposes live concurrency metrics for operators (/stats).
func (px *Proxy) statsJSON() []byte {
	return []byte(mustJSON(map[string]any{
		"total_requests": px.stats.total.Load(),
		"in_flight":      px.stats.inflight.Load(),
		"streamed":       px.stats.streams.Load(),
		"upstream_slots": cap(px.limiter),
		"retries":        px.stats.retries.Load(),
	}))
}

// extractCatalogIDs pulls providers.opencode.models keys (the live catalog).
func extractCatalogIDs(raw []byte) []string {
	var cfg struct {
		Providers struct {
			Opencode struct {
				Models map[string]json.RawMessage `json:"models"`
			} `json:"opencode"`
		} `json:"providers"`
	}
	if json.Unmarshal(raw, &cfg) != nil {
		return nil
	}
	keys := make([]string, 0, len(cfg.Providers.Opencode.Models))
	for k := range cfg.Providers.Opencode.Models {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func mustJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func staticModels() []byte {
	ids := []string{
		// free
		"deepseek-v4.1-flash-free", "glm-5.3-flash-free", "space-bunny-free",
		"big-pickle", "beam-free", "longcat-2.5-preview-free", "mimo-v2.6-flash-free",
		"nemotron-3-ultra-free", "nemotron-3.5-lightning-free",
		// paid
		"deepseek-v4.1-flash", "deepseek-v4-pro", "claude-opus-4-8", "claude-sonnet-5-5",
		"gpt-5.3-codex", "gpt-5.5", "gemini-3.1-pro", "grok-4.7", "kimi-k2.7-code",
		"minimax-m2.7", "qwen3.8-max",
	}
	data := make([]any, 0, len(ids))
	for _, id := range ids {
		data = append(data, map[string]any{"id": id, "object": "model", "owned_by": "opencode"})
	}
	out, _ := json.Marshal(map[string]any{"object": "list", "data": data})
	return out
}

// ---------- glue ----------

type Proxy struct {
	cfg     ProxyConfig
	client  *http.Client
	limiter chan struct{}
	stats   AppStats
}

type AppStats struct {
	total    atomic.Int64
	inflight atomic.Int64
	streams  atomic.Int64
	retries  atomic.Int64
}

type ProxyConfig struct {
	Key        string
	Upstream   string
	Project    string
	InjectRead bool
	Timeout    time.Duration // whole-request budget per client call
	ClientAuth string        // optional: token clients must present
}

// authorize optionally enforces a proxy-own token for LAN/multi-user use.
func (px *Proxy) authorize(w http.ResponseWriter, r *http.Request) bool {
	if px.cfg.ClientAuth == "" {
		return true
	}
	if r.Header.Get("Authorization") == "Bearer "+px.cfg.ClientAuth {
		return true
	}
	writeJSON(w, 401, openaiError(401, "[opencode-proxy] invalid proxy token (set the Authorization header to the value given via -auth)"))
	return false
}

func writeJSON(w http.ResponseWriter, status int, body []byte) {
	writeBody(w, status, "application/json", body)
}

func writeBody(w http.ResponseWriter, status int, ctype string, body []byte) {
	w.Header().Set("Content-Type", ctype)
	w.WriteHeader(status)
	_, _ = w.Write(body)
}
