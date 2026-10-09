# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** at the repo root: system-wide decisions that span multiple contexts.
- **`<context>/docs/adr/`** (e.g. `ask-naren/docs/adr/`): context-scoped decisions for the project you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

This is a multi-context repo. `frontend/` (Next.js CS-platform app) and `Brain/` (Python coaching-taxonomy pipeline) are independent projects sharing one repo, each already documented by its own `CLAUDE.md`. `ask-naren/` is a third, newer context: an internal tool that consumes Brain's knowledge base (Layer B `kb_pairs`, Layer C playbooks) but is architecturally its own project, not part of the mining pipeline — see `CONTEXT-MAP.md`'s Relationships section for how it depends on Brain.

```
/
├── CONTEXT-MAP.md
├── CLAUDE.md
├── docs/adr/                          ← system-wide decisions
├── frontend/
│   └── CLAUDE.md                      ← no CONTEXT.md yet, created lazily on first resolved term
├── Brain/
│   ├── CLAUDE.md
│   └── docs/                          ← existing GOTCHAS.md, SCHEMA.md, findings/INDEX.md (no CONTEXT.md yet)
└── ask-naren/
    ├── CONTEXT.md
    └── docs/adr/                      ← Ask-Naren-specific decisions
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the relevant `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
