# Elastic Budget Implementation Plan

> Execute inline. Do not delegate or commit the pre-existing dirty tree.

**Goal:** Optimize budget allocation without increasing the 3280-request book
limit, then validate the same Tencent 80-chapter manuscript.

**Architecture:** Shared pure allocation rules are consumed by request
reservation and public diagnostics. Existing locked session JSON persists an
opt-in policy and one bounded cycle hold. Normal control APIs activate the
policy; autonomous retries preserve all recovery allowances.

**Tech Stack:** Python, SQLAlchemy async, PostgreSQL, FastAPI, LangGraph,
existing Tencent Docker Compose deployment.

**Spec:** `docs/superpowers/specs/2026-10-02-elastic-budget-design.md`

## Global Constraints

Same long-r3 book, 80 chapters, 336000 characters +/-10%; total 3280.
Other books and tenant flags unchanged. No counter reset or gate bypass.
Keep preparation/review/search limits; policy opt-in until calibrated.
Tests run on the isolated Tencent PostgreSQL QA database, not production.

## Task 1: Atomic Allocation And Cycle Holds

Files: `service/value_objects/creative_budget.py`,
`infrastructure/database/creative_allocation.py`,
`infrastructure/database/creative_repository.py`,
`tests/test_elastic_budget.py`.

- [x] RED: Seed a real session; assert the 33rd call succeeds after authenticated
  activation while total and historical 32 calls remain unchanged.
- [x] RED: Assert concurrent last-call and cycle reservations cannot overspend;
  replay/restart cannot refill a consumed cycle; missing future reserve blocks.
- [x] Implement `budget_capacity(limits, counters, bucket)` and
  `model_spent(counters)`, shared by actual metering and diagnostics.
- [x] Implement locked, persisted `begin_budget_round` and
  `release_budget_round`; requests consume remaining held allowance atomically.
- [x] GREEN: run `tests/test_elastic_budget.py` with required real database.

## Task 2: Trusted API And Runtime

Files: `api/routers/creative_router.py`,
`application/creative/runtime.py`, `application/checkpoint_budget.py`,
`application/orchestrator.py`, `tests/test_elastic_budget.py`,
`tests/test_budget_snapshot.py`, `tests/test_quality_retry_budget.py`.

- [x] RED: assert owner-only activation, exact total/CAS/idempotency binding,
  outsider rejection, and preservation of all recovery metadata on retry.
- [x] Implement typed `PUT /{novel_id}/creative/budget-policy` with
  `expected_version`, `expected_total`, `mode="elastic_v1"` and `reason`.
- [x] Begin review/repair holds from trusted runtime state, release after
  completed postprocess, reject exhausted/no-progress cycles.
- [x] Share the effective capacity with reload diagnostics.
- [x] GREEN: focused integration, metering, recovery and static tests.

## Task 3: Receipts, Qualification And Production Validation

Files: `infrastructure/llm/metering.py`,
`service/ports/model_meter.py`, request repository and focused tests.

- [x] RED/GREEN: provider timeout stays charged and records an unknown receipt;
  successful usage merges with reservation metadata.
- [x] Run full backend, Ruff, mypy and zero-provider harness on Tencent QA.
- [x] Capture current immutable image IDs, fresh data/environment checks;
  build/deploy the exact qualified source and verify readiness/preservation.
- [x] Activate only long-r3 via authenticated API, then normal same-book retry.
- [x] Observe real spending and quality results; diagnose new failures without
  blindly increasing limits. Record remaining 80-chapter acceptance work.

## Evidence So Far

Tencent isolated PostgreSQL: initial RED 9 failed/1 passed; runtime RED
7 failed/47 passed; focused GREEN 103 passed. Full run found one incomplete
pre-existing test double (missing the real session's `limits` field);
1183 other tests passed. The double was completed without relaxing production
validation; the final full rerun passed. Additional cases cover a shared
last request across distinct buckets, the hard chapter cap, identical concurrent
hold creation, and both legacy/elastic total enforcement.

## Qualified And Deployed

Source `3217d27676510566f0b26ac82045c8045185abc90676f72b7aecba1ed43218da`,
650 files. Final full backend: 1184 passed in 107.56 seconds; focused final
59 passed; Ruff and mypy 60 sources passed; harness 13 passed/provider calls 0.
The upstream LangChainPendingDeprecationWarning remains. Original qualified
`increment_budget` was loaded from the immutable previous package in a separate
QA process: both whole-book overrun counterexamples failed as expected.

Tencent release at 2026-10-02T10:02:57Z preserved all captured chapters,
tenant flags, sessions, creative records and retained checkpoint sets; all
service environment hashes and research image identities unchanged.
Live backend `sha256:0b379d4365bef64f122bcae21decab6561bb958e5d376d82951ca2c74551a8f0`;
frontend `sha256:40953f1f2959f85b2d49308f1e93059279cb5a2879fb98b2aa47e6f985ee5571`.
Rollback pins the previous `2c556fac` immutable images. Public readiness 200.

Normal public-HTTPS owner API activated only long-r3 with expected version2,
expected total3280 and an immutable reason; repeated key returned the original
response. Session version3, limits/counters preserved, policy added. Normal
same-book retry resumed the exact 3705-character retained body and recovery
2/2/3, with a persisted 12-request review hold. Physical chapter:1 request33
succeeded without changing the total or resetting historical consumption.

Fresh main review event12988 passed every goal on the exact current body,
quality score0.905714, but decision remained patch due to editorial findings.
Normal revision and independent re-review are running. No unknown goal was
converted to passed by application code and no archive gate was bypassed.
This is a verified budget boundary recovery, not 80-chapter acceptance.
The run subsequently stopped at46 calls on quality-repair accounting;
the continuation below supersedes the earlier running status.

Evidence prefix `long-r3-elastic-`: qualification, original-total RED,
final-focused, full-tests-final, Ruff/mypy/harness, release-before/after,
policy-activation, resume-receipt, review-events, new-requests and live-watch.

## Task 4: Actual Accounting Boundary

Real event15782: current3828-character candidate SHA-256
`1515ab2a9e71d37bee156e4a2c3d45fcb217820876893c1866b20a7758d206ce`,
quality0.928571 and all goals passed, but an explicitly paired front/back
page inconsistency remained must-fix. Stop was
`AutomaticRecoveryExhausted`, not physical-budget exhaustion.
Chapter46, preparation35, review1; total3280 and hard cap64 unchanged.

The existing runtime uses the review function's default maximum5.
`MAX_REFLECTION_LOOPS=3` is configured but is not forwarded into that node's
config; prior notes describing3 as the effective runtime bound were inaccurate.
This task does not raise either value. Purpose-aware counting must distinguish
the single same-body fact-staging confirmation from4 completed prose repairs,
while preserving the historical aggregate recovery2/2/5.

- [x] RED: actual-purpose accounting, nonblocking patch exclusion and an
  18-request complete minimum;3 failed/26 passed on previous code.
- [x] Correct only uniquely evidenced, same-goal, same-body fact confirmations;
  no offset for missing/changed/duplicate/invalid proof or manual mode.
- [x] Autonomous patches edit only grounded must-fix findings; manual behavior
  remains unchanged. Do not alter prose directly.
- [x] Adaptive repair hold: prefer20, allow18 at the safe boundary. Ordinary
  short-body bounded footprint: patch3 + fallback1 + fact1 + editorial4 +
  main-review2 + quote-repair1 + metadata6 =18. Failures or extra fact-recovery
  rounds may still exhaust the hold without a refund.
- [x] Zero-provider replay of the actual checkpoint with freshly read trusted
  author configuration and stored brief; normal route to revision, original
  goal/body and all2/2/5 aggregate counters unchanged. New accounting receipt
  says completed4/requested5/maximum5/fact confirmation attempt1.
- [x] Final full QA, deployment/preservation and same-book normal retry.
- [ ] Actual chapter archive and remaining full80 acceptance.

The first expanded GREEN passed83 cases but failed the static nesting gate
in the new parametrized test's elif chain. Replaced that test-only dispatch
with a case map; no production guard was relaxed. Final full QA:1195 passed
in107.04 seconds; Ruff/mypy and13 offline harness cases passed/provider0.

Source `490c499d0f0287aeff3f9f2150cb7222ea6f9234b076058cc086c7936c26655e`
was deployed with all fresh data/environment baselines unchanged. Backend
`sha256:fbe227a21450c3980817f1cd5e28d46d7ab611553c7e8df67dadcd1ae656f329`;
frontend `sha256:12086e6b151c2a453f53d5386844ee5fed3f28767c398cedb60cb3e011c774fe`.
Public readiness200 and research images unchanged; rollback pins3217 images.
Normal same-book retry `acc56596-75ed-49bf-97bf-1c4102f58f27` preserved the
3828-character body and2/2/5 aggregate counters. Fresh review consumed2 calls
(chapter48), then safely paused before revision because16 remaining cannot
fit the ordinary18-call minimum. Still0/80 archived; do not retry blindly.

## Task 5: Bounded Local-Only Repair

Actual combination boundary above, not a total-budget or quality-maximum raise.
For a short body with a fresh passed goal receipt and grounded must-fix patch
findings, remove patch-generation retries and full-rewrite fallback. Keep
fact extraction, editorial review, main review, quote validation and metadata.
The bounded ordinary cycle becomes15 calls, fitting the actual remaining16.
On unsafe/invalid patch retain the draft and stop, without escalation.

- [x] RED:3 failed/7 passed on the previous release, including normal automatic
  full fallback escaping the intended local-only scope.
- [x] GREEN/full qualification on Tencent isolated PostgreSQL.
- [x] Fresh live-data preservation, exact-source deployment and normal retry.
- [ ] Observe actual archive/80-chapter continuation without forced acceptance.

Sourcebd3a9e59:70 focused and1205 full tests passed (108.20 seconds),
Ruff/mypy and13 offline cases passed. Tencent deployment preserved all fresh
data/environment baselines. Normal run79bbd385 began a15-call local hold
on the exact3828-character draft, counted physical request49 and stopped
without a full rewrite because the generated patch failed validation.
Hold remaining14, historical counters and prose retained; still0/80.

The checkpoint retains only the outer validation error, not its cause.
The actual paired-location issue recommends correcting both p38 and p40;
the existing patch validator requires the primary evidence inside every
anchor, but the prompt never states how to group these linked edits.
A deterministic paired-edit counterexample proves the contract mismatch.
The old provider payload was not retained, so this is not claimed as proven
attribution of that particular failed response.

### Patch Contract And Diagnostic Continuation

- [x] RED:2 failed/10 passed for missing scope instructions and lost
  safe validation category; split paired edits remain rejected.
- [x] Clarify grouped contiguous evidence anchors in the patch template,
  without relaxing1500-character/30% scope or unique-anchor validation.
- [x] Preserve only allowlisted static validation messages in failure
  receipts/logs; unknown exceptions disclose only their class name.
- [x] Final full QA/deployment and normal retry using the existing15-call
  hold (remaining14), without replenishment or a new quality attempt.

The first full contract run passed1206 behavior tests but found the revision
function at51 nonempty lines (limit50). Extracted only the bounded error/log
construction, leaving the static gate unchanged. Added a negative test proving
unknown provider messages cannot enter retained errors or logs. Final full
qualification passed1208 tests in107.59 seconds, Ruff/mypy and13 offline
cases/provider0. Sourcec32f0593 was deployed with fresh baselines intact.
Actual retry6c4df1c3 spent request50 in the same hold (remaining13), then
retained the exact original draft. Its checkpoint/log now confirms the
specific failure: the generated anchor did not include the primary evidence.
No blind repeat was issued after that diagnosis.

### Server-Owned Paragraph Anchors

Use the project's existing `source_catalog`/`source_span` APIs in local-only
patches. The model selects start/end paragraph IDs and generates the complete
replacement; the server resolves the immutable original anchor. Then run the
unchanged evidence, uniqueness,1500-character/30%, overlap and issue-ID guards.
Reject missing/reversed/forged references and any conflicting model anchor.
No direct manuscript edits, acceptance bypass or extra generation attempt.

- [x] RED:1 failed/13 passed on the prior version for a valid ID-selected edit.
- [x] GREEN/full1214 backend tests in108.33 seconds; Ruff/mypy and13 offline
  cases/provider0. Source5b5ea0af,654 files, is qualified.
- [x] Deploy/preserve and normal same-book retry in the existing hold.
- [ ] Actual independent review/archive and full80 acceptance.

## Current Verified Boundary (2026-10-02T11:42:38Z)

Live source `5b5ea0af7f97c524da9405d94bb25d4482454d9f4978915d4798bbde13833ea6`;
backend `sha256:d84a517173235b2163555ca47b7e34a68b73f8b16973ac696e15b30bb36b22ae`;
frontend `sha256:c4adee56c42461e440eeef938dc66e3b524a47231e8772a166a9f652606da1ac`.
1214 current full tests, Ruff/mypy and13 offline cases passed; public ready200.
All fresh release data/environment baselines preserved before normal retry.
Rollback pinsc32f0593 images; no DB restore/downgrade or policy removal.

Normal run `dda5972c-6989-4af9-9151-3c857b59dc7a` reused the exact local hold.
The model-generated paragraph patch changed only two instances of front-side
to back-side, leaving every other character and the3828-character length
unchanged. Current SHA-256
`085a7e46758d34b48e6172770641b024a0c251a4d36bb559619223b3372c9e10`.
New complete v5 fact receipt passes; one ordinary extraction recheck consumed
the third historical extraction allowance (2 to3), not a reset. Revision
attempts6 comprise5 actual prose repairs and1 proved fact confirmation.
All calls reused roundf330b485, size15, now remaining6.

Fresh main review event15816 on this exact body has score0.922857 and no
remaining editorial must-fix finding. It fails original goalch1:must:1:
the reviewer requires the specified Jiangcheng water archive institution
to be established in the prose. That institution's full literal name is
absent; prior reviews passed this event, so inconsistent review strictness
is also a residual risk. Do not reinterpret the failure as passed.
The original effective5 actual prose-repair maximum is now exhausted;
event15818 stops before any further repair or archive. Still0/80 archived.

Actual model spend93 (preparation35/review1/chapter57), total3280 unchanged,
book remaining3187, chapter hard remaining7, current held remainder6.
All93 request rows have provider token receipts; missing usage0.
Tenant monthly23/102, remaining79; original31 chapter rows, tenant flags
and other marked book budgets unchanged. Active writing leases0.
No further retry/grant, extra quality attempt or acceptance was issued.

Proposed next control, NOT authorized/applied: one additional goal-directed
repair for this book's first chapter only; a15-call bounded local cycle would
need that chapter's temporary safety ceiling72 (57+15), while preserving the
3280 total and every historical counter. It must be a scoped audited control,
not a global setting change, and must retain fresh independent acceptance.
The current budget optimization is qualified/deployed, but full production
and80-chapter acceptance are BLOCKED, not complete.

Final private evidence: `long-r3-elastic-final-verification.json`,
`long-r3-elastic-final-checkpoint.json`, `long-r3-elastic-final-requests.json`,
and `long-r3-elastic-local-span-final-events.json`.

## Approved First-Chapter Goal Repair (2026-10-02)

The user's latest "yes" authorizes exactly the previously proposed control:
one additional goal-directed prose repair for long-r3 chapter1, hard72,
whole-book3280 unchanged. This supersedes the NOT authorized status above.
It does not authorize another book, reset, global loop increase, fact allowance,
or bypass of independent acceptance.

- [x] RED:18 failed/1 passed on the missing owner endpoint/replay.
- [x] Targeted68 tests, Ruff and mypy pass in Tencent isolated QA.
- [x] Persisted review replay binds exact body/contract/failed must-event,
  performs no paid re-review before repair and never changes acceptance to pass.
- [x] Scope is owner-only, locked/CAS, idempotent and cannot stack; the original
  five prose repairs and fact counters remain intact. Normal revision history
  records the one-use authorization; fresh independent review remains mandatory.
- [x] Pin current live5b5ea0af images as rollback; capture fresh DB/environment
  baseline with0 active leases.
- [x] Full current-source qualification and deployment:1234 tests in110.64s,
  Ruff/mypy and13 offline cases/provider0. Source6a42690c (657files), backend
  413bbb1c/frontend94cfe6fc; public ready200. All pre-authorization business
  data/environment baselines preserved; research images unchanged.
- [ ] Normal owner authorization/retry and real independent first-chapter archive.
- [ ] Continue and verify the original80-chapter novel; production readiness
  remains UNVERIFIED until end-to-end evidence is obtained.

The owner API authorized controlbd885baf with idempotent replay, sessionv4,
total3280/counters35+1+57 unchanged; old hold remaining6 was not refilled.
Read-only actual-checkpoint preflight routed to revision_node with provider0,
quality requested6/completed5 and original fact attempts2/3.
Normal runc0295a42 started; new local holdc2a26a74, size15, source085a7e46.
The model-generated patch changed only the goal paragraph,3845characters,
SHAad10736942bb2a6ed8bb6f14e695a6d3f99956dcd86398cfbc3cb3cbfc8ca516:
it establishes the institution and1990s water-fee books explicitly.
Revision history attempt7 records this exact one-use control; no manual prose
or checkpoint write. New complete v5 fact receipt passes onad107369.
Independent editorial/main review and first archive remain pending; still0/80.
Private evidence prefix:`long-r3-scoped-goal-`.

## Fresh Final Boundary (2026-10-02T12:14:09Z)

Run c0295a42 is STOPPED,0/80 archived, next reflection_node. The authorized
goal patch succeeds: independent quality event15835 on exactad107369 has
goal statuspassed and score0.922857. Fresh complete v5 fact receipt passes.
However, its editorial receipt identifies a real paired action contradiction:
p29 dons both gloves then removes only the right glove; p50 dons both again,
without any intervening removal of the left. Both original quotations exist
unchanged in085a7e46 andad107369. The prior same-prompt editorial receipt
declared81-paragraph coverage but missed this contradiction. Coverage labels
and valid citations do not prove exhaustive semantic action-state review.
Do not suppress/downgrade the new grounded finding or reuse the old pass.

The one additional goal-directed repair is spent; revision history7 means
six actual prose repairs plus one proven same-body fact confirmation.
Recovery semantic2/extraction3/quality6 and baseline0 remain intact.
Event15837 stops on the normal repair bound before any extra repair/archive.
No further retry/grant/reset or manual manuscript/checkpoint write was made.
First chapter63/72, active local hold15/remaining9, preparation35/review1;
book99/3280, remaining3181. All99 requests have finished token receipts,
missing usage0. Monthly23/102 unchanged; original31 chapter rows, tenant flags
and other marked book budgets unchanged. Public ready200, active leases0.

The approved bounded control and its real goal repair are verified/deployed;
production readiness and full80 verification are NOT complete. A subsequent
control must be separately scoped/approved. Root issue to address is semantic
action-state coverage and repair-progress budgeting, not blind review repeats
or continued cap increases. Final private evidence:
`long-r3-scoped-goal-final-verification.json`,
`long-r3-scoped-goal-final-checkpoint.json`,
`long-r3-scoped-goal-final-requests.json`,
`long-r3-scoped-goal-final-events.json`.

## Approved Progress Mechanism (2026-10-02T13:35:27Z)

User approved the proposed improvement with "改进一下". Continue the same
long-r3/accepted planv1/80 slots/336000 characters, without another book,
physical budget increase, recovery reset or direct manuscript/checkpoint edit.
Implementation stays inline; no subagents or commits.

- [x] Reproduce missing action checks, progress authorization and nine-call
  physical-boundary behavior:26 expected failing tests in Tencent isolation.
- [x] Implement editorial v3 action-state checklist and owner-only
  progress_v1 policy, old-review replay, bounded local cycles and existing
  review-pool postprocessing.
- [x] Fix full-regression compatibility: unapproved legacy flows must not
  compute new-policy capacity; body-bound failed-review replay does not
  require a new12-call observation hold.
- [x] Qualify exact sourceba7879d87d3f5836e77b0a4c908eca58b00be0067f85b1c84f25c2f777518f41:
  1264 backend tests, Ruff, mypy60 sources,13 offline cases/provider0.
- [x] Pin live6a42690c immutable rollback images, capture fresh baselines,
  deploy exact qualified source, verify data/environment unchanged,
  research images preserved and public ready200.
- [x] Actual-checkpoint preflight: provider0, bodyad107369 unchanged,
  only editorial_action_state repair, requested7/completed6 with historical
  fact semantic2/extraction3 retained.
- [x] Normal owner activation, sessionv5, idempotent response replay;
  all limits and counters unchanged (book99, chapter63).
- [x] Normal run8148dc15 produces a one-line model patch:
  "她把褪下的右手手套戴回去". Exact3846-character body
  SHAda3f317741f4108f5aaee16192d00503ce8bf32b833537dd615b68d1fd38f653,
  revision history8, no full rewrite or manual prose edit.
- [ ] Fresh v3 editorial/main/goal acceptance and independent first archive.
- [ ] Complete the original80 chapters and full production acceptance.

At this checkpoint the run is still active in reflection_node and0/80
archived, chapter66/72. Do not claim production-ready or book acceptance
from test/deployment success. Private evidence prefix:
`long-r3-progress-` (RED, qualification, baselines, activation, preflight,
normal-run watch, exact manuscript diff and checkpoint).

## Real Review Failure And Qualified Follow-Up (2026-10-02T14:09:50Z)

Run8148dc15 stopped before archive at reflection_review_node,0/80,
chapter71/72/book107. All six observation attempts were charged; invalid
predecessor links were rejected, not accepted. The first request used71068
total tokens including57159 reasoning tokens. Existing whole-review
recovery reached2 without being reset. Bodyda3f3177 is unchanged.

The follow-up adds precise rejected/expected action-link diagnostics,
stable-name/aN prompt instructions and an immediate pause after two invalid
reports for opted-in books. Independent editorial/main reflection calls
now use the existing review660 pool. Historical71 chapter calls stay there;
generation/revision/fact checks still use chapter budgets. No physical cap,
tenant/monthly budget or whole-book3280 is increased.

- [x] Reproduce missing diagnostics, ineffective whole-review pause,
  chapter-ceiling interference with independent review, unclosed review hold
  and legacy exhausted proposal recovery with failing isolated tests.
- [x] Qualify exact source61cfc56aadcee44278f2e2ac5c2feea22ab593a5a0eb59ed9b2ea4584deb114f:
  1274 backend tests, Ruff, mypy60 sources,13 offline cases/provider0.
- [x] Fresh actual-checkpoint preflight restores only trusted author config;
  provider0/body unchanged, fact2/3/quality7/review retry2/baseline0 preserved.
  One body/protocol-template migration key4ae983d8 is appended, not reset.
  Review capacity659; original total3280 and first chapter72 unchanged.
- [x] Pin liveba7879d8 immutable rollback, capture fresh data/environment
  baselines, deploy61cfc56a; compare every baseline unchanged, ready200.
- [x] Normal retry run50f62609 starts, routes legacy unavailable proposal
  once into new-protocol review. Actual new request is in review pool:
  review2/chapter71/preparation35, same manuscript. No SQL/checkpoint write.
- [ ] Fresh v3 editorial/main/goal acceptance and first independent archive.
- [ ] Original80 chapters/336000 characters and full production acceptance.

Latest qualified images: backend8ca63636/frontend614bf9e8; research images
and environment hashes unchanged. Detailed private evidence prefix:
`long-r3-progress-final-`. Full80 production readiness remains UNVERIFIED.

## First Archive Verified (2026-10-02T14:27:03Z)

Fresh quality event15871 on exact bodyda3f3177 passes original goals and
scores0.9142857142857141, with no unresolved must-fix issue. Complete
editorial v3 covers81 paragraphs and41 action checks with no findings.
Run50f62609 then stopped at persist_node because independent archive fact
revalidation still charged the chapter pool, exhausting72. No archive
or skipped fact check occurred at that boundary.

The narrow routing correction assigns persist_node's independent fact
acceptance calls to the existing review pool for progress_v1 only.
Generation/revision and their fact checks retain chapter accounting.
Reproduced one expected failure, then qualified exact source
0f12290d242ed3cb6a3a66cd6ed2148f1cd944b56d5cbb83abcd77037439dc31
with1275 backend tests, Ruff/mypy60 sources and13 offline cases/provider0.
Fresh immutable rollback and full unchanged-data/environment verification
preceded deployment; readiness200. Backend3fa29848/frontend0171ed8d.

- [x] Normal retry run132cef66 resumes archive without changing manuscript,
  goals, limits, old counts or any checkpoint manually.
- [x] First chapter actually archives, review_statuspassed,3846 characters,
  exact SHAda3f317741f4108f5aaee16192d00503ce8bf32b833537dd615b68d1fd38f653.
  Saved editorial v3 and complete passed v5 fact receipt bind the same body.
  All8 revision-history entries are retained.
- [x] Chapter postprocessing completes in the review pool, chapter1 stays72.
  Review hold closes with4 unspent requests; none of the old spend is refunded.
- [x] Original31 chapter rows remain identical; now32 rows including this
  first new chapter. Tenant flags and other creative sessions are unchanged.
- [x] Continue the same original80-chapter book: second chapter generation
  is active, review9/chapter1=72/chapter2=4/preparation35 at14:25:27Z.
- [ ] Complete80 chapters/336000 characters, ending, full quality, exports
  and tenant-isolation acceptance.

This is verified first-chapter/mechanism acceptance, not full production
readiness. No smaller/new book or forced acceptance substituted for long-r3.
Private evidence: `long-r3-progress-first-archive*.json`,
`long-r3-progress-archive-*`, `long-r3-progress-book-watch.jsonl`.

## Full-Source Action Evidence (2026-10-02T15:26:29Z)

Chapter2's normal local repair corrected two grounded errors (same-day
"yesterday" and the three-character label counted as four). Current3606
character draft411492d4 retains its one revision/progress proof. A real
editorial report then paired p4/p23 glove states, but the server wrongly
required p4's single primary-object action check to be labelled gloves.
Descriptive initial states without an action cue suffered the same defect.
Run6fbd88fc paused after two invalid reports; no forced pass or archive.

- [x] Isolated tests reproduce both false rejections; duplicate/current
  paragraph evidence remains rejected.
- [x] Validate pair chronology against the full source paragraph catalog,
  not selected primary-object labels. Preserve real-quote validation,
  ordered exhaustive checks, same-object predecessor links and must-fix gates.
- [x] Qualify exact source49b3b383b9bfa9299534a9ae91443b95d409d006e3316395fcb1260286e484ae:
  1279 tests, Ruff, mypy60 sources,13 offline cases/provider0.
- [x] Pin d6c32dda immutable rollback; deploy with all32 chapter rows,
  checkpoints, counters, tenant flags, other sessions and environments
  unchanged. Ready200; backend4d20bd8e/frontend812706a6.
- [x] Normal retry982a935f resumes the same second chapter. At15:26:29Z:
  preparation35, review19, chapter1=72, chapter2=12; archive1/80.
- [ ] Verify fresh chapter2 review, any required repair and actual archive.
- [ ] Original80 chapters/336000 characters and full production acceptance.

No cap increase, refund, closed-hold refill, manual prose/SQL/checkpoint
mutation or alternative book. Private evidence prefix:
`long-r3-progress-full-source-pair-`. This is deployed mechanism
verification; full-book and human-quality acceptance remain UNVERIFIED.

Actual fresh checkpoint evidence after deployment confirms a valid complete
v3 receipt on the unchanged411492d4 body:101 paragraphs,34 action checks.
The p4/p23 glove pair is now accepted as action_state/must_fix, not suppressed
or converted into pass. Main review and subsequent repair are still pending.
Private receipt: `long-r3-progress-full-source-pair-live-checkpoint.json`.

## Source Identity And Controlled Correction

Normal second repair changed only p23's repeated wearing into explicitly
retaining the gloves, bodyfd4bb4d2/3616 characters/history2. Fresh full
editorial receipt was valid but falsely equated comparison-volume sheets
with the morning worksheet's original sheets. Equal numbers do not prove
equal physical objects. Its folding inference also assumed a fresh sheet
without initial creases. These are semantic review risks, not JSON failures.

A normal owner cancellation stopped run982a935f. The third normal revision
had already completed before cancellation: bodyf3ad0535/3888/history3,
chapter2=16/review28/preparation35/chapter1=72,151 physical requests.
The original worksheet's differing paper sounds remain; no manual prose,
history, fact or checkpoint rollback was used.150 completed requests have
token receipts; one interrupted request is terminal usage-unknown and
remains counted. Actual archive1/80; active leases0.

- [x] Add explicit same-object/source/time and known-initial-state review
  criteria; preserve definite continuous-scene contradiction requirements.
- [x] Format correction includes the rejected report as untrusted data,
  with a bounded, explicitly truncated preview above30000 characters.
  Two component attempts and real validation remain mandatory.
- [x] Reproduce four failures, then qualify exact source
  fefb978d4bdfeaf1a14bf4a900e46c5ba4ede6a6ff980ed33320e66c6d13ca7c:
  1283 tests, Ruff, mypy60 sources,13 offline cases/provider0.
- [x] Capture current paused baseline and pin49b3b383 immutable rollback.
- [x] Deploy and verify exact data/environment preservation, readiness200
  at2026-10-02T15:56:27Z; backend6f87d7a0/frontend97e35f08.
- [x] Normal retry74e9ef0b resumes the unchanged3888-character second chapter.
  At15:57:41Z preparation35/review29/chapter1=72/chapter2=16, archive1/80.
- [x] Fresh real review and actual second archive, including normal facts
  and postprocessing; content-quality residual risks are recorded below.
- [ ] Complete the original80-book production acceptance.

Prompt contract tests verify the instructions and bounded correction
mechanism, not the model's semantic accuracy. New real review is required;
no false-positive issue is manually waived or manuscript forced to pass.
Private evidence: `long-r3-progress-source-identity-*` and
`long-r3-progress-full-source-pair-source-identity-cancel.json`.

## Second Archive Verified (2026-10-02T16:14:05Z)

Normal run74e9ef0b archives chapter2,3888 characters, exact SHA
f3ad05357694a45e85aa1ffdf6eae26b80d480dc805cff4f9d493186125ccd59.
API bytes equal DB bytes, review_statuspassed/quality0.8942857142857144.
Fresh goal event21555 passes on that same hash and original c3603159
contract; this is chapter acceptance, not proof of full-book word count.
Complete editorial v3 covers104 paragraphs/39 actions/findings[].
Complete passed fact-v5 gate binds the same body/context snapshot.
All3 revision-history entries remain. Postprocessing completes normally.

Every predeployment32 chapter row stays unchanged; now33 including chapter2.
Tenant flags and other books' sessions stay unchanged. Same original80-book
has2 archives/7734 characters; third chapter enters reflection_node.
At16:14:05Z preparation35/review38/chapter1=72/chapter2=16/chapter3=9.
No physical cap, monthly quota, search allocation or old spend is reset.

Residual semantic risks remain: main review classified a four-versus-three
identifier-count statement and an ambiguous "two volumes" referent as
optional. They are recorded, not a clean-content certification. The count
statement especially requires full-book content review; passing automated
labels and a normal archive do not prove no prose error. Human review has
not been performed. Original80 chapters, ending, aggregate word range,
exports and final quality acceptance remain UNVERIFIED.

Private receipts: `long-r3-progress-second-archive-audit.json`,
`long-r3-progress-second-archive-verification.json`,
`long-r3-progress-source-identity-current-status.json`,
`long-r3-progress-source-identity-watch.jsonl`.
