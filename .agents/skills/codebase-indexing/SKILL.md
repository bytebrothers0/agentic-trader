---
name: codebase-indexing
description: Use when analyzing a large codebase to map out the architecture and structure into a markdown index map instead of reading files line-by-line.
---

# Codebase Indexing Skill

When you  analyze a large or complex codebase, DO NOT attempt to read entire files line-by-line from the start. That consumes excessive context and takes too long. 

Instead,YOU MUST perform **Architecture Mapping** to build a concise index:

### 1. Folder Scanning
 you MUST Start by using `list_dir` to understand the root structure and identify core directories (e.g., `src`, `components`, `lib`, `api`, `models`, `routes`).

### 2. Targeted Search
MUST Use `grep_search` (ripgrep) to quickly find the definitions of key entities across the workspace. Search for patterns like `class Component`, `export default function`, or route map definitions. 

### 3. Chunked Reading
When you locate the file containing needed logic,YOU MUST use `view_file` but ALWAYS provide `StartLine` and `EndLine` to limit your viewing window just to the relevant block of code.

### 4. Create the Map
YOU MUSTWrite down your findings logically. Group them by component/subsystem, documenting exactly which files handle which responsibility. Save this into an `architecture_index.md` file (or a Knowledge Item) so you only have to do this full scan once.

### 5. Consult Before Action
Whenever the user asks a complex question moving forward,you MUST check the architecture index first to pinpoint the exact 2 or 3 files you actually need to reference.

### 6. Continuous Maintenance
As you work on the codebase and discover new components, services, or significant patterns (or when you create new files),YOU MUST explicitly append these findings to the `architecture_index.md` file including the file paths and line numbers. Treat the index as a living document that grows alongside your understanding.

### 7. Legacy Context Cross-Referencing (Self-Correction)
When migrating, refactoring, or re-implementing UI components that previously existed (e.g., migrating a V4 dashboard to V5), **NEVER assume the new scaffold contains all necessary logic.** You can:
1. Locate the older/legacy version of the files being replaced (even if they are in backup `.zip` archives or previous commits).
2. Extract and thoroughly read the old component's source code to map all state, side-effects, and backend dependencies it relied on.
3. Compare the old logic to the new implementation plan before writing any code to ensure no integrations (like secondary OAuth flows or custom device-auth patterns) are accidentally dropped.
5. no need to extract them again if they have already been extracted

