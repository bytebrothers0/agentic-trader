---
name: requesting-code-review
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements
---

# Requesting Code Review

Dispatch a code-reviewer subagent to catch issues before they cascade. Review early, review often.

**Mandatory**:
- After each task in subagent-driven development.
- Before merging to main.

## How to Request

1. **Get git SHAs**:
```bash
BASE_SHA=$(git rev-parse HEAD~1)
HEAD_SHA=$(git rev-parse HEAD)
```

2. **Dispatch Reviewer**:
Use Task tool with the template provided.

3. **Act on Feedback**:
- **Critical/Important**: Fix immediately.
- **Minor**: Note for later.

## Templates
A standard code review template should be used, covering:
- What was implemented.
- Plan/Requirements.
- Base and Head SHAs.
- Brief Description.
---
