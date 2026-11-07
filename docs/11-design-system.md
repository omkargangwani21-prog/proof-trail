# 11 — ProofTrail visual system

> Revision 3 · 2026-11-07. This system is for a merchant reviewing a case file, not a generalized fintech dashboard. The code uses tokens for all color, type, space, shape and elevation decisions.

## Direction: the evidence docket

ProofTrail should read like a careful clerk assembled a case file from source records. The interface’s memorable detail is a citation receipt attached to each drafted claim. Each receipt carries the claim number, record ID, field and quoted value; activating it opens the exact source record and highlights that value. The source relationship is the visual signature. Everything around it stays quiet: warm file paper, graphite ink, thin rules and a restrained burnt-clay annotation color.

This keeps the useful warmth of paper from the previous direction, but removes the highlighter-yellow stripe as a generic product accent. Burnt clay is used for active review, links and receipt registration marks. Status colors retain familiar meanings and always pair with an icon and label. There are no brand marks, gradients, decorative cards, or color-only states.

## Typography

Google Fonts: **Instrument Sans** for interface text and **IBM Plex Mono** for source IDs, timestamps, quoted evidence and payload. They are real typefaces with local system fallbacks.

| Role | Font | Size / line height | Use |
|---|---|---:|---|
| Page title | Instrument Sans 600 | 30 / 36 px | Screen title, no hero treatment |
| Section title | Instrument Sans 600 | 20 / 26 px | Timeline and draft sections |
| Body | Instrument Sans 400 | 15 / 22 px | Case content and claims |
| Control / label | Instrument Sans 550 | 13 / 18 px | Buttons, table headings and metadata |
| Supporting text | Instrument Sans 400 | 13 / 18 px | Secondary context |
| Receipt / record | IBM Plex Mono 400/500 | 12 / 18 px | IDs, source fields and quoted values |
| Amount | Instrument Sans 600, tabular numerals | 15 / 20 px | Right-aligned currency |

Body copy stays under 72ch when possible. Headings are sentence case. No tracked uppercase eyebrow above headings.

## Color and contrast

WCAG contrast ratios below use the WCAG 2.x relative-luminance formula, rounded to two decimals. Body and control text pairs are all above 4.5:1. Borders and focus indicators are non-text boundaries and exceed 3:1 against their adjacent surface.

| Text token | Light background | Contrast | Dark background | Contrast | Use |
|---|---|---:|---|---:|---|
| `--ink` `#24251F` / `#EEE9DF` | `--paper` `#F4F0E7` | 13.58:1 | `--paper` `#171916` | 14.62:1 | Main text |
| same | `--surface` `#FBF9F4` | 14.68:1 | `--surface` `#20231E` | 13.14:1 | Detail surface |
| `--muted` `#55574E` / `#B7B7AA` | `--paper` | 6.46:1 | `--paper` | 8.73:1 | Secondary text |
| `--accent-ink` `#873923` / `#E3A08A` | `--paper` | 6.99:1 | `--paper` | 8.14:1 | Links and active review |
| same | `--receipt` `#F1E5DA` / `#30241F` | 6.43:1 | 6.91:1 | Citation receipt text |
| `--muted` `#55574E` / `#B7B7AA` | `--surface` `#FBF9F4` / `#20231E` | 6.98:1 | 7.85:1 | Secondary copy on raised surfaces |
| `--ink` `#24251F` / `#EEE9DF` | `--receipt` `#F1E5DA` / `#30241F` | 12.48:1 | 12.42:1 | Receipt field text |
| `--accent-ink` `#873923` / `#E3A08A` | `--accent-pale` `#E9D3C5` / `#58352B` | 5.53:1 | 4.93:1 | Selected review choice |
| `--info-ink` `#36566F` / `#A7C6DA` | `--surface` `#FBF9F4` / `#20231E` | 7.34:1 | 8.88:1 | Sandbox marker on header surface |
| `--verified-ink` `#175B41` / `#9BD3B5` | `--verified-bg` `#E2EEE5` / `#163126` | 6.74:1 | 8.24:1 | Verified icon and text |
| `--review-ink` `#80401C` / `#E9BB7A` | `--review-bg` `#F6EBDD` / `#392A1A` | 6.69:1 | 7.80:1 | Needs review icon and text |
| `--removed-ink` `#8F2F26` / `#F0A69B` | `--removed-bg` `#F5E5E0` / `#3D211F` | 6.60:1 | 7.41:1 | Removed icon and text |
| `--info-ink` `#36566F` / `#A7C6DA` | `--info-bg` `#E6EDF2` / `#202F39` | 6.54:1 | 7.68:1 | Sandbox / informational state |
| `--on-button` `#FBF9F4` / `#171916` | `--button` `#24251F` / `#EEE9DF` | 14.68:1 | 14.62:1 | Primary action |
| `--rule-strong` `#70736A` / `#77796F` | `--surface` | 4.59:1 | `--surface` | 3.60:1 | Input/table boundaries |
| `--focus` `#873923` / `#E3A08A` | `--surface` | 7.56:1 | `--surface` | 7.32:1 | Visible focus ring |

`--rule` is decorative only (`#D8D3C8` light; `#34372F` dark). Do not use it for meaningful boundaries. Dark mode is automatic from system preference and can be explicitly selected with `data-theme="dark"`; an explicit light choice overrides the system.

## Layout and spacing

- Spacing scale: 4, 8, 12, 16, 24, 32, 48 and 64 px.
- Main content max width: 1320 px; page gutters: 32 px at desktop, 24 px at tablet, 16 px at mobile.
- Queue rows are open and ruled, not enclosed in repeated cards.
- Case review is two columns at ≥ 1024 px: chronology at 34%, draft at 66%. Between 640 and 1023 px, chronology stacks above the draft. Below 640 px, the source panel becomes a bottom sheet and the action bar pins to the viewport bottom.
- Radius: 0 on data rows and receipt slips; 2 px on inputs and buttons; 4 px only on menus and modal. No pill badges.
- Elevation: none on normal content; one restrained shadow on the modal/drawer only.

## Signature component: citation receipt

A claim is followed by one or more receipt slips. Each slip visually attaches to its claim using an asymmetrical edge, a short perforation rule and a narrow clay registration stripe. It shows a stable source ID, exact field and short quoted value. The entire slip is a keyboard-operable button. It is not a colored badge or a generic card. On activation, the drawer shows all source-record fields with the quoted field/value highlighted. If the quoted source is unavailable, the claim shows “Source record unavailable” and a retry path; never fabricate replacement text.

## Status and controls

| State | Visible mark | Text | Color role |
|---|---|---|---|
| Verified | Check mark | Verified | Green |
| Needs review | Open circle with dot | Needs review | Amber |
| Removed | Cross | Removed | Red |
| Informational | Small outlined square | Sandbox / Dry run | Blue |

Icons reinforce words, never replace them. Buttons are at least 40 px tall; every pointer target is at least 24 by 24 px. Focus is a 2 px accent ring with 2 px offset. Modal focus is trapped and restored; Escape closes it. Reduced motion disables transitions. Source panels remain functional without animation.

## Theme and future surfaces

Use the same paper/ink/copper palette in both themes. In dark mode, receipt slips are warmer than the background so source provenance remains distinct without glow. The future Trail viewer should render linked record slips on a single chronology. The Demo Agent should use a plain event log and an explicit buyer-approval step. Eval Results should use small multiples and labeled intervals rather than oversized KPI cards. Settings should be a simple form with visible sandbox host. These future surfaces are specified for continuity and must not appear in navigation until they exist.
