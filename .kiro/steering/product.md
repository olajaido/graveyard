---
inclusion: always
---

# Product Steering — Graveyard

## Purpose

- Graveyard exhumes a repo's dependency tree, autopsies each package for abandonment, and resurrects dead dependencies via agent-assisted rites.
- One-liner: *Dependabot upgrades what's alive. Graveyard deals with what's dead.*
- Every codebase is built on the dead. Graveyard finds them, explains how they died, and brings software back to life.

## Personas

- **Priya (platform/DevSecOps engineer, primary):** owns dependency health across 40 services; needs a prioritised list of dead deps with PRs ready to merge.
- **Marcus (engineering lead / CTO):** needs a one-page Coroner's Report, trend over time, and compliance evidence for CRA.
- **Ade (application developer):** adds packages from memory or AI suggestions; needs a real-time warning at install time.
- **AI coding agents (non-human):** recommend stale packages from training data; need a machine-callable check (MCP) and a blocking hook.

## Product Principles

1. Explainable over clever: the score is deterministic and every point is traceable to evidence with a link. LLMs never compute the score; they only narrate and draft remediation.
2. Dormant is not dead: the "Resting" state exists to protect quiet-but-healthy packages. Crying wolf kills trust.
3. Theme serves function: every spooky element encodes information; Lights On is always one click away.
4. Human in the loop: agents propose; humans dispose. All PRs are draft and need a human to merge.
5. Eat our own dog food: Graveyard autopsies its own alternatives and its own dependencies via a hook and CI.
6. Untrusted by default: READMEs, issues and changelogs are attacker-controllable input to an LLM.

## Glossary (themed → plain)

| Themed | Plain | Meaning |
|---|---|---|
| Exhume | Ingest | Fetch manifests or SBOM, resolve dependency graph |
| Autopsy | Health analysis | Collect signals, compute Mortality Score per package version |
| Mortality Score | Abandonment risk | 0–100 deterministic score (§7) |
| Alive | Healthy | Actively maintained |
| Resting | Dormant, stable | Quiet but no risk indicators; informational only |
| Ailing | At risk | Declining maintenance signals |
| Dead | Abandoned | Declared dead, or score ≥ 60 |
| Cursed | Unfixable vuln | Known vuln affects this version and no fixed version exists |
| Wounded | Fixable vuln | Vuln with an available fix; upgrade, not resurrect |
| Haunting | Exposure | Dependency paths through which a package reaches you |
| Blast radius | Impact | Paths × runtime weight × services affected |
| Death Certificate | Package report | Detail view with evidence |
| Rite | Remediation | Reincarnate, Necromancy, or Seal the Crypt |
| Vigil | Continuous monitoring | CI check and scheduled rescans |
| Coroner's Report | Exportable report | Markdown, PDF, CycloneDX VEX |
| Séance | Grounded Q&A | Ask questions about a dead package, answered only from its artefacts |

## Scope Boundaries

- Public GitHub repos (npm, PyPI) and uploaded CycloneDX SBOMs only.
- No private repos, private registries, or self-hosted GitHub (P2 via GitHub App).
- Ecosystems: npm and PyPI at MVP. Go, Maven, Cargo are stretch.
- Never auto-merge. All PRs are draft.
- Never execute user code in Graveyard infrastructure. Tests run in the user's own CI.
- No malware detection (link to Socket/OSV instead).
- Not a full SCA platform; Graveyard complements existing tools.
