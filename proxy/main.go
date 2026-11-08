package main

// main.go — boots the proxy. Config via flags or env (flags win):
//
//	OPENCODE_API_KEY    OPTIONAL fallback key; clients are expected to send
//	                    their OWN oc_sk_ key as 'Authorization: Bearer oc_sk_...'
//	                    (or 'x-opencode-key: oc_sk_...' when -auth is on)
//	-listen :8080       bind address (env PORT honored if flag empty)
//	-project global     x-opencode-project value (CLI fingerprint member)
//	-inject-read true   append the canonical CLI read tool to tools arrays
//	-upstream ...       override the inference base URL
//	-max-up 32          max concurrent upstream calls (extra requests queue)
//	-timeout 15m        whole-request budget per client call
//	-auth SECRET        optional: require clients to send "Authorization: Bearer SECRET"

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func main() {
	cfg := ProxyConfig{}
	listenFlag := flag.String("listen", "", "listen address (default: :8080 or $PORT)")
	keyFlag := flag.String("key", "", "fallback opencode API key (default: $OPENCODE_API_KEY; clients send their own per-request)")
	upstreamFlag := flag.String("upstream", defaultUpstream, "upstream inference base URL")
	projectFlag := flag.String("project", "global", "x-opencode-project header value")
	injectRead := flag.Bool("inject-read", true, "inject the canonical CLI read tool (required by the gateway fingerprint)")
	maxUp := flag.Int("max-up", 32, "max concurrent upstream requests; extra requests queue")
	timeout := flag.Duration("timeout", 15*time.Minute, "whole-request budget per client call")
	auth := flag.String("auth", "", "optional proxy token: clients must send 'Authorization: Bearer SECRET'")
	flag.Parse()

	cfg.Key = *keyFlag
	if cfg.Key == "" {
		cfg.Key = os.Getenv("OPENCODE_API_KEY")
	}
	if cfg.Key == "" {
		log.Println("WARN: no fallback key configured — every client must send its own 'Authorization: Bearer oc_sk_...'")
	}
	cfg.Upstream = *upstreamFlag
	cfg.Project = *projectFlag
	cfg.InjectRead = *injectRead
	cfg.Timeout = *timeout
	cfg.ClientAuth = strings.TrimSpace(*auth)

	// Shared, tuned connection pool: parallel tools reuse TLS sessions
	// instead of re-handshaking per request. No overall client timeout —
	// long-lived SSE streams are bounded by per-request contexts instead.
	transport := &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		DialContext:           (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 180 * time.Second, // reasoning models can sit before first token
		IdleConnTimeout:       90 * time.Second,
		MaxIdleConns:          128,
		MaxIdleConnsPerHost:   64,
		MaxConnsPerHost:       0,
	}
	px := &Proxy{
		cfg:     cfg,
		client:  &http.Client{Transport: transport},
		limiter: make(chan struct{}, *maxUp),
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/models", px.withLog(px.models))
	mux.HandleFunc("POST /v1/chat/completions", px.withLog(px.chatCompletions))
	mux.HandleFunc("GET /stats", px.withLog(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, px.statsJSON())
	}))
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, []byte(`{"status":"ok"}`))
	})

	listen := *listenFlag
	if listen == "" {
		listen = os.Getenv("PORT")
	}
	if listen == "" {
		listen = ":8080"
	}

	srv := &http.Server{
		Addr:              listen,
		Handler:           cors(mux),
		ReadHeaderTimeout: 10 * time.Second, // slowloris bound
		IdleTimeout:       2 * time.Minute,  // keep-alives between tool calls
	}

	shutdownCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-shutdownCtx.Done()
		log.Println("shutting down (in-flight requests drain)...")
		shCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		_ = srv.Shutdown(shCtx)
	}()

	log.Printf("opencode-proxy listening on %s -> %s (project=%s inject-read=%t max-up=%d timeout=%s)",
		listen, cfg.Upstream, cfg.Project, cfg.InjectRead, *maxUp, cfg.Timeout)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
	log.Println("bye")
}

// cors makes browser-based tools (Open WebUI etc.) work out of the box.
func cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// withLog adds a compact request log line.
func (px *Proxy) withLog(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next(w, r)
		log.Printf("%s %s %s (%s)", r.Method, r.URL.Path, clientLabel(r), fmtDuration(time.Since(start)))
	}
}

func clientLabel(r *http.Request) string {
	if r.Header.Get("Authorization") != "" {
		return "keyed-client"
	}
	return "keyless-client"
}

func fmtDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%dms", d.Milliseconds())
	}
	return fmt.Sprintf("%.1fm", d.Minutes())
}
