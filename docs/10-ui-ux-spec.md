# 10 — UI/UX Specification


## 1. Design concept: "the evidence folder"
ProofTrail should feel like a careful case file, not a chatbot. Ledger rules, mono citations, calm color, claims presented as **entries with receipts**. The one memorable element: **citation tabs**, small mono pills attached to each claim like paper tabs, that open the exact source record beside it.

## 2. Principles
1. **Proof over prose.** Claim + receipt, always.
2. **Deadlines visible.** What is due sits first.
3. **Human decides.** The primary button is a review action, not "auto".
4. **Calm.** No red unless something is removed or broken.
5. **Honest failures.** Errors say what happened and what to do.

## 3. Users and context
Maya (operator) on a laptop at a desk, needs scan-and-decide. Secondary: judge watching a video at 1080p. Primary viewport 1280–1440 px; must work down to 360 px.

## 4. Information architecture
```
Top bar: [ProofTrail]  Disputes · Trail · Demo Agent · Eval · Settings      [SANDBOX] [Budget $x/20] [mode]
```

## 5. Screens and wireframes

### 5.1 Disputes queue
```
+-----------------------------------------------------------------------------+
| ProofTrail  Disputes  Trail  Demo Agent  Eval  Settings   SANDBOX $2.4/20 LIVE|
+-----------------------------------------------------------------------------+
| Disputes needing action (3)                              [Filter v] [Refresh]|
|-----------------------------------------------------------------------------|
| ● Due in 2d   ITEM_NOT_RECEIVED   $49.00   #D-77   Draft ready  [Review ->] |
| ● Due in 6d   UNAUTHORIZED        $120.00  #D-81   No draft     [Draft ->]  |
| ○ Resolved    ITEM_NOT_AS_DESC    $19.00   #D-70   Won/Lost not shown       |
+-----------------------------------------------------------------------------+
```
States: empty ("No disputes yet. Run the Demo Agent or load fixtures"), loading skeleton, error banner. Due date shown only if API returns it **[VERIFY]**; else "Due: not provided".

### 5.2 Dispute workspace (hero screen)
```
+-----------------------------------------------------------------------------+
| ← Queue   Dispute D-77 · ITEM_NOT_RECEIVED · $49.00 · Stage: CLAIM          |
+--------------------------+--------------------------------------------------+
| Timeline                 | Draft response            Decision: CONTEST       |
| 10/01 Order placed       |--------------------------------------------------|
| 10/02 Shipped (trk ...)  | 1 ✓ Verified   "Order shipped 10/02 via UPS."    |
| 10/05 Marked delivered   |     [shp:9 tracking_number] [shp:9 shipped_at]   |
| 10/09 Dispute opened     | 2 ! Needs review "Buyer signed for the parcel."  |
|                          |     [no receipt found]            [Keep][Remove] |
| Buyer message (untrusted)| 3 ✕ Removed   "Delivered to front door."         |
| ┌──────────────────────┐ |     Reason: value not in any record              |
| │ "I never got it..."  │ |--------------------------------------------------|
| └──────────────────────┘ | Missing evidence: Signature confirmation         |
+--------------------------+--------------------------------------------------+
| Source panel (slides in on citation tab click): record, field, quoted value |
+-----------------------------------------------------------------------------+
| Verified 1 · Needs review 1 · Removed 1        [Accept claim] [Review & submit]|
+-----------------------------------------------------------------------------+
```
Interactions: clicking a citation tab opens the Source panel highlighting the quoted value. "Review & submit" opens the confirm modal (5.2b). Sticky action bar.

**Abstain card** (replaces draft when ABSTAIN):
```
+---------------------------------------------------------+
| We recommend accepting this claim                       |
| Not enough verified evidence to contest honestly.       |
| Missing: Proof of delivery, Carrier confirmation        |
| [Accept claim ▾ allowed type]   [See what was checked]  |
+---------------------------------------------------------+
```

### 5.2b Confirm modal
```
+------------------------------------------------+
| Review before submitting         SANDBOX · DRY RUN |
| Payload preview (exact JSON/multipart fields)  |
| • 1 verified claim included                    |
| • 1 removed claim excluded                     |
| [ ] I reviewed these claims and approve them   |
| [Cancel]                 [Approve and submit]  |
+------------------------------------------------+
```
Button disabled until the checkbox is ticked. Focus trap, Esc closes.

### 5.3 Trail viewer
```
Order #A-12  Origin: AI agent      Chain: ✓ Verified (3 events)
 ┌intent──────┐ → ┌cart────────┐ → ┌payment─────┐
 │"buy X <$50"│   │X $49 qty1  │   │capture ID.. │
 │hash a1f3.. │   │hash 9be2.. │   │hash 0c77.. │
 └────────────┘   └────────────┘   └────────────┘
 [Tamper test: modify event 2] → Chain: ✕ Broken at event 2
```
Footnote: "Tamper-evident, not tamper-proof."

### 5.4 Demo Agent simulator
Form: shopper intent text → agent steps list (intent, cart, order created, awaiting buyer approval, captured). Clear "Sandbox buyer approval required" step.

### 5.5 Eval results
```
Unsupported claims in final payload (lower is better, 95% CI)
 Baseline  ████████████████  x%
 Cited     ██████████        y%
 ProofTrail ██               z%
[Model table] [Cost table] [Failure browser] [Reproduce: commit, seed, models, date]
Banner: Synthetic data. n = 40 cases × 5 runs.
```
Chart values come from `results.json`; never typed by hand.

### 5.6 Settings
Mode (live-sandbox / replay), budget meter, key status as "set / not set" only, base URL (read-only, must be sandbox).

## 6. Components
Status chip, citation tab, claim row, source panel, timeline, payload preview, budget meter, mode badge, banner, empty state, skeleton. Specs in doc 11.

## 7. Content rules
Plain words. Buttons are verbs: "Review & submit", "Remove claim". Error text: what happened + what to do. Never "AI-powered" marketing. No PayPal logos.

## 8. Accessibility (WCAG 2.2 AA)
- Status uses **icon + text + color**, never color alone.
- Contrast per doc 11 table.
- Visible focus ring 2 px, 3:1 against adjacent colors.
- Full keyboard path; no single-key shortcut for approve.
- Modal traps focus and returns it.
- Live region announces verdict changes.
- Targets ≥ 24 px (WCAG 2.2), aim 40 px.
- Respect `prefers-reduced-motion`.
- Tables have proper headers; claim list is an ordered list.

## 9. Responsive
≥1024: two columns. 640–1023: timeline collapses above draft. <640: single column, action bar becomes bottom sheet.

## 10. States checklist (every screen)
Loading, empty, error, partial, success, offline/replay.

## 11. Usability test (self + 2 peers if possible)
Task 1: find the soonest due dispute (<10 s). Task 2: explain why claim 3 was removed. Task 3: submit in dry-run. Note failures in `docs/usability-notes.md`.
