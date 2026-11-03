---
inclusion: fileMatch
fileMatchPattern: "web/**"
---

# UI Theme Steering — Graveyard

## Visual Language

- Scene: 2.5D layered SVG (night sky, moon, treeline, rolling hills, iron fence, ground fog). Tombstones on parallax layers.
- Motion: CSS/Framer Motion for fog drift and wisps. No Three.js.
- Tombstone attributes encode data:
  - Height (3 sizes) = blast radius tercile.
  - Shape (rounded, cross, obelisk) = ecosystem (npm, PyPI, other).
  - Crack overlay + purple glow = Cursed.
  - Moss coverage = months since last release.
  - Fog around base = low confidence.
  - Epitaph (engraved) = `name@version`, "† <died-date>".
  - Wisps on hover/focus = haunting paths highlighted.

## Palette Tokens (CSS custom properties)

```
--night-900: #0B0E14
--night-700: #161B26
--moon: #E8E4D8
--fog: rgba(200,205,215,.12)
--ectoplasm: #7CFFB2   (Alive/Resting accent)
--ember: #FF8A3D       (Ailing)
--blood: #E5484D       (Dead)
--curse: #B07CFF       (Cursed)
--parchment: #F2E6C9   (certificate)
```
- Define light-mode equivalents for the Lights On table.

## Typography

- Display face for headings only (OFL-licensed Google Font). Keep out of body text.
- Body text: Inter.
- Code: JetBrains Mono.

## Layout Rules

- Tombstones ordered left to right by priority; most urgent nearest the viewer.
- Layout works from 360 px to 4K.
- Filters: ecosystem, state, runtime/dev, direct/transitive, service.
- Lights On renders a sortable, filterable, keyboard-navigable table; exportable to CSV; remembers choice per browser.
- Alive and Resting packages shown as count only ("The living: 412 · Resting: 37").

## States to Design

Loading, partial results (fog banner when a source is down), errors (repo not found, rate limited, file too large), empty graveyard, mobile layout, Lights On, reduced motion, keyboard focus rings.

## Accessibility (GY-6 — WCAG 2.2 AA)

- Roving-tabindex keyboard navigation between tombstones.
- `aria-label` on every tombstone (e.g. "pycrypto 2.6.1, Dead and Cursed, priority 1 of 7").
- Respect `prefers-reduced-motion`; disable animations when set.
- Text contrast ≥ 4.5:1.
- No information conveyed by colour alone; always pair with icon, shape or text.
- Lights On table fully keyboard navigable.
- axe-core in CI with zero serious violations.

## Sound

- Sound off by default.

## Copy Tone

- Darkly playful in headers ("Cause of death: abandonment").
- Sober and precise in evidence and PR text.
- Never spooky in PR bodies (they land in other people's repos).

## Key Screens

1. Landing: hero over graveyard horizon; repo input and two secondary CTAs.
2. Exhumation (progress): shovel animation, stage list, live autopsy counter.
3. Graveyard: scene, filter bar, living/resting counters, Lights On toggle, export menu.
4. Death Certificate drawer: per DC-1 spec.
5. Last Rites modal: rite cards, diff preview (Monaco, read-only), Open draft PR button.
6. Coroner's Report: printable view.
7. Vigil setup: copy-paste snippets for Action and Power install.
