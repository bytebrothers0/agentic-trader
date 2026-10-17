---
description: Skill Discovery and Priority System
---

# Skill Discovery and Priority System

## Search Paths (in priority order)

1. **Project Skills** - Highest priority
   - Path: `.antigravity/skills/` in current working directory
   - Override: Shadows all other skill tiers

2. **Personal Skills** - Medium priority  
   - Path: `~/.config/antigravity/skills/`
   - Override: Shadows superpowers skills

3. **Superpowers Skills** - Lowest priority
   - Path: `~/.config/antigravity/skills/superpowers/` (symlink)
   - Base: `~/.config/antigravity/superpowers/skills/`

## Resolution Logic

When agent requests a skill by name:
1. Check project skills first (if exists)
2. Check personal skills second  
3. Check superpowers skills last
4. First match wins

## Escape Hatch Prefix

Use `superpowers:` prefix to bypass overrides and always load from superpowers tier:
- `brainstorming` → Uses project/personal override if present
- `superpowers:brainstorming` → Always uses superpowers version

## Skill Structure

Each skill requires:
```
skill-name/
├── SKILL.md (with YAML frontmatter)
└── [supporting files]
```

Frontmatter format:
```yaml
---
name: skill-name
description: Use when [condition] - [what it does]
---
```

## Symlink Setup (Manual)

To create the superpowers symlink:
```powershell
mkdir -p "$HOME/.config/antigravity/skills"
# On Windows, symlink creation might require admin or use New-Item
New-Item -ItemType SymbolicLink -Path "$HOME/.config/antigravity/skills/superpowers" -Target "$HOME/.config/antigravity/superpowers/skills"
```