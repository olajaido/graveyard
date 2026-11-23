---
inclusion: fileMatch
fileMatchPattern: "web/**"
---
# Frontend Design Steering — Graveyard
Source: the approved mockups in `design/mockups/` (`Main`, `Exhumation`, `Graveyard`, `Certificate`). Every UI spec follows this file. Contrast figures are WCAG 2.x ratios computed from the hex values.

**Precedence.** This file is the whole UI design steering. It replaces `ui-theme.md`, which is now a one-line pointer; the parts of `ui-theme.md` that still apply are carried over in section 10. Where `product.md` or the PRD define a state, they win over mockup copy. The product runs mortality model v2: Dead means declared dead (PRD amendment v1.4).

## 1. Colour tokens
Define as CSS custom properties in `web/app/globals.css` (Tailwind v4 `@theme`, names `--color-<token>`). Components use the token, never the hex.

### Surfaces and text (dark)
| Token | Hex | Role |
|---|---|---|
| `ground` | `#0D0F13` | page background |
| `night` | `#121620` | sky, header band, plot panel |
| `night-alt` | `#11141A` | alternate section band |
| `ground-cert` | `#0F1011` | certificate page background |
| `surface` | `#161A21` | cards, chips |
| `surface-line` | `#262C35` | card and chip border |
| `hairline` | `#1E232B` | section dividers, plot border |
| `stone` | `#2A2F37` | grave body |
| `stone-line` | `#3E444E` | grave edge, `#3A3F45` for input and button borders |
| `plot` | `#0F1217` | plot ground behind stones |
| `earth` | `#1A150F` | cast shadow under a grave. Warm earth tones `#3A2E22`, `#46382A`, `#2A2219` are art-only |
| `bone` | `#ECE6D8` | primary text, primary button fill, focus ring on dark |
| `bone-soft` | `#D3CDC0` | lead paragraphs |
| `bone-muted` | `#C9C3B6` | secondary text |
| `bone-quiet` | `#A9A396` | captions, tertiary text |
| `bone-dim` | `#8F8A7F` | placeholders, "waiting" |
| `on-bone` | `#121314` | text on a `bone` button or chip |

### Parchment (certificate, Lights On table, toe tags)
| Token | Hex | Role |
|---|---|---|
| `parchment` | `#EDE6D6` | paper |
| `paper-tint` | `#E3DACA` | highlight, current node |
| `ink` | `#1B1A17` | text on paper, focus ring on paper |
| `ink-soft` | `#3D3A31` | body on paper |
| `ink-muted` | `#5E5848` | labels on paper (5.7:1) |
| `paper-rule-strong` | `#8C8371` | double rules. Decoration only (3.0:1) |
| `paper-rule` | `#A99F88` | table head rule |
| `paper-line` | `#C9BFA9` | field underlines |
| `paper-hair` | `#CFC6B2` | row lines, paper border |
| `paper-link` | `#5B2A22` | links on paper (hover `#3A1712`) |

### State tokens
Each state has four values: **bright** for dark surfaces, **ink** for text on parchment, **pill** (background of the pill on parchment) and **body** (grave fill, where it differs from `stone`).

| State | bright | ink | pill | Notes |
|---|---|---|---|---|
| Dead | `#E8887B` | `#8A2B1F` | `#F3D4CE` | |
| Cursed | `#C4AEF5` | `#4E3A86` | `#E2D9F7` | body `#2B2838`, glow `rgba(196,174,245,.45)` |
| Ailing | `#E9B266` | `#7A4A0E` | `#F4E1C2` | |
| Resting | `#8FB2E0` | `#2D4B78` | `#D6E2F2` | |
| Alive | `#93CBA6` | `#2F6B44` | `#D5EBDC` | leaf `#6FA982`, tint `#1A2A20`, ground `#1F2A21` |
| Wounded | `#F0A39A` | `#8A3A30` | `#F5D9D4` | |

Other fixed colours: lantern flame `#F3C77C`; wax seal fill `#8A2B1F`, ring `#B8463A`, inner ring `#6E2118`, text `#F2D6CF`; moon and stars `#E8E1CF`, craters `#D7CFBB`; fog `#CBD2DE` at 6 to 7 % opacity.

### Contrast (checked)
- Bright state colours on `ground`, `night`, `surface`, `plot`: 6.8 to 10.4:1. On `stone`: 5.3 to 7.3:1. All pass AA for text.
- `bone`, `bone-soft`, `bone-muted`, `bone-quiet` pass AA on every dark surface including `stone` (5.4:1 at worst).
- `bone-dim` passes on `ground`, `night`, `surface` and `plot` (5.1 to 5.6:1) and **fails on `stone` (3.9:1)**. Never put `bone-dim` text on a grave.
- `#7E848E` (used for version text inside graves in the mockup) fails on `stone` (3.6:1). Use `#9AA0AA` (5.1:1) or `bone-quiet`.
- Every state ink passes AA on `parchment` (5.1 to 7.4:1) and on its own pill (5.1 to 6.8:1). `ink-muted` passes on `parchment` and `paper-tint`.
- `paper-rule-strong` is below 3:1. Use it for decorative rules, never for a control boundary or text.
- A unit test (`web/lib/contrast.test.ts`) asserts these pairs from `globals.css`. Add a pair there when you add a text/background combination.

## 2. Typography
Self-hosted via `@fontsource` (latin subset, `font-display: swap`, loaded with `next/font/local`). No Google Fonts request at runtime.
| Role | Face and weights | Rule |
|---|---|---|
| Display | **Cormorant Garamond** 500, 600, 700, italic 500 and 600 | h1, h2, plot and certificate titles, large numerals, taglines. Never body text |
| Body | **Inter** 400, 500, 600 | everything else |
| Code | **JetBrains Mono** 400, 500 | package names, purls, repo names, scan IDs, service paths |

| Style | Size / line height | Notes |
|---|---|---|
| Hero h1 | `clamp(48px, 6.4vw, 88px)` / 1.0, tracking -0.01em, 600 | italic accent word in `cursed` |
| Page h1 | `clamp(36px, 5vw, 60px)` / 1.05, 600 | repo name. `overflow-wrap: anywhere` |
| Section h2 (marketing) | 52 / 1.1, 600 | `clamp(36px, 5vw, 52px)` on small screens |
| App h2 | 30, 600 (plot title 32) | |
| Certificate h1 / h2 | `clamp(40px, 5vw, 58px)` 700 / 24, 600 | |
| Card h3 | 21 Inter 600 | |
| Numerals | Cormorant 600 at 36, 40, 56, 64, 96, 104 | stat displays |
| Body / lead / small / caption | 16 / 1.6, 19 / 1.6, 15, 13 to 14 | |
| Eyebrow | 13, 600, uppercase, tracking 0.16em | |
| Field label on paper | 12, uppercase, tracking 0.14em, `ink-muted` | |
| Mono | 12 (stone name), 13, 14, 15, 26 (certificate name) | |

Text inside an SVG is decorative and `aria-hidden`. Real, readable text is at least 12 px and sits in HTML.

## 3. Spacing, layout, radii, elevation
- Spacing is the Tailwind 4 px scale. Observed rhythm: 8, 10, 12, 16, 20, 24, 28, 32, 40, 48, 56. Section padding is 88 px vertical (64 px under 640 px). Card padding 22 to 24.
- Container: `max-width: 1240px`, centred, horizontal gutter `clamp(16px, 5vw, 32px)` (the mockup's fixed 32 px leaves 296 px at 360 px wide).
- Grids: `repeat(auto-fit, minmax(250px, 1fr))` for step cards, `minmax(340px, 1fr)` for state cards, with `min(100%, …)` so nothing overflows at 360 px.
- Radii: 4 (inline highlight), 6 (paper, toe-tag left edge), 10 (inputs, buttons), 12 (view toggle), 14 (table wrapper), 16 (cards), 18 (plot panel), 22 (toe-tag right edge), 999 (chips, pills). A rounded grave has a top radius of half its width.
- Elevation: paper `0 30px 80px rgba(0,0,0,.45)`. Grave cast shadow `0 18px 0 -6px #1A150F` (an offset earth block, not a blur). Cursed glow is `drop-shadow(0 0 22px rgba(196,174,245,.45))`.
- Targets: buttons and chips 44 px high, primary submit 54 px. No interactive target is under 24 px (WCAG 2.5.8).

## 4. Motion
All motion is optional decoration. Nothing may carry meaning that is not also in text.
| Motion | Definition |
|---|---|
| Fog drift | `translateX` ±90 to ±120 px, 36 to 52 s, linear, alternate |
| Lantern flame, dirt | 1.4 s ease-in-out opacity .6 to 1; dirt 2.2 s ease-out, moves (-70, -40) px, fades |
| Cursed glow | 4 s ease-in-out opacity .5 or .55 to 1 |
| Star twinkle | 5 s ease-in-out opacity .9 to .35 |
| Stone hover and focus | `translateY(-6px)`, 0.25 s ease |
| Entrances (Framer Motion) | fade and rise of at most 12 px, at most 0.4 s. Plots and the wax seal only |

Rules:
1. Every animation and transition is inside `@media (prefers-reduced-motion: no-preference)`. A global `prefers-reduced-motion: reduce` rule also sets `animation: none`, `transition: none` and `scroll-behavior: auto`. Framer Motion runs under `MotionConfig reducedMotion="user"`.
2. Nothing flashes more than 3 times a second. No parallax on scroll.
3. The landing page uses CSS animation only (no Framer Motion import) to protect its Lighthouse score.
4. Progress is conveyed by text and `aria-current`, not by animation.

## 5. State to grave mapping
Six grave types. The grave is always paired with a text label, so colour is never the only signal.
| State | Grave | Shape (viewBox 120×160) | Stroke |
|---|---|---|---|
| Cursed | obelisk with a four-point star and a pulsing halo | pointed shaft, `stone` replaced by cursed body | cursed |
| Dead | round-top stone with a cross | arch, cross `M60 38 V92 M42 56 H78` | dead |
| Ailing | rounded-top stone, tilted -7°, with a crack | squared arch, crack path | ailing |
| Resting | arch with a crescent moon and flowers | arch, moon, small blooms | resting |
| Wounded | sapling with a bandage | stem, two leaves, rotated bandage | alive green, bandage wounded |
| Alive | sapling | stem, two leaves | alive green |

Rules (PRD §7.4 wins over mockup copy):
- **Cursed** and **Wounded** are overlays, not states. Cursed can sit on any base state, and PRD §7.4 allows it on a healthy package with an old unfixable advisory. Wounded can sit on any base state.
- Choose the grave in this order: Cursed if `cursed`; else Dead or Ailing by base state; else Wounded if `wounded`; else the base state (Resting, Alive). A Dead or Ailing package that is also wounded keeps its Dead or Ailing grave and shows "wounded" in its label and pill. If both overlays are true the UI shows Cursed (PRD §7.4).
- Dead is declared-only under model v2. Ailing covers what v1 called Dead by score.
- Unknown (no verdict) draws no grave. It appears as a count and in the table as a neutral "unknown" pill.
- Pill and label text joins the base state and overlays with " · ", for example `dead · cursed`, `alive · wounded`. Accessible names use words: "Dead and cursed".
- Size encodes urgency within a scan, in four buckets (150, 124, 104, 86 px wide, height = width × 160 / 120). Buckets come from the rank of `priority` (section 4 of the `ui-core` design), never from a score threshold in the UI.
- The legend always says what size means: "Taller stones need you sooner, relative to this scan".

## 6. Components and illustrations
- Every SVG in the mockups is ported to a React component in `web/components/art/` with its shapes, coordinates and colours unchanged: night scene (stars, moon with halo, hills, chapel, dead tree, fence pattern, background stones, foreground graves, fog), the plot backdrop, the six graves (scene size and the 80×90 legend size), the lanterns (lit, working, unlit), the open grave scene, the wax seal, the toe tag, the four "how it works" illustrations, the brand mark. Do not redraw them. Change a colour only by swapping a hard-coded hex for the matching token.
- Decorative SVG is `aria-hidden="true"` and `focusable="false"`. SVG `id`s (patterns, gradients) come from `useId()` so two copies never collide.
- Scene stones are real links (`<a>`) with an accessible name, for example "pycrypto 2.6.1, Dead and cursed, priority 1 of 7".
- Buttons are `<button>`, navigation is `<a>`/`next/link`. A link styled as a button stays a link.
- Pills on parchment use state `ink` on state `pill`. Chips on dark use `surface` with a state-coloured dot, and `bone` fill with `on-bone` text when pressed.

## 7. Accessibility rules (WCAG 2.2 AA)
- Focus ring: 2 px solid, 2 to 4 px offset, **`bone` on dark surfaces and `ink` on parchment**. The mockup's table reuses the bone ring on parchment, where it is invisible (1.0:1). Do not copy that.
- No sticky or fixed element may cover a focused control (2.4.11). A "Skip to content" link is the first focus stop.
- One `<h1>` per page, no skipped levels, landmarks `header`, `nav`, `main`, `footer`. A scrollable region (a wide table) has `tabindex="0"`, a role and a name.
- Live updates go through a polite `role="status"` region that announces changes only (a stage change, completion, an error), never every poll.
- Errors say what happened and what to do next in plain words under the themed title, and are tied to their field with `aria-describedby`.
- Layout works from 360 px with no horizontal page scroll. Only a data table scrolls horizontally inside its own region.
- Text meets 4.5:1, large text and UI boundaries meet 3:1. State is never colour alone: text, shape or glyph repeats it.

## 8. Copy
- Headers darkly playful ("The lantern path", "Certificate of Death"). Evidence, errors and instructions sober and exact. Never spooky in PR text.
- Always show the plain term next to the themed one where a state is named: "Dead (abandoned)".
- Every number shown comes from the API or a committed data file. No invented counts, percentages, depths or durations. If a value is missing, say "not recorded".
- Dates `22 Nov 2026` (en-GB, UTC). The wax seal uses `22·XI·2026`.

## 9. Mockup defects not to carry over
- Bone focus ring on parchment (section 7).
- Hard-coded numbers (`208`, `17`, `142 of 208`, `68% deep`, "fresh toe tags" stream, per-state "tally so far" during a scan; a real `examined of total` counter exists while the autopsy runs and is the only number shown) and invented evidence text (`[notice text from npm]`).
- State copy that contradicts the PRD: "Cursed: dead and carrying a known vulnerability", "Wounded: still alive". Use the PRD definitions.
- Dead copy. Under model v2 Dead is declared-only, so "Dead is only ever sealed on evidence: a deprecation, an archive, the maintainer's own word" is correct. Do not describe a score as making a package Dead. A package that v1 would have called Dead by score is Ailing.
- `role="img"` with an invented label on decorative scenes.
- A submit control built as a link (`Exhume` is a `<button type="submit">`).

## 10. Carried over from the old `ui-theme.md`
- **Screens:** Landing (hero over the graveyard horizon, repo input), Exhumation (progress), Graveyard (scene, filter bar, living and resting counters, Lights On toggle), Death Certificate (a page in `ui-core`; PRD DC-1 calls it a drawer), then later: Last Rites modal (rite cards, read-only diff, Open draft PR), Coroner's Report (printable), Vigil setup (copy-paste snippets).
- **Layout:** stones ordered left to right by priority, most urgent first. Works from 360 px to 4K. Living and Resting counts shown as numbers in the header.
- **Filters:** state now; ecosystem, runtime or dev, direct or transitive, service as later specs add them.
- **States to design explicitly:** loading, partial results (fog banner when packages could not be scored), errors, empty graveyard, mobile, Lights On, reduced motion, keyboard focus rings.
- **Accessibility:** roving tabindex between stones, `aria-label` on every stone ("pycrypto 2.6.1, Dead and cursed, priority 1 of 7"), `prefers-reduced-motion`, text at 4.5:1, no information by colour alone, Lights On fully keyboard operable, axe-core in CI with zero violations.
- **Sound:** off by default (none is shipped in `ui-core`).
- **Not carried over:** the old palette and Google display font (section 1, 2), "shape encodes ecosystem" (the grave type encodes state, section 5), height by blast-radius tercile (size is a priority bucket), and moss, fog and wisps on stones (PRD GY-2, deferred, not in the mockups).
