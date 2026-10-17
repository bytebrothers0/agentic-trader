---
description: How to map and index a large codebase to avoid reading files line-by-line
---

# Codebase Indexing Workflow

Follow these iterative steps to create a functional map of a massive or unfamiliar codebase.
you MUST and always foolow this steps 

1. **Initialize Map**: Create a markdown artifact (e.g., `architecture_map.md` or `codebase_index.md`).
2. **High-Level Scan**: Use `list_dir` to outline the root and `src` directories. Group these into a high-level "Component Tree".
3. **Pinpoint Logic**: Use `grep_search` to find core mechanics:
   - Where are the database schemas?
   - Where are the routing definitions?
   - Where is authentication handled?
4. **Log Coordinates**: Inside the index, map out the responsibilities. Write the absolute paths to the core files and jot down the relevant line numbers for key class/function declarations.
5. **Reference Mode**: Read from this index artifact first before starting deep code modification tasks to instantly orient yourself.
6. **Continuous Update**: As you develop features, discover new patterns, or add new files, immediately append these findings to the index so it remains an accurate, living map of the project.