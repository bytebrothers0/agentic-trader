---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."
---

# Brainstorming Ideas Into Designs

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the project context and then perform a **Complexity Triage**.

## Complexity Triage

Before proceeding, categorize the task:

### 1. Simple Task (FastTrack)
**Definition**: Typo fixes, simple variable renaming, minor CSS tweaks, or 1-3 line logic changes.
**Workflow**: 
- Briefly explain what you'll do (1-2 sentences).
- Get user "go ahead".
- Implement directly.
- Verify with a single test/manual check.
- **Skip**: Formal specs, git-worktrees, implementation plans, and subagents.

### 2. Complex/Huge Task (Full Pipeline)
**Definition**: New features, refactoring, complex bug fixes, or architecture changes.
**Workflow**: Follow the full 7-step pipeline below.

<HARD-GATE>
For **Complex Tasks**, do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it.
</HARD-GATE>

## Full Pipeline Checklist (Complex Tasks Only)

You MUST create a task for each of these items and complete them in order:

1. **Explore project context** — check files, docs, recent commits
2. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria
3. **Propose 2-3 approaches** — with trade-offs and your recommendation
4. **Present design** — in sections scaled to their complexity, get user approval after each section
5. **Write design doc** — save to `docs/specs/YYYY-MM-DD-<topic>-design.md` and commit
6. **User reviews written spec** — ask user to review the spec file before proceeding
7. **Transition to implementation** — invoke writing-plans skill to create implementation plan

## The Process

**Understanding the idea:**
- Check out the current project state first (files, docs, recent commits)
- Ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Focus on understanding: purpose, constraints, success criteria

**Exploring approaches:**
- Propose 2-3 different approaches with trade-offs
- Lead with your recommended option and explain why
**silience & Lifecycle Matrix** (Must be use when implmeneting new feature or refactoring to the project, this cycle shoule be used to make sure that the feature being implemented can handle edge case scenerios and long term production use, always be honest and upfront about the potential issues)this is needed to make sure the feature has all the needed logic and and architectural flow: Proactively challenge the design and make sure its fully integrated end to end with error handling:
 Examples of the Lifecycle Matrix Includes the following:
   **Lifecycle Angle (Setup → Conflict → Cleanup)**: example ,
      Setup: How is the feature initialized? Are defaults sane? Are resources allocated safely?
      Conflict: What happens if it is triggered twice or concurrently? Are locks or idempotency handled?
      Cleanup: Are temporary/ghost resources cleaned? Does it leave stale data? Are background processes terminated correctly?
    **Paradox / “What If” Angle** : example,
      Empty / Edge Data: Zero entries, missing fields, null values.
      Scale / Load: Tens, thousands, millions of items—how does it behave? Memory, CPU, and storage considerations.
      Interruption / Failure: User refresh, cancel, network loss, service crash—any partial updates? Rollback mechanisms?
      Security & Compliance: Unauthorized access, injection vulnerabilities, sensitive data leaks.
    **Contextual Angle**: example,
      Side Effects: Does it impact other modules, services, or scheduled jobs?
      Dependencies: External services, databases, APIs—what happens if they fail or lag?
      Assumptions: Network speed, OS, permissions, VM uptime, environment variables.
    **Observability & Maintenance Angle**: example,
      Logging & Metrics: Are key actions logged? Are errors tracked? Metrics for performance, latency, error rates.
      Alerts / Monitoring: Can production issues be detected proactively?
    **Testing & Validation Angle**: example,
      Unit Testing: Each component works in isolation.
      Integration Testing: Interactions with DB, APIs, and other services.
      End-to-End / Scenario Testing: Covers common workflows and edge cases.
      Regression Readiness: Changes shouldn’t break existing features.
    **Present & Validate Design**: example,
      Present architecture, components, data flow, error handling, testing strategy.
      After each section, ask for feedback or validate assumptions before proceeding.
      Include risk assessment: Known gaps, potential production issues, mitigations.

## After the Design

**Documentation:**
- Write the validated design (spec) to `docs/specs/YYYY-MM-DD-<topic>-design.md`
- Commit the design document to git

**User Review Gate:**
- Ask the user to review the written spec before proceeding:
> "Spec written and committed to `<path>`. Please review it and let me know if you want to make any changes before we start writing out the implementation plan."

**Implementation:**
- Invoke the writing-plans skill to create a detailed implementation plan
