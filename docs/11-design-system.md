# 11 — Design System


## 1. Visual direction
"Evidence folder": warm-neutral slate paper, ledger rules, mono receipts, one confident indigo. Serif headings give an official, case-file tone; sans body for speed; mono for anything that is a quoted fact.

## 2. Typography (Google Fonts, `display=swap`)
| Role | Font | Use |
|---|---|---|
| Heading | IBM Plex Serif 600 | page and section titles |
| Body/UI | IBM Plex Sans 400/500/600 | everything else |
| Receipt | IBM Plex Mono 400/500 | citation tabs, ids, quoted values, hashes |

Scale (rem): 0.75 caption · 0.875 small · 1 body · 1.125 lead · 1.375 h3 · 1.75 h2 · 2.25 h1. Line-height 1.5 body, 1.25 headings. Max line length 72ch. Fallbacks: `Georgia, serif` / `system-ui, sans-serif` / `ui-monospace, monospace`.

## 3. Color tokens
### Light
| Token | Hex | Pair and contrast |
|---|---|---|
| `--bg` | `#F6F7F9` | text on bg 16.65 |
| `--surface` | `#FFFFFF` | text on surface 17.85 |
| `--text` | `#0F172A` | — |
| `--muted` | `#475569` | on white 7.58 |
| `--primary` | `#4338CA` | white text on primary 7.90 |
| `--verified-fg/bg` | `#166534` / `#DCFCE7` | 6.49 |
| `--review-fg/bg` | `#92400E` / `#FEF3C7` | 6.37 |
| `--removed-fg/bg` | `#991B1B` / `#FEE2E2` | 6.80 |
| `--neutral-fg/bg` | `#334155` / `#E2E8F0` | 8.40 |
| `--info-fg/bg` | `#3730A3` / `#E0E7FF` | 8.06 |
| `--border-input` | `#8493A8` | on white 3.12 (≥3:1 for UI boundary) |
| `--danger` | `#B91C1C` | white text 6.47 |

### Dark
| Token | Hex | Pair and contrast |
|---|---|---|
| `--bg` | `#0B1220` | — |
| `--surface` | `#121B2E` | text `#E6EAF2` 14.25 |
| `--muted` | `#9AA6BC` | on surface 7.00 |
| `--primary` | `#A5B4FC` | on surface 8.62; dark text on primary button 9.39 |
| `--verified-fg/bg` | `#86EFAC` / `#0F2A1B` | 10.94 |
| `--review-fg/bg` | `#FCD34D` / `#34270A` | 10.11 |
| `--removed-fg/bg` | `#FCA5A5` / `#3A1111` | 8.72 |
| `--border-input` | `#5B6B85` | 3.18 |

Implementation: define on `:root`; override in `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. `body` gets an explicit background.

## 4. Spacing, radius, elevation
Spacing 4-pt scale: 4, 8, 12, 16, 24, 32, 48. Page gutter 16 px (mobile) / 32 px (desktop). Radius: 6 (inputs/chips), 10 (cards). Elevation: border 1 px plus a faint shadow on modals only; no heavy shadows. Ledger rule: 1 px `--border` lines between claim rows.

## 5. Components
| Component | Spec |
|---|---|
| **Status chip** | icon + text, never color alone. Verified ✓, Needs review !, Removed ✕, Neutral •. 24 px high, radius 6 |
| **Citation tab** | mono 12 px, neutral bg, left 3 px primary edge, hover raises; click opens source panel; focusable, `aria-label="Source shp:9 tracking_number"` |
| **Claim row** | number · chip · claim text · tabs row · actions (Keep/Remove). Removed text has strikethrough **plus** reason line |
| **Source panel** | right drawer ≥1024, bottom sheet on mobile; highlights quoted value with `<mark>` styled with info colors |
| **Untrusted block** | dashed border, label "Buyer-written, treated as untrusted" |
| **Primary button** | primary bg, white text, 40 px min height; disabled state 60% with cursor not-allowed and text remains readable |
| **Danger button** | `--danger`, used only for irreversible actions |
| **Banner** | info / warning / error with icon; persistent for SANDBOX and REPLAY |
| **Budget meter** | bar + numeric text "$2.40 / $20" (not color-only) |
| **Payload preview** | mono block, copy button, collapsible |
| **Chart** | CSS/SVG bars with CI whiskers, direct labels, colors from tokens; baseline neutral, ours primary |
| **Skeleton** | neutral shimmer; disabled under reduced motion |

## 6. Interaction and motion
150–200 ms ease-out for panel slides and chip changes. No decorative animation. Reduced-motion: no transitions. Focus ring: 2 px `--primary` with 2 px offset.

## 7. Iconography
Inline SVG, 1.5 px stroke, own simple set (check, alert, x, link, shield, clock). No PayPal or third-party brand marks.

## 8. Voice and microcopy
Direct and calm. Examples: "Removed: this value is not in any record." · "We recommend accepting. Not enough verified evidence." · "Sandbox only. Nothing here touches live PayPal."

## 9. Implementation notes
Tailwind via CDN with `theme.extend` mapping tokens to CSS variables. HTMX swaps for claim actions. No external images. Set `<title>` per page. Layout tested at 360, 768, 1280, 1440.

## 10. Design QA checklist
- [ ] Every text/background pair appears in the tables above
- [ ] Light and dark both checked
- [ ] Status shown without color (grayscale screenshot test)
- [ ] Keyboard-only run of the submit flow
- [ ] 200% zoom: no clipping
- [ ] Screenshot of each screen in all states saved in `docs/screens/`
