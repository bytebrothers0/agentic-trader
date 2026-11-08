package main

// ids.go — exact Go port of OpenCode CLI 2.0.32 identifier minting
// (schema/src/identifier.ts). The gateway fingerprints x-opencode-session-id
// against this format: ses_ + 12 hex chars ((timestamp * 0x1000 + counter)
// bitwise-NOTted into the low 48 bits) + 14 random base62 chars.
//
// Verified by live request-isolation experiments (2026-10-18): CLI-format ids
// pass the free-tier gate; foreign-format ids (UUIDs, random hex) 403 with
// FreeTierError even when every other header matches.

import (
	"crypto/rand"
	"fmt"
	"regexp"
	"sync"
	"time"
)

const idAlphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

var (
	idMu         sync.Mutex
	idLastTS     int64
	idCounter    uint64
	sesPattern   = regexp.MustCompile(`^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$`)
)

// suffixAt computes the identifier time part for a given timestamp/counter.
// Exported-for-test semantics; mirrors identifier.ts byte extraction exactly.
func suffixAt(descending bool, timestamp int64, counter uint64) string {
	current := uint64(timestamp)*0x1000 + counter
	value := current
	if descending {
		value = ^current // low 48 bits equal the BigInt two's complement
	}
	timePart := ""
	for i := 0; i < 6; i++ {
		b := byte((value >> uint(40-8*i)) & 0xff)
		timePart += fmt.Sprintf("%02x", b)
	}
	raw := make([]byte, 14)
	_, _ = rand.Read(raw)
	randPart := make([]byte, 14)
	for i, b := range raw {
		randPart[i] = idAlphabet[b%62]
	}
	return timePart + string(randPart)
}

// MintSessionID returns a fresh CLI-format gateway session id. A new id per
// request is valid (X2 experiment passed with fresh ids on all headers).
func MintSessionID() string {
	now := time.Now().UnixMilli()
	idMu.Lock()
	if now != idLastTS {
		idLastTS = now
		idCounter = 0
	}
	idCounter++
	counter := idCounter
	idMu.Unlock()
	return "ses_" + suffixAt(true, now, counter)
}
