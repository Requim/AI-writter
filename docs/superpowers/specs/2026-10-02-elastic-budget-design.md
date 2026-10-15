# Elastic Budget Design

Approved scope: optimize the legacy request budget, then resume the same
`long-r3` 80-chapter acceptance book on Tencent. The earlier proposal to
raise the total to 3920 is withdrawn. The current total remains 3280.

## Contract

- AC-B1: Every physical model request atomically checks actual cumulative
  spend against the persisted book total. Provider failures and unknown
  outcomes remain charged. Search is a separate allowance, not a model call.
- AC-B2: Explicit owner/admin activation through a typed, tenant/book-scoped,
  versioned and idempotent API changes allocation only. It preserves all
  limits, counters, manuscripts, recovery history and tenant quotas.
- AC-B3: Under the opt-in `elastic_v1` policy, the existing chapter allocation
  becomes a soft threshold. The provisional safety cap is 64 requests.
  Unused allocations can be borrowed only while preserving unspent preparation
  and review allowances and 24 requests for each future chapter.
  These are conservative, uncalibrated scheduling parameters, not a guarantee
  that a chapter can pass quality within 24 requests.
- AC-B4: Before an elastic review or repair cycle starts, atomically hold
  12 or up to20 requests respectively. A repair may reserve18 when that is
  the remaining safe capacity: its bounded ordinary short-body footprint is
  patch3 + fallback1 + fact1 + editorial4 + main-review2 + quote-repair1 +
  derived metadata6 =18 physical calls. Extra fact-recovery rounds or provider
  failures are not guaranteed to complete within a hold and must stop safely.
  Holds are not spend. Physical requests
  consume a hold once; restart/replay cannot replenish it. An exhausted hold
  pauses before another provider call. A new repair for an unchanged body
  cannot repeatedly obtain a fresh hold. Completed postprocessing releases
  the unused hold, without refunding physical requests.
  A separate15-call local-only repair is eligible only for a <=6000-character
  body with a fresh passed goal receipt, a patch decision and grounded must-fix
  findings, without rewrite instructions. Its one-attempt patch has no full
  rewrite fallback; unchanged-body cycles cannot switch repair purposes to
  obtain another hold. Patch scope and every independent review stay intact.
  Bounded ordinary footprint: patch1 + fact1 + editorial4 + main-review2 +
  quote-repair1 + derived metadata6 =15. Larger bodies, blocked/stale goals
  and full rewrites still require the ordinary18-call minimum.
  Local model output selects existing immutable paragraph IDs; the server
  resolves the original contiguous anchor before applying unchanged scope,
  evidence, uniqueness, overlap and issue-ID validation. Invalid references
  or conflicting copied anchors are rejected, never silently normalized.
- AC-B5: An autonomous retry does not reset fact, extraction or quality
  recovery counters. Public budget diagnostics use the same allocation
  calculation as physical metering, not the obsolete soft threshold.
  An audited, unchanged-body fact-staging proposal confirmation with no quality
  issues is classified separately from actual prose repairs. Exclusion requires
  the same accepted goal, unique attempt number, valid provenance and matching
  body hashes. Preserve historical aggregate counters and expose a separate
  purpose-aware accounting receipt. Do not increase the effective repair maximum.
- AC-B8: Autonomous local patches may edit only grounded must-fix issues,
  not nonblocking style suggestions. Manual revision behavior is unchanged.
- AC-B6: Requests retain provider usage when available, purpose, policy,
  round identity and latency. A timeout is explicitly recorded as unknown,
  with no refund. Missing token usage is not interpreted as free usage.
- AC-B7: Real PostgreSQL tests cover concurrency, replay, failure, scope and
  preservation. Qualify the complete backend and deploy the exact tested
  source with fresh rollback pins and unchanged-data checks. Resume the same
  book only through normal authenticated APIs.

## Boundaries

No automatic migration of other books, no increase in the tenant/monthly,
search or whole-book limits, no direct checkpoint or manuscript edits.
No acceptance of stale/unknown quality reports and no increase in global
reflection loops. Manuscript quality issues remain separate evidence-driven
repairs. The full production objective remains open until actual 80 chapters,
ending, complete manuscript quality, exports and tenant isolation pass.

## Storage

Use additive keys in the existing session `limits` JSON for the typed policy
and current round. Preserve historical counter keys. Immutable system control
records capture round creation/release; request receipts capture actual spend.
No database migration is required. Old code must not run against an activated
elastic session without first explicitly removing the unspent policy/hold
through a controlled recovery; image rollback alone is not a budget-policy
rollback.

## Approved Narrow Exception

On2026-10-02 the user approved one additional goal repair for long-r3's first
chapter on exact source085a7e46/contract91bf5a77/failing event15816 only.
The owner-only typed control may set that chapter's safety ceiling72 without
changing default64 or book3280. Store additive `limits.chapter_extension`
and a server-owned failed-review control in session config, with locked/CAS
immutable command audit and original-response replay. No duplicate stacking.
Runtime checks the current body/accepted source/sole failed must-event and
normal history before replaying the existing failed review into a local
repair. It does not mark goals passed; all post-patch acceptance is fresh.
Normal revision history consumes the authorization once. Preserve every
fact counter, historical request and the other chapters' default guards.

## Approved Progress Repair

The user's subsequent "改进一下" approves the proposed action-state and
progress-budget improvements. This is not approval to raise a physical cap:
book3280, first chapter72, other chapters64, tenant/monthly/search limits
and all historical spend remain unchanged.

The owner-only `creative/repair-policy` control enables typed `progress_v1`
only for the selected book. Activation uses locked CAS, the latest real
failed quality event, body/goal hashes and immutable idempotent command
receipts. It changes config/version only. The initial failed review may
route to repair without another paid review; it never authorizes archive.

Only short, high-scoring, goal-passed manuscripts with grounded local
must-fix evidence qualify. A changed body and a new issue fingerprint are
required after prior repairs. Unchanged edits, unresolved/reintroduced
findings, stale goals or fewer than9 available requests stop safely.
Preferred local hold15, minimum9; closed same-body cycles cannot refill
under a different repair purpose. Generation gets one attempt and cannot
fall back to a whole-chapter rewrite. Every actual request still charges
the unchanged physical budgets. Existing cumulative recovery/fact history
is preserved with separate purpose accounting.

Post-archive state updates use the existing book review pool for opted-in
books, with no transfer/refund of old spend. Chapter holds are released
only after successful postprocessing. Other books retain their old policy.

Editorial protocol v3 adds server-enumerated action cues and an ordered,
object-bound predecessor/state checklist to the existing observation
stage. Unknown/missing/skipped checks are not complete receipts. A reported
contradiction requires paired literal evidence. Negation, metaphor and
explicit restoration are not automatically errors. Old v2 receipts do
not satisfy v3 freshness. These structural checks improve coverage but
do not prove exhaustive human-quality semantic judgment.

### Production Feedback Refinement

The first real v3 attempt exposed invalid predecessor links and expensive
reasoning; old unavailable-review recovery repeated complete observations.
Do not interpret returned JSON or completed provider receipts as valid review.
Emit the rejected action/object/link and the server-expected predecessor
in correction feedback. Clarify aN versus pN and exact stable object names.
Keep all predecessor, quote and contradiction checks; no coercion into pass.

For progress_v1 only, independent reflection/editorial/main acceptance
requests now charge the existing review660 pool, as do postprocess calls.
Prose generation, local revision and their fact checks keep their original
chapter pool. This is new-request purpose allocation, not migration/refund
of old chapter spend. Book3280 and chapter72/64 ceilings remain unchanged.
Review holds still constrain physical spend and are released after successful
postprocessing. Other books retain their original accounting.

Two invalid component reports pause with `editorial_evidence_invalid`;
the old whole-review retry loop is not automatically restarted. A legacy
unavailable editorial proposal may migrate once per exact body/current
protocol-template binding into fresh review. Its audit is appended to
automatic_recovery without changing any old fact/quality/review counters.
This does not accept the old report or manuscript, change goals, waive a
budget check or refill a closed same-body hold.

Archive-time persist_node fact revalidation is also independent acceptance
and uses the opted-in review pool. Generation/revision and their fact checks
remain chapter-scoped; no old receipt moves between pools. This correction
was verified at a physically exhausted chapter72 with normal archive,
preserved goal/editorial/fact guards and unchanged whole-book3280.

### Full-Source State Evidence

An action candidate's primary object is not a complete paragraph inventory.
The real second chapter established glove state in a paragraph primarily
checking a register; the matching glove action later had no same-labelled
predecessor. Requiring both paired quotes to belong to selected same-object
checks rejected a legitimate must-fix report. Descriptive states without
action cues are likewise admissible original evidence.

Use the full server-owned source catalog for earlier paragraph identity and
chronology. The earlier evidence range must end before the current candidate;
the last quote remains anchored at the current candidate. Base validation
still requires real, uniquely located, ordered original quotes. Same-object
nearest action links and exhaustive action coverage remain separate guards.
A valid contradiction remains must-fix and blocks archive; this change does
not label prose consistent or accept any manuscript.

Qualified/deployed source49b3b383 has1279 passing tests and preserved live
data/environment baselines. Original80-book acceptance is still open.

### Semantic Identity And Correction Context

The second chapter also demonstrates that equal identifiers across a
comparison volume and the original worksheet do not establish one physical
sheet. Prompt criteria now require compatible subject/object/property/time
and distinguish unknown initial creases from proved state contradictions.
Ordinary omitted actions across scene/time changes are not automatically
must-fix; definite continuous-scene contradictions still are.

The bounded second format attempt receives its rejected report as data,
not instructions. Above30000 characters it receives an explicitly truncated
JSON preview. It must return a complete independently validated report;
there is no coerced pass, extra attempt or waiver of evidence requirements.
Qualified sourcefefb978d4 has1283 tests. Unit tests establish this mechanism
and prompt contract only; actual model semantic verification remains open.

Exact qualified sourcefefb978d4 is deployed at2026-10-02T15:56:27Z.
All paused data/counter/checkpoint and environment baselines are unchanged,
ready200. Normal retry74e9ef0b resumes the same3888-character manuscript;
real semantic/second-archive and full80-book acceptance remain open.

Real chapter2 archive subsequently succeeds:3888-character bodyf3ad0535,
fresh goal acceptance, complete editorial104/39/findings[], passed fact-v5
gate, all3 histories preserved and normal postprocessing. This establishes
the mechanism on the real book, not clean-content certification: main review
retains optional identifier-count and referent issues. Same80-book2/80,
third chapter reviewing at2026-10-02T16:14:05Z. Full-book acceptance is open.
