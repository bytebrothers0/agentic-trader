---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans - creates isolated git worktrees with smart directory selection and safety verification
---

# Using Git Worktrees

## Overview

Git worktrees create isolated workspaces sharing the same repository, allowing work on multiple branches simultaneously without switching.

**Core principle:** Systematic directory selection + safety verification = reliable isolation.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Directory Selection Process

Follow this priority order:
1. **Check Existing Directories**: Uses `.worktrees/` or `worktrees/` if they exist.
2. **Ask User**: If no directory exists, ask where to create them (default to `.worktrees/`).

## Creation Steps

### 1. Detect Project Name
```bash
project=$(basename "$(git rev-parse --show-toplevel)")
```

### 2. Create Worktree
```bash
# Example for Windows PowerShell
New-Item -ItemType Directory -Path ".worktrees" -Force
git worktree add ".worktrees/$BRANCH_NAME" -b "$BRANCH_NAME"
cd ".worktrees/$BRANCH_NAME"
```

### 3. Run Project Setup
Auto-detect and run setup for `pos_system`:
```bash
if (Test-Path "package.json") { npm install }
```

### 4. Verify Clean Baseline
Run tests to ensure worktree starts clean:
```bash
npm run test
```

## Safety Verification
Ensure the worktree directory is in `.gitignore` to prevent committing worktree contents.
