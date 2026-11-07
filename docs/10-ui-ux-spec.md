# 10 — UI/UX specification

## Product surface and user job

ProofTrail helps a small merchant operator decide quickly whether evidence supports a PayPal sandbox dispute. The user must inspect a deadline, understand the buyer’s message, check claims against source records, and explicitly approve an exact payload. The review screen is the product; there is no marketing home page.

## Design direction

Use the evidence docket system in [11-design-system.md](11-design-system.md). The defining interaction is a citation receipt attached to each claim. Selecting it opens the exact source record and highlights the quoted field value. This comes from line-attached review patterns: the claim and its evidence must be inspected together. Queue deadlines borrow from case-management worklists; final submission borrows from payment confirmation flows, with a clearly enumerated payload and explicit approval.

## Information architecture

Only **Disputes** appears in primary navigation because it is the only built product surface. The queue is `/disputes`; each case opens at `/disputes/{paypal_dispute_id}`. Trail viewer, Demo Agent, Eval results and Settings are future surfaces and are not nav items.

The shell shows an unobtrusive **Sandbox** marker with a tooltip that says nothing here touches live PayPal. The header spend meter is labeled **Model spend**; its tooltip explains it is language-model credits against the configured hard cap. No spend figure is invented.

## Disputes queue

Use a full-width, open table with columns for Respond by, Dispute, Amount, Status and Action. Needs-action rows sort first by earliest known deadline, followed by other cases. The latest draft status affects the action label. A `SUBMITTED` or `SUBMITTED_DRY_RUN` latest draft never appears in Needs action. Use plain-language dispute reasons and monospace PayPal IDs. Amounts are tabular and right aligned. On mobile, each row becomes a labeled, open record section; it must not clip or require horizontal scrolling.

## Dispute workspace

The header identifies the reason, PayPal ID, amount, PayPal status and deadline. At desktop widths, a left chronology shows order → shipment → delivery → dispute; a missing event is stated as unavailable rather than invented. Buyer messages appear under “Buyer message” and are visibly labeled **Untrusted text**. The evidence draft sits to the right.

Claims are a numbered list, grouped by verifier verdict:

- **Verified:** check icon and word; claim text; attached citation receipt(s).
- **Needs review:** open-circle icon and word; claim text; attached receipts and Keep / Remove choice.
- **Removed:** cross icon and word; struck-through claim, removal reason and receipt(s), when available.

A missing-evidence list names only items from `verification_json`. A source panel displays the full record from `source_records`, its record ID and kind, and the precise quoted value highlighted. On wide screens it opens at the right; on narrow screens it opens as a bottom sheet. It closes by close button and Escape, returns keyboard focus, and never hides the whole case context.

An Abstain decision replaces the submission panel with **“We recommend accepting this claim”**, followed by missing evidence and what the verifier checked. Do not offer a contest-submit action from that state.

A sticky action bar shows verified, needs-review and removed counts, and the review/submission action only when a submittable draft exists. Needs-review claims must be explicitly kept or removed before the confirmation action is enabled. Any kept item must be included only if the stored payload supports it; otherwise the UI must block submission and explain why rather than silently altering the database payload.

## Confirmation

The confirmation dialog shows **Sandbox · Dry run** or **Sandbox submission** from the selected mode. It previews the exact `payload_json` content and counts included and excluded claims. It requires an explicit acknowledgement checkbox before enabling the primary action. Focus is trapped while open, Escape and Cancel close it, and focus returns to the opener. A completed dry run must be labeled “Dry run complete”; do not say PayPal received the evidence. Real sandbox API submission must be clearly labeled “Submitted to PayPal sandbox”. Nothing in this application can address live PayPal.

## States and copy

Every route and state uses direct sentences and a safe next action.

| State | Queue | Dispute workspace |
|---|---|---|
| Loading | “Loading disputes…” with stable row placeholders. | “Loading this dispute…” with chronology and draft structure retained. |
| Empty | “No disputes yet. A sandbox dispute will appear here after it is created.” | No case id: “This dispute is not in the local case file. Return to disputes and refresh the list.” |
| Error | “Disputes could not be loaded. Check the local database, then refresh.” | “This case could not be loaded. Return to disputes and try again.” |
| Partial | “Some dispute details are unavailable. Open a case to inspect its source records.” | Identify the missing order, shipment, buyer message or source record directly. Keep verified details available. |
| Success | “No disputes need a response.” or list the answered cases. | “Dry run complete. No request was sent to PayPal.” / “Submitted to PayPal sandbox.” |

No lorem text, placeholder data or “Not built yet” pages. Dev-only fixtures are loaded only when both `PT_ENV=development` and `PT_UI_FIXTURES=1`; production always reads SQLite.

## Accessibility and responsive behavior

Target WCAG 2.2 AA: minimum 4.5:1 normal-text contrast, 3:1 non-text boundaries, visible focus, keyboard-only access to citations and decisions, status with both text and icon, labels for form controls, accessible dialog name and focus trap, reduced-motion support, and target size ≥ 24 px (40 px default for buttons). Screen-reader live region announces source-panel changes and review-state updates.

Required screenshot widths: 1440, 1280, 768 and 390 px. Desktop two-column case layout begins at 1024 px; tablet stacks the timeline before the draft; mobile uses one column, a bottom source panel, and a pinned action area that leaves content scrollable. No horizontal overflow at any width. Support explicit light and dark theme states.

## Acceptance checks

1. A submitted or dry-run-submitted dispute never appears in Needs action.
2. Model spend has the visible label and explanatory tooltip.
3. Each citation opens the same record and exact field/value represented by the stored claim.
4. Removed claims are visibly crossed out and include the stored removal reason.
5. Missing evidence and Abstain recommendation come from stored verification JSON.
6. Modal payload is byte-for-byte equivalent at the data level to the payload being submitted; approval is explicit.
7. Empty, loading, error, partial and success states have useful, direct copy.
8. Four target widths render with light and dark themes; keyboard/focus and reduced motion are checked.
