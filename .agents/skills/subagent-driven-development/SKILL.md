---
name: subagent-driven-development
description: Use when executing implementation plans with independent tasks in the current session
---

# Subagent-Driven Development

Execute plan by dispatching fresh subagent per task, with two-stage review after each: spec compliance review first, then code quality review.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration.

## The Process

1. **Read plan**, extract tasks.
2. **For each task**:
   - Dispatch **Implementer** subagent.
   - Dispatch **Spec Reviewer** subagent.
   - Dispatch **Code Quality Reviewer** subagent.
   - Mark task complete.
3. Finish branch with `finishing-a-development-branch`.

## Prompt Templates

Available in this directory:
- `implementer-prompt.md`
- `spec-reviewer-prompt.md`
- `code-quality-reviewer-prompt.md`

## Handling Status
- **DONE**: Proceed to review.
- **NEEDS_CONTEXT / BLOCKED**: Resolve before proceeding.
