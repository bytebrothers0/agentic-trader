package main

import (
	"regexp"
	"testing"
)

// Cross-language vectors computed with the exact TS BigInt arithmetic
// (timestamp*0x1000 + counter, bitwise-NOT for the descending variant).
func TestIdentifierVectors(t *testing.T) {
	desc := suffixAt(true, 1700000000000, 1)
	if got, want := desc[:12], "4301a97ffffe"; got != want {
		t.Fatalf("descending time part: got %s want %s", got, want)
	}
	asc := suffixAt(false, 1700000000000, 2)
	if got, want := asc[:12], "bcfe56800002"; got != want {
		t.Fatalf("ascending time part: got %s want %s", got, want)
	}
	if len(desc) != 26 || len(asc) != 26 {
		t.Fatalf("suffix length: %d / %d, want 26", len(desc), len(asc))
	}
}

func TestMintSessionID(t *testing.T) {
	pattern := regexp.MustCompile(`^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$`)
	for i := 0; i < 200; i++ {
		id := MintSessionID()
		if !pattern.MatchString(id) {
			t.Fatalf("minted invalid id: %s", id)
		}
	}
}
