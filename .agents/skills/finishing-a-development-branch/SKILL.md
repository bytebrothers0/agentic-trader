---
name: finishing-a-development-branch
description: Use when implementation is complete, all tests pass, and you need to decide how to integrate the work
---

# Finishing a Development Branch

Guide completion of development work by verifying tests and handling the chosen integration workflow.

**Core principle:** Verify tests -> Present options -> Execute choice -> Clean up.

## The Process

### 1. Verify Tests
```bash
npm run test
```
If tests fail, STOP and fix them.

### 2. Present Options
Present these 4 options to the user:
1. Merge back to base branch locally.
2. Push and create a Pull Request (`gh pr create`).
3. Keep the branch as-is (I'll handle it later).
4. Discard this work (requires 'discard' confirmation).

### 3. Cleanup
For options 1, 2, and 4, remove the git worktree if one was used:
```bash
git worktree remove <path>
```
---
