# ProofTrail interface research

Research conducted 2026-11-07 using public product documentation, product tours, and interface descriptions. The sample covers 33 distinct product surfaces across disputes, case management, legal/compliance review, code review, and finance. The aim is to learn workflow patterns, not reproduce brand styling or layouts. Where a source documents a workflow rather than publishing a full screen capture, observations are limited to that documented flow.

## Interfaces reviewed

### Disputes and chargebacks

1. [Stripe: handling disputes in the Dashboard](https://support.stripe.com/questions/how-to-handle-disputes?locale=en-GB) — distinguish accepting a dispute from challenging it; put the response decision in the case context.
2. [Stripe: visual evidence examples](https://docs.stripe.com/disputes/visual-evidence) — evidence is grouped around the disputed reason, and the submitted packet is legible as a response rather than as an analytics page.
3. [Stripe: dispute workflow and evidence guidance](https://stripe.com/guides/introduction-to-payment-disputes) — show the deadline and relevant evidence, while leaving the business responsible for its response.
4. [Adyen: Risk & dispute analytics](https://docs.adyen.com/risk-management/dispute-and-fraud-monitoring) — trends and case operations are different jobs; broad analytics belong away from a single-case decision surface.
5. [Adyen: Manage disputes](https://docs.adyen.com/risk-management/manage-disputes) — accept and defend are explicit alternatives, with status and due dates part of case operations.
6. [Adyen: dispute components](https://docs.adyen.com/marketplaces/components-overview/after-payment/disputes-component) — a queue and focused dispute detail are separate levels; respond-by dates and evidence submission are core case data.
7. [Adyen: dashboard dispute component](https://docs.adyen.com/platforms/build-user-dashboards?component=Dispute&integration=components&version=1.7.x) — open and resolved work is visible as distinct states; users can choose accept or defend.
8. [Shopify: chargebacks in admin](https://help.shopify.com/en/manual/payments/chargebacks/chargebacks-in-admin) — status explains the process; saving progress and submitting are separate actions.
9. [Shopify: chargeback response form](https://help.shopify.com/en/manual/payments/chargebacks/chargebacks-in-admin#submit-your-evidence-for-review) — review evidence before a separate confirmation; accepting remains available without evidence.
10. [Shopify: resolve a chargeback](https://help.shopify.com/en/manual/payments/chargebacks/resolve-chargeback) — open, submitted, won, lost and resolved are lifecycle states, not just colors.
11. [PayPal: Resolution Center](https://developer.paypal.com/platforms/disputes/handle-disputes/use-resolution-center) — merchant-facing response and API integration are separate workflows.
12. [PayPal: disputes overview](https://developer.paypal.com/disputes/overview) — a structured lifecycle reduces ambiguity; manual and API workflows should not be conflated.
13. [Chargeflow: merchant app](https://help.chargeflow.io/en/articles/5772300-the-chargeflow-app) — consolidate dispute work and status in one operational surface.
14. [Chargeflow: dispute automation concepts](https://docs.chargeflow.io/docs/reference/concepts/dispute-automation) — make stages from intake through submission and tracking inspectable.
15. [Chargeflow: insights](https://docs.chargeflow.io/docs/merchants/insights) — portfolio trends have a different purpose from resolving one case.
16. [Justt: platform](https://justt.ai/platform/) — reporting, predictions and case handling serve different decisions; don’t crowd each case with dashboard metrics.
17. [Justt: chargeback insights](https://justt.ai/insights/) — group performance measures and trend context into an analytics surface.
18. [Kount 360: chargeback queue migration](https://support.kount.com/hc/en-us/articles/45534272788628-Migrating-from-Dispute-and-Chargeback-Management-DCM-to-Chargeback-Management) — queues in primary navigation are easier to revisit than a mode switch hidden in a dashboard.
19. [Kount 360: chargeback dashboard](https://support.kount.com/hc/en-us/articles/45534295749652-Navigating-the-Chargeback-Management-Dashboard) — dashboards summarize work, while the case queue remains an operational entry point.

### Case, legal, and audit review

20. [ServiceNow: CSM case form ribbon](https://www.servicenow.com/docs/r/customer-service-management/csm-agent-workspace-ribbon.html) — a compact case header can hold identity, timeline and SLA context without making each a separate card.
21. [ServiceNow: horizontal case playbook](https://www.servicenow.com/docs/r/xanadu/customer-service-management/csm-playbook-horizontal-stages.html) — persistent record context beside an activity stream supports focused review.
22. [ServiceNow: workspace framework](https://horizon.servicenow.com/getting-started/app-frameworks) — list, record and role-specific action surfaces belong in one coherent workspace.
23. [Salesforce: investigative casework](https://help.salesforce.com/s/articleView?id=ind.psc_casework_overview.htm&language=en_US&type=5) — evidence can be captured as custody items and linked to proceedings, emphasizing source and relationship.
24. [Clio: matter workspace](https://help.clio.com/hc/en-us/articles/9285920226075-Get-Started-With-Matters) — the case file is the durable home for related events, documents and work.
25. [Clio: legal documents and cited sources](https://www.clio.com/features/legal-documents/) — a cited answer should take a reviewer directly to its source passage.
26. [Drata: Audit Hub](https://drata.com/products/compliance/audit-hub) — evidence requests connect to next steps; missing evidence should be stated directly.
27. [GitHub: pull request review](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request) — put findings inline with the material and offer a clear final review decision.
28. [GitHub: review comments](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/commenting-on-a-pull-request) — comments attached to exact lines make a finding actionable and auditable.

### Finance and transaction review

29. [Plaid: payment dashboard](https://plaid.com/docs/payment-initiation/payments-dashboard/) — a focused payment detail combines status, transaction facts and an activity log.
30. [Plaid: transfer dashboard](https://plaid.com/docs/transfer/dashboard/) — operational counts and activity can be scanned without decorative visualization.
31. [Ramp: real-time reporting](https://support.ramp.com/real-time-reporting) — aggregate spend reporting should not substitute for the work queue.
32. [QuickBooks: home page and dashboard](https://quickbooks.intuit.com/learn-support/en-us/help-article/product-setup/customize-home-page-quickbooks-online/L0ryPsyjD_US_en_US) — prioritize what needs attention and frequent actions over promotional content.
33. [Mercury: transaction review](https://support.mercury.com/hc/en-us/articles/38790547830036-Viewing-cashflow-and-transactions-data-on-your-Transactions-page) — transaction lists benefit from quick refinement and clear details.

## What works across these products

- **Decision before decoration.** A queue starts with deadlines and actionable state; account-wide analytics are a separate destination.
- **Status is vocabulary.** Products distinguish open, submitted, resolved, won and lost because those labels explain the next action. Color can reinforce status but cannot carry it alone.
- **Details stay attached to their case.** Order, shipment and customer communication form one chronology, while a stable record identity makes each fact findable.
- **Evidence needs provenance.** Inline findings in code and legal review work because the reviewer can open the exact source near the statement. ProofTrail should make the citation itself a small receipt: record ID, field, quoted value, and a direct path back to its record.
- **Treat submission as a commit.** Reviewing is separate from the final submission decision; confirmation should enumerate what goes in and what is excluded.
- **Keep uncertainty explicit.** An absent due date should say so. A weak or missing fact should be visible as missing, not filled by inference.
- **Use density selectively.** Queues need aligned columns and numeric consistency. A case needs a timeline and evidence beside one another. Analytics can use charts, but the case screen should not become a card dashboard.
- **Errors need recovery.** State what failed and what to retry or inspect. Empty states should say how data gets here. Partial data should identify what is unavailable.
- **Maintain a quiet shell.** Finance and review tools use restrained surfaces, clear dividers, tabular amounts, and few accent colors.

## Direction selected for ProofTrail

Use a warm, ink-on-file-paper base and a small burnt-clay annotation accent. The metaphor is a clerk’s evidence docket: a plain chronological record column and claim entries with detachable, ruled citation receipts. The receipt carries the provenance interaction; the rest stays restrained. Use sentence-case headings, an open table (not a table inside a card), green/amber/red status text paired with icons, and tabular figures. The claim receipt is a distinct shape and interaction, not a colored pill. Source details open in a right-hand drawer on wide screens and a bottom sheet on narrow screens.

Avoid logos, imitation brand layouts, gradient treatments, generic metric tiles, ornamental hero areas, decorative icons, and guessed success rates. Trust comes from showing which record supports each sentence and what happens before anything is sent.
