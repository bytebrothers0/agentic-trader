---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---

# Test-Driven Development (TDD)

## The Iron Law
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.

## Red-Green-Refactor Cycle

1. **RED**: Write a failing test in Vitest.
   - Run: `npm run test <path/to/test>`
   - Confirm it fails as expected.
2. **GREEN**: Write minimal code to pass the test.
   - Run: `npm run test <path/to/test>`
   - Confirm it passes.
3. **REFACTOR**: Clean up code while keeping tests green.

## Rules
- Deleting means delete: If you wrote code before the test, delete it and start over.
- One behavior per test.
- Use real code (no mocks unless unavoidable).

## Anti-Patterns
- Testing mock behavior instead of real behavior.
- Skipping TDD because "it's too simple".
- Tests written after implementation.
