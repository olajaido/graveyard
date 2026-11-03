---
inclusion: manual
---

# PR Voice Steering — Graveyard

## Copy Tone in PRs

- Sober and precise in evidence and PR text.
- Never spooky or themed in PR bodies — they land in other people's repos.
- Darkly playful tone is for in-app headers only ("Cause of death: abandonment"), never for PRs.

## PR Body Template (Reincarnate)

```markdown
## Replace `<old>@<version>` with `<new>@<version>`

**Why:** `<old>` is no longer maintained — <cause of death, factual>.
Evidence: <links: registry deprecation notice, archived repo, OSV advisories>.

**What changed**
- <manifest change>
- <n> call sites rewritten (<files>)

**How to test**
- Run the existing test suite; specifically exercise <affected modules>.

**Rollback**
Revert this PR; no data or schema changes.

_Draft opened by Graveyard (mortality model v1). Review before merging._
```

## Rules

- All PRs are draft; never auto-merge.
- Never push to the default branch.
- Include evidence links (registry deprecation, archived repo, OSV advisories).
- Include a rollback note in every PR.
- Stamp with model version.
- In public demo mode, PRs target the `haunted-house` demo repo only; rate-limited to 10 per hour globally.
