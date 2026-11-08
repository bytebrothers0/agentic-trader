# opencode-proxy

A local OpenAI-compatible relay for the **OpenCode inference gateway**
(`opencode.ai/inference/openai/v1`). Run it, point any agentic or coding tool
at `http://localhost:8080/v1`, and use OpenCode's models (including free-tier
ones) with **only an `oc_sk_` API key** — no device login, no console account.

## Why the fingerprint matters

The gateway rejects requests that don't look like they come from the OpenCode
CLI (`FreeTierError 403`). This proxy reproduces the CLI's client fingerprint,
established by live request-isolation experiments against the gateway:

- CLI identity headers: `User-Agent: opencode/latest/2.0.32/cli`,
  `x-opencode-client: cli`, `x-opencode-project`
- **CLI-format session ids**: `x-opencode-session[-id]` /
  `x-session-affinity` / `x-session-id` carry freshly minted
  `ses_` + 12 hex (timestamp-encoded, bitwise-NOT) + 14 base62 ids —
  a faithful port of `schema/src/identifier.ts` (`ids.go`, vector-tested
  against the TS algorithm)
- **The canonical CLI `read` tool** injected into every `tools` array
  (`tools=[read]` alone passes; no tools or foreign-looking tools 403)
- Body parity: `stream: true` upstream (non-streaming clients get an
  aggregated single JSON), `stream_options.include_usage`,
  `max_completion_tokens` (client `max_tokens` is mapped), no `tool_choice`
- Retry: transient rejects (429 / `FreeTierError`) retried with backoff

## Endpoints

| Route | Behavior |
|---|---|
| `POST /v1/chat/completions` | Streaming relay or non-streaming aggregation; prompt/tool schemas pass through **unmodified** (except the additive read-tool injection) |
| `GET /v1/models` | Live catalog from the Console config (84 models) — static fallback offline |
| `GET /health` | liveness |

Client `Authorization` headers are ignored — the proxy uses its own key for
the gateway.

## Run

```powershell
cd tmp\proxy
$env:OPENCODE_API_KEY = "oc_sk_..."   # optional fallback; or pass -key
.\opencode-proxy.exe -listen :8080
```

Build from source: `go build -o opencode-proxy.exe .` · Tests: `go test ./...`

Flags: `-listen`, `-key`, `-upstream`, `-project`, `-inject-read`,
`-max-up`, `-timeout`, `-auth` (defaults `:8080`, `$OPENCODE_API_KEY`,
`https://opencode.ai/inference/openai/v1`, `global`, `true`, `32`, `15m`, none).

## Keys: client bring-your-own, proxy fallback

Every request's credential is resolved with this precedence (unit-tested in
`key_test.go`, live-verified against the real gateway):

1. **The client's OWN `oc_sk_` key** — `Authorization: Bearer oc_sk_...`
   (billed to the client's account, quotas follow that key).
2. **The proxy's configured key** (`-key` / `OPENCODE_API_KEY`) — fallback
   for clients that send nothing. Run with no fallback key configured and
   every caller MUST bring its own (requests without one get a descriptive
   401).

The proxy never hands out or logs its configured key. When `-auth` is on,
the `Authorization` slot belongs to the proxy token, so clients present their
gateway key in a separate header — see below.

## Concurrency (multi-tool parallel load)

One process handles many tools in parallel — Go runs a goroutine per
connection, and the hot spots are tuned deliberately:

- **Shared connection pool** (`MaxIdleConnsPerHost: 64`): parallel tools reuse
  TLS sessions instead of re-handshaking per request.
- **Upstream semaphore** (`-max-up 32`): bounds concurrent gateway calls;
  surplus requests **queue** and leave the queue immediately if their client
  disconnects — no entry stampeding, no orphan goroutines.
- **Leak-free SSE pumps**: streaming relays poll upstream synchronously and
  stop on stream end or client hang-up (a producer-goroutine design was
  rejected precisely because it leaks on mid-stream disconnects).
- **Cancellation propagates**: client disconnect → upstream request cancelled.
- **`GET /stats`**: total/in-flight/streamed/retry counters for live ops.
- **CORS handled** (`Access-Control-Allow-*`, OPTIONS 204) so browser-based
  tools (Open WebUI etc.) work without hacks.
- **Optional `-auth SECRET`**: require clients to send
  `Authorization: Bearer SECRET` — one token, many tools, safe on LAN.
  With `-auth` on, the client's gateway key moves to the
  `x-opencode-key: oc_sk_...` header (the `Authorization` slot is owned by
  the proxy token; an `oc_sk_` value there is treated as a wrong token).
- **Graceful shutdown** on Ctrl+C: stops accepting, drains in-flight calls.

Load-verified: 8 concurrent calls wall-clock **3.1s** vs ~8.8s sequential,
all 200s, all pooled (see `stress.mjs` to re-run).

## Integrate (examples)

OpenAI Python SDK:

```python
from openai import OpenAI
# bring-your-own-key: your oc_sk_ key goes here, used per-request by the proxy
client = OpenAI(base_url="http://localhost:8080/v1", api_key="oc_sk_yourkey...")
r = client.chat.completions.create(
    model="deepseek-v4.1-flash-free",
    messages=[{"role": "user", "content": "hello"}],
)
```

curl:

```powershell
curl http://localhost:8080/v1/chat/completions `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer oc_sk_yourkey..." `
  -d '{\"model\":\"deepseek-v4.1-flash-free\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'
```

Aider: `aider --openai-api-key oc_sk_... --openai-api-base http://localhost:8080/v1`
· Continue / Cline / Cherry Studio: any tool with a custom OpenAI base URL.

## Known caveats

1. **The injected `read` tool is callable.** Models in agentic loops may emit
   a `read` tool call that the *client* must handle (clients that echo an
   "unknown tool" result back recover on the next turn). Disable with
   `-inject-read=false` only if you accept a 403 risk — the gate currently
   requires the tool in every request.
2. **Key-only means key-tier behavior.** Quotas/entitlements follow the key;
   402 on paid models is passed through verbatim as an OpenAI-style error.
3. The free-tier gate is a moving target server-side. If requests start
   403ing, re-run the fingerprint experiments (see GHOST
   `tmp/zen-analysis/source-findings.md`) — the proxy is where any update
   lands.
