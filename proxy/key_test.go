package main

import (
	"net/http/httptest"
	"testing"
)

func TestGatewayKeyPrecedence(t *testing.T) {
	const clientKey = "oc_sk_client_abc"
	const proxyKey = "oc_sk_proxy_xyz"
	const proxyToken = "lan-secret"

	tests := []struct {
		name       string
		cfgKey     string
		cfgAuth    string
		authorization string
		xKey       string
		wantKey    string
		wantSource string
		wantOK     bool
	}{
		{
			name:     "no key anywhere -> 401",
			cfgKey:   "",
			authorization: "",
			wantOK:   false,
		},
		{
			name:     "client key wins over configured proxy key",
			cfgKey:   proxyKey,
			authorization: "Bearer " + clientKey,
			wantKey:  clientKey,
			wantSource: "client-key",
			wantOK:   true,
		},
		{
			name:     "client key used even without proxy key configured",
			cfgKey:   "",
			authorization: "Bearer " + clientKey,
			wantKey:  clientKey,
			wantSource: "client-key",
			wantOK:   true,
		},
		{
			name:     "no client key -> proxy fallback",
			cfgKey:   proxyKey,
			authorization: "",
			wantKey:  proxyKey,
			wantSource: "proxy-key",
			wantOK:   true,
		},
		{
			name:     "non oc_sk_ Authorization is not a client key",
			cfgKey:   proxyKey,
			authorization: "Bearer sk-random-provider-key",
			wantKey:  proxyKey,
			wantSource: "proxy-key",
			wantOK:   true,
		},
		{
			name:     "with -auth, Authorization is the proxy token and x-opencode-key carries the gateway key",
			cfgKey:   "",
			cfgAuth:  proxyToken,
			authorization: "Bearer " + proxyToken,
			xKey:     clientKey,
			wantKey:  clientKey,
			wantSource: "client-key",
			wantOK:   true,
		},
		{
			name:     "with -auth, missing x-opencode-key falls back to proxy key",
			cfgKey:   proxyKey,
			cfgAuth:  proxyToken,
			authorization: "Bearer " + proxyToken,
			wantKey:  proxyKey,
			wantSource: "proxy-key",
			wantOK:   true,
		},
		{
			name:     "with -auth, oc_sk_ in Authorization is just a wrong token and never a key",
			cfgKey:   proxyKey,
			cfgAuth:  proxyToken,
			authorization: "Bearer " + clientKey,
			xKey:     "",
			wantKey:  proxyKey, // token check happens in authorize(); key is the fallback
			wantSource: "proxy-key",
			wantOK:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			px := &Proxy{cfg: ProxyConfig{Key: tt.cfgKey, ClientAuth: tt.cfgAuth}}
			r := httptest.NewRequest("POST", "/v1/chat/completions", nil)
			if tt.authorization != "" {
				r.Header.Set("Authorization", tt.authorization)
			}
			if tt.xKey != "" {
				r.Header.Set("x-opencode-key", tt.xKey)
			}
			key, source, ok := px.gatewayKey(r)
			if ok != tt.wantOK {
				t.Fatalf("ok = %v, want %v", ok, tt.wantOK)
			}
			if key != tt.wantKey {
				t.Errorf("key = %q, want %q", key, tt.wantKey)
			}
			if source != tt.wantSource {
				t.Errorf("source = %q, want %q", source, tt.wantSource)
			}
		})
	}
}
