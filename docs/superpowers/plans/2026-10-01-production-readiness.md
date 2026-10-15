# Production Readiness Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Do not delegate
> or discard the existing working-tree changes. Steps use checkboxes for tracking.

**Goal:** Qualify and deploy the existing application on the Tencent host, then
produce and inspect an 80-chapter book targeting 336,000 characters.

**Architecture:** Retain FastAPI, LangGraph checkpoints, PostgreSQL fencing and
the current React application. Persist automatic-run recovery intent separately
from accepted manuscript artifacts; restore authorized execution from checkpoints
after restart, never by rewriting production checkpoints. Add authenticated
manuscript download through the existing tenant-scoped repository.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16,
LangGraph, React, TypeScript, Ant Design, Vitest, Docker Compose.

**Spec:** `docs/production-readiness-20261001.md`, including AC-1 through AC-6
and the user's confirmed 80-chapter acceptance scale.

## Global Constraints

- Deploy only to `/opt/novel-writer` on `124.220.67.163`.
- Preserve existing books, credentials, production database, Compose overrides
  and unrelated services. No migration downgrade or broad Docker cleanup.
- PostgreSQL tests must use `novel_writer_test`, never the production database.
- Final acceptance: 80 chapters, target 336,000 characters, existing tolerance.
- Preserve fact, goal, quality, budget, cancellation and quota guards.
- Model evaluation is not human reader validation.
- A failed run or a smoke-test book is not the completed long-form deliverable.

## Task 1: Qualify Prompt Resources and Type Checking

Files: `application/review_evidence.py`, prompt resources under
`application/prompts/templates/reflection`, `application/agents/chapter_outline_node.py`.

- [x] Reproduce `test_long_strings_live_only_in_prompt_templates` and `mypy`.
- [x] Move the unchanged citation-repair instruction into a snapshot-bound
  resource with `$requirements`, `$invalid` and `$content` variables.
- [x] Annotate nullable creative-plan context as `dict[str, Any] | None`, and
  accept that type at `_attach_plan_contract`; keep its empty-context behavior.
- [x] Run static-quality, review-evidence, outline, prompt and goal regressions.

## Task 2: Complete Authenticated Manuscript Download

Files: `writter_front/src/api/novel.ts`,
`writter_front/src/pages/novel-studio/NovelStudioView.tsx`,
existing `novel.test.ts` and `NovelStudioView.test.tsx`.

- [x] Observe the existing missing-client and missing-button tests failing.
- [x] Add `exportManuscriptBlob(novelId: string, format: 'txt' | 'md'): Promise<Blob>`
  using `apiClient.get` with `responseType: 'blob'`.
- [x] Add a download-icon menu for TXT/Markdown; disable it without archived
  chapters, show request state, report failure and revoke object URLs.
- [x] Add tests for actual download behavior and failure recovery.
- [x] Run targeted tests, lint, full tests and the production build on the server.

## Task 3: Diagnose Fact-Ledger Timeout

Files: `FactLedger.test.tsx`, `FactLedger.tsx`, test utilities if warranted.

- [x] Run the existing test alone under the same server resource limits.
- [x] Inspect where confirmation stops: form validation, preview request,
  modal rendering or final confirmation.
- [x] Fix only the observed cause; do not blanket-increase test timeouts.
- [x] Verify no write happens before confirmation and repeat the full suite.

## Task 4: Persist Safe Automatic Recovery

Files: `infrastructure/database/runtime_models.py`,
`infrastructure/command_store/postgres_command_store.py`,
new `infrastructure/command_store/recovery.py`,
new Alembic revision `0010_workflow_recovery`, `tests/test_restart_recovery.py`.

Interfaces:
- `set_recovery(lease_token: str, intent: dict) -> bool`
- `release_for_restart(tenant: str, novel: str, command: str, token: str) -> bool`
- `recovery_candidates() -> list[dict]`
- `clear_recovery(run_id: UUID) -> None`
- `claim(..., expected_run_id: UUID | None = None)` fences takeover against a
  newer user command.

- [x] Upload and run existing restart tests; confirm missing behavior fails.
- [x] Add a nullable JSONB recovery-intent column with an additive migration.
- [x] Persist intent only for a live, non-cancelled owner; query only the latest
  orphaned run with unexpired recovery intent and no live lease.
- [x] Keep user cancellation terminal and reject stale takeover.
- [x] Run real PostgreSQL cancellation, fencing, recovery and runtime tests.

## Task 5: Connect Process Shutdown and Startup Recovery

Files: `api/main.py`, `api/routers/workflow_router.py`,
new `application/automatic_restart.py`, lifecycle integration tests.

- [x] Add tests proving shutdown preserves automatic intent, startup schedules
  saved intent once, cancelled tasks never restart, and retries reuse quota IDs.
- [x] Persist server-derived user identity and bounded deadline before starting
  automatic work; never persist tokens or provider credentials.
- [x] On startup reload current authorization, acquire the expected latest-run
  fence and retry/resume the saved checkpoint without accepting human-only gates.
- [x] On shutdown cancel and await producers, preserving restart intent only
  when shutdown initiated cancellation. User cancellation clears intent.
- [x] Run an actual isolated backend restart and verify resumed checkpoint/events.

## Task 6: Qualify Release and Backup

Files: controlled server-release script and delivery evidence.

- [x] Package current source and lockfiles, excluding secrets and dependencies.
- [x] Run locked backend/research/frontend regression checks on isolated server QA.
- [x] Capture image identities and the union of backend/frontend Compose chains.
- [x] Back up production PostgreSQL; restore the dump into an isolated database.
- [x] Build qualified application images from verified dependency locks.
- [x] Recheck active leases and update only backend/frontend with rollback on
  failed health checks; do not downgrade the additive database migration.

## Task 7: Real End-to-End Acceptance

Files: bounded server acceptance runner, evidence and downloaded manuscript.

- [x] Create marked QA identities and books through authenticated APIs.
- [ ] Verify tenant isolation, stale writes, export and browser workflows.
- [x] Verify three sequential archives/postprocessing of the original full-size
  sample: 12,254 characters, 71 exact proofs and unchanged authenticated exports.
  This technical milestone does NOT pass literary acceptance; retain all samples
  and physical counters without resets.
- [ ] Run the confirmed 80-chapter/336,000-character contract without disabling
  guards or manually accepting rejected artifacts.
- [ ] Inspect contiguous archived chapters, exact stored/actual counts,
  review status, clean prose, causal progression, character continuity,
  foreshadowing payoffs and a closed ending.
- [ ] Record failures, repair causes with regression tests, deploy affected fixes
  and rerun invalidated acceptance. Keep unknowns separate from passed checks.

### Observed Release Defects

- [x] Register creative controls as an explicit router; reproduce the real
  `/creative-options` 500/405 and verify authenticated PostgreSQL API behavior.
- [x] Expose runtime configuration in measured LangGraph node signatures while
  preserving `Command` metadata; verify with an actual compiled graph.
- [x] Keep author title/summary in candidate input and distinguish book scale
  from model-request budgets; keep exact evidence and pilot length gates intact.
- [x] Add model/length/evidence rejection diagnostics and regression tests.
- [x] Name autonomous stages in the user-facing workflow; verify real browser
  login, desktop/mobile presentation and reload after deployment.
- [x] Test graceful shutdown and hard process crash against real PostgreSQL.
- [x] Verify cancellation stops requests and preserves artifacts on the production
  R2 test book, then resume through explicit authenticated retry.
- [x] Reproduce ambiguous JSON-outline quotes and add exact-leaf evidence
  localization; preserve full-artifact binding and fail-closed fact checks.
- [x] Reproduce the crash window between durable task writes and the next
  snapshot; repair restart admission without resetting budgets or initialization.
- [x] Qualify the combined candidate (812 backend tests, 13 harness cases)
  and deploy after active-lease checks; repeat production browser verification.
- [x] Diagnose the real-provider extraction protocol; qualify v4 grounded
  mentions and verify an actual body receipt without inventing canonical facts.
- [x] Recover original goal sources only from matching saved author truth;
  qualify 844 backend tests and deploy the repair.
- [x] Qualify provisional-name binding before goal compilation, including
  relationship prose and source/user-name protection.
- [x] Produce a fresh bounded R3 sample after R2 exhausted its unchanged cap;
  retain failed goals, manuscript and physical counters. R3's first chapter
  is archived, not a passed whole-book smoke test.
- [x] Qualify future-role boundary validation, outline evidence locator hints
  and evidence-only goal recovery on the real provider path.
- [x] Reproduce wrong postprocess offsets with five actual literal quotes;
  resolve unique quotes without weakening archived version/hash validation.
- [x] Preserve raw reader responses across validation/storage failures and
  reconcile new-design address metadata before character confirmation.
- [x] Qualify 884 backend tests, 13 offline harness cases and static checks,
  deploy healthy and replay the actual failed response without state mutation.
- [x] Create/start the actual 80-chapter book through normal APIs; verify
  it runs on the server after its stream reader disconnects.
- [x] Reproduce JSON-mode request failure, preserve prompt snapshots and resume
  the same book; verify real eight-character address alignment and accepted plan.
- [x] Project engine provisional names through admitted IDs for initialization
  and recap; preserve original history, source quotes and opaque identity fields.
- [x] Reproduce ambiguous postprocess quotes and invalid foreshadow enum;
  supply paragraph references/status values and bounded metadata-only repair.
- [x] Reject unknown foreshadow characters and preserve hard lifecycle guards;
  qualify all 902 backend tests, 13 harness cases and static checks, then deploy.
- [x] Verify first long-form chapter archive/export/postprocess with ten exact
  proofs, 19/32 physical requests and automatic continuation into chapter two.
- [x] Reproduce partial fact-report routing failure, revise actual draft under
  unchanged gates, qualify 905 tests and obtain a real outline fact pass.
- [x] Reproduce tactical commit/checkpoint version conflict, qualify exact latest
  recovery and stale/replan rejection with 908 tests, then deploy.
- [x] Read second/third actual prose, record literary failure, reproduce count
  errors and add conservative server checks plus action/tool/time copyediting.
- [x] Preserve quality revision baseline on fact retry and bind current facts
  to tactical generation; keep original physical request caps.
- [x] Reject known copyediting failures in final acceptance regardless of model
  scores; qualify all 924 tests, static checks and 13 offline cases, then deploy.
- [x] Create/start a new complete 80-chapter/336,000-character rerun (`long-r2`)
  after relevant pre-archive fixes; retain the original failed long-form sample.
- [x] Verify owned QA cache scope and idle processes before recovering disk
  space; delete only generated `.pyc` caches, not production data or images.
- [x] Run the real, metered retrospective chapter-two review: valid evidence
  detects glove state, units and literal count failures without changing prose.
- [x] Verify the new complete rerun's loaded desktop/mobile browser workflow;
  mark export unavailable before archival rather than reusing an older download.
- [x] Inspect the complete accepted rerun plan and preserve its actual
  seven-day-appraisal/deadline conflict through normal QA-only cancellation.
- [x] Add complete-input-bound whole-plan semantic review with exact JSON
  Pointer quotes, one durable repair and independently reviewed regeneration.
  Correct the invalid test fixture; 14 regressions / 64 affected tests pass.
- [x] Close the reviewed autonomous minor-drift acceptance bypass with a durable
  review proposal and correct review-budget classification; reproduce two reds,
  verify benign/rejected drift paths and obtain a no-remaining-findings rereview.
- [x] Qualify all 944 backend tests, 74 affected tests, static checks and
  13 offline cases; bind exact source/images/evidence and deploy healthy.
- [x] Qualify the combined whole-plan candidate, deploy with no active leases,
  then submit consistency replanning for the same QA book through the ordinary
  versioned API, without resetting its counters or editing its manuscript.
- [x] Preserve the real model's two semantic failures and malformed evidence
  pointer; reproduce strict unique-whole-leaf localization and malformed-pointer
  rejection, retaining original and derived reports separately.
- [x] Supply durable historical execution receipts to complete-plan review;
  reproduce receipt-sensitive cache invalidation and preserve future prerequisites.
- [x] Qualify all 956 backend tests, 101 affected tests, static checks and 13
  offline cases; replay the actual paused report without model calls or mutations,
  retaining both semantic failures.
- [x] Deploy the exact qualified source healthy, verify running image labels,
  then resume the same book's bounded automatic repair through authenticated retry.
- [x] Retain the actual independently reviewed second candidate's four supported
  semantic failures; verify its normal repair-limit pause without acceptance.
- [x] Reproduce omitted admitted intent/full blueprint in planning generation;
  append current-name-projected brief/engine and full cross-volume context, preserving
  original sources, locked content and manual legacy behavior.
- [x] Reproduce explicit versioned replan reusing the old rejected proposal through
  request preparation and the real initialization node; clear only transient batch
  state after accepted-version validation, preserving draft/plan/counters/history.
- [x] Qualify all 963 tests, 63 affected/maintenance cases, static checks and 13
  offline cases; preserve failed maintenance/type-check candidates, deploy the
  final generation/source and replan-boundary corrections healthy, then submit a
  normal versioned request for the same book without resetting repair allowance.
- [x] Preserve the real complete review's three literal duplicate-event failures;
  trace missing history to the four-slot context limit and reproduce the omission.
- [x] Supply all earlier planned critical events and state changes to each later
  volume, exclude future retained slots and preserve planning/fact distinction;
  qualify 964 full tests, 60 affected tests, static checks and 13 offline cases.
- [x] Deploy the history correction with zero active leases and preserved services;
  verify fresh public HTTPS login, loaded desktop/mobile views and reload, then
  submit the same book's normal versioned replan with counters and draft retained.
- [x] Verify real complete-plan model review and contract audit pass after the
  evidence-bound correction; confirm the repository accepts version two.
- [ ] Finish the actual 80-chapter book and verify its export and content.

### Evidence-Bound Milestone Correction

The real history-bound reruns passed timeline, resource and ending checks but
full regeneration introduced another isolated arc/slot chapter mismatch.
Add an opt-in `repair_proposal_id` to the existing future-replan command.
Read the named current proposal from the authenticated tenant's checkpoint, not
client JSON. Only a complete, literally valid, exact-context-bound cross-layer
report may authorize corrections to its cited arc escalation text/chapter.
All slots, scale, volume boundaries and ending remain byte-for-byte unchanged.
One cached model patch is generated per source proposal and instruction; failed
patches remain visible. The revised proposal still runs complete-plan review,
locked-transition validation, author-policy checks and replan-contract audit.
This does not reset the existing automatic-repair allowance or any counters.

- [x] Reproduce missing API intent and node-level differential correction.
- [x] Implement the trusted checkpoint loader and bounded cached milestone patch.
- [x] Reject stale context, uncited edits, invalid chapters and custom input.
- [x] Obtain readonly review; qualify 986 full tests, static checks and offline cases.
- [x] Deploy the milestone correction and submit the named-proposal command;
  retain the real entry-chain failure without resetting counters or artifacts.
- [x] Reproduce character reuse clearing another stage's proposal; preserve
  unrelated proposals and recover only exact same-run checkpoint metadata.
- [x] Reproduce recovery routing overwritten after error tasks are cleared;
  qualify the final early-return correction with 997 full tests, 53 affected
  tests, static checks and 13 offline cases; obtain no-blocking readonly rereview.
- [x] Deploy healthy, verify fresh public browser login/layout/reload and all
  26 original chapters unchanged, then resume through normal authenticated retry.
- [x] Independently verify the actual patch changes only chapter 35 to 36 and
  all four full-plan consistency criteria pass for the new proposal.
- [x] Deploy at zero active leases and repair the actual current proposal through
  the ordinary versioned API; verify full review, contract audit and acceptance.
- [x] Retain the cast-coverage pause; run one normally metered exact-input
  diagnostic, verify all eight characters/seven slots pass the unchanged gate,
  and resume with standard authenticated retry without resetting counters.
- [ ] Verify subsequent manuscript generation, full-book archival and export.
- [x] Bind the new chapter's goal source to accepted version two and inspect the
  actual 3,852-character prose/quality rejection; preserve the failed revision
  and unchanged physical 32-request cap, with zero archived chapters.
- [x] Trace swallowed budget pauses in fact extraction; reproduce four focused
  and one actual PostgreSQL/LangGraph failure, propagate trusted control pauses,
  and qualify 1,002 full tests, 74 affected tests, static checks and 13 offline cases.
- [x] Deploy the control-pause correction and verify the production counter
  boundary without changing the exhausted book's manuscript or allowances.
- [x] Validate focused body-only editorial review against retained real failures;
  never treat a retrospective diagnostic as an archived chapter or whole-book pass.
- [x] Retain the failed focused-editor probe: it still omitted the action-state
  error and classified the physical-unit error as optional; do not add an
  unqualified extra production model stage.
- [x] Reproduce the capped checkpoint's misleading reload/continue display;
  derive a scoped read-only server blocker and remove blind retry from the UI.
- [x] Reproduce a new execution starting during the budget lookup; refresh
  execution state and clear the obsolete failure blocker without changing quota.
- [x] Reproduce and preserve stale-running inactivity detection during rereview;
  fix the shared frontend action spy without weakening the no-start assertion.
- [x] Qualify 1,008 backend tests, static checks and 13 offline cases; retain the
  frontend full-run timeout, verify the failed file independently and qualify
  all 180 frontend tests with bounded sequential workers and unchanged timeouts.
- [x] Reproduce contradictory retained-draft retry advice for nonretryable errors;
  correct the message, retain normal retry behavior and existing static limits,
  obtain readonly review and verify source-manifest evidence reuse.
- [x] Qualify/deploy the combined budget-presentation correction and verify
  the real failed book's public API and desktop/mobile reload state.
- [x] Qualify all 182 frontend tests and build, pin the previous qualified image
  IDs for rollback, verify the actual checkpoint/draft/counters unchanged,
  all 26 original chapters intact and all four original flags unchanged.
- [x] Recover disk space by verifying idle QA processes and deleting only
  scoped generated .pyc caches; retain production data, images and evidence.
- [x] Agree the next architectural editorial change after the failed overall
  and focused-review probes; do not retry indefinitely or bypass acceptance.
- [x] Validate separate observation/quantity evidence against the actual failed
  manuscript and corrected counterexample; reject the combined false-positive
  candidate, preserve all raw reports and count actual diagnostic requests.
- [x] Implement server-validated source catalogs, body/template/report-bound
  receipts, durable component checkpoints and autonomous archive enforcement.
- [x] Fix readonly-review findings through real graph pause/provider-failure and
  mid-request hot-template regressions; qualify 1,051 backend tests, 129 affected
  tests, mypy 60 sources, Ruff and 13 zero-provider offline cases.
- [x] Deploy source 4777fe57 at zero leases, healthy, preserve original data and
  failed-book state, and verify fresh public desktop/mobile login/reload.
- [ ] Complete the fresh smoke-r4 manuscript on the same identity and original
  budgets; inspect actual chapter evidence, revisions, ending and exports.
- [ ] Validate a complete 80-chapter book, closed ending, exports and actual
  prose quality; the current real long-r2 run remains 0/80 and failed acceptance.

## Direct Full-Book Execution (2026-10-02)

The user corrected the execution priority and explicitly said to begin:
the three-chapter smoke is no longer a prerequisite for the complete book.
Its unfinished artifacts and 48/48 pause remain preserved, not accepted or
extended. The proposed 48 to 56 exception is not authorized or applied.

The canonical current full-book acceptance is `long-r3`, novel
`9e422832-63de-5a02-ba81-476885bbe79b`, title
`生产验收20261001·潮汐账本·长篇R3`. Reuse this book for subsequent diagnosis,
repairs and normal recovery. Do not create replacement identities/books,
reset counters or bypass fact, goal, quality, quota or request-budget gates.

- [x] Verify the current Tencent release is healthy, public readiness is 200,
  all 31 existing chapter rows are unchanged and no writing lease is active.
- [x] Verify the existing QA identity has 82 monthly units remaining against
  at least 81 required for planning plus 80 chapters. Keep cap 102 unchanged.
- [x] Create through the normal authenticated public API with exactly 80
  chapters / 336,000 characters / original 10% tolerance. Its normal budget is
  preparation 60, chapter 32, review 660 and total 3,280; no operator exception.
- [x] Start the same book normally and verify server execution continues after
  reader disconnection. Run `cca6c72f-d32c-4293-bcd2-79788da7a1d4` was observed
  running at 2026-10-02T05:04:55Z (October 2, 13:04 Asia/Shanghai).
- [ ] Observe and diagnose this actual full-book workflow; qualify/deploy only
  evidence-supported fixes and resume this same book within existing guards.
- [ ] Verify all 80 contiguous archived chapters and actual 302,400 to 369,600
  characters, version-bound reviews, causal/character continuity, fulfilled
  core payoffs and closed ending.
- [ ] Verify complete unchanged authenticated TXT/Markdown exports, tenant
  isolation and public desktop/mobile behavior. Actual manuscript reading is
  required; model scores are not human readership or professional parity.

Source remains the qualified 637-file
`fc9ce36b2c7be8422600b9b38fb69ca9c897808a98223220eed99c3c3469aea6`.
Evidence: `long-r3-preflight.json`, `long-r3-start.json`,
`long-r3-status.json` and `long-r3-first-monitor.json`. Starting the run is not
completion. Overall delivery and AC-2/AC-5 remain unpassed.

### First Full-Book Failure and Scoped Recovery

At 2026-10-02T05:23Z the actual fourth-volume node stopped after its three
normal attempts, with preparation counter 23/60 and zero archived chapters.
Checkpoint `1f1be20d-170e-6a24-801a-d635306aa625` retained the first 60 slots.
Its error rejected prefixed payoff aliases without earlier matching setups
and chapter 80 references to an arc ending at chapter 76. No budget was
exhausted, no manuscript accepted and no failed raw model response persisted.

- [x] Reproduce the ID/boundary failures through the real volume node and
  validator: three expected failures and three passing rejection/provider cases.
- [x] Append a server-derived complete earlier foreshadow ledger and legal
  arc IDs by chapter using a new template resource outside the old snapshot.
  Keep opaque IDs, validation, earlier slots and budgets unchanged.
- [x] Verify 34 affected/static tests, 1,091 full backend tests, Ruff, mypy
  (60 sources) and 13 offline cases with zero provider calls.
- [x] Replay the actual retained checkpoint with its frozen templates:
  all 21 earlier IDs and 20 current chapter boundaries supplied; no mutation.
- [x] Compare frozen manifests: exactly four changed backend/test/resource
  files; frontend and research unchanged, so their qualified tests remain valid.
- [x] Pin current images before rebuilding and deploy at zero active leases.
  At 2026-10-02T05:41:45Z public readiness was 200 and both services healthy;
  all 31 existing chapters, creative records/sessions, tenant flags and all
  three retained acceptance checkpoint tables matched the pre-release baseline.
- [x] Resume this same book through normal authenticated public retry.
  Run `7c59700f-b550-4cd2-9bd4-d0ade7e382e1` is observed running from the
  fourth-volume node, preparation 24/60, still zero archived chapters.
- [ ] Observe actual provider recovery and the rest of the complete workflow.

Qualified source: 639 files,
`661501235426424a62765efd9edde4eb74d12a527bbf75b19ca02f55cbbc3f51`.
Evidence prefix: `long-r3-reference-`, including red/green/full tests,
checkpoint replay, before/after release baselines, resume and live monitor.
The generic public retry message was not sufficient diagnosis; the retained
checkpoint error supplied the concrete failure. This repair does not establish
professional prose quality or full-book completion.

### Conflicting Macro Reference Labels

The first real recovery still failed at 2026-10-02T05:47:12Z, preparation
26/60. The last error no longer contained an out-of-range arc but still rejected
13 `payoff-*` aliases. Preserve failed checkpoint
`1f1be23f-4811-6294-801b-6dd06b07b650` and the complete error; the reference
catalog alone did not solve actual provider generation.

- [x] Reproduce both competing inputs: the primary current-volume object and
  the complete-blueprint context still carried macro `setup_ids`/`payoff_ids`.
- [x] Remove only those macro reference fields from autonomous model input.
  Preserve every narrative field, all stored blueprint fields and earlier slots.
  Existing chapter IDs remain authoritative; no ID normalization or validator change.
- [x] Verify two new failing regressions, then 36 affected/static tests and
  1,093 full backend tests, Ruff, mypy and 13 zero-provider offline cases.
- [x] Replay the actual failed checkpoint with old frozen templates; assert
  all narrative blueprint fields remain and source state is unchanged.
- [x] Pin the currently live images for rollback. Deploy at zero leases and
  compare all original rows/flags and retained session/record/checkpoint digests.
  At 2026-10-02T05:56:41Z both services were healthy and public readiness 200.
- [x] Resume the same book normally as
  `9ebc4356-d91e-4336-b011-070c8b228635`, preparation 27/60, still 0/80 archived.
- [ ] Verify real provider recovery and all remaining full-book acceptance.

Current source: 639 files,
`115ee27e250e336cd49a8fa115bdbcdd45db8f4f4e64bf267485be3ef86951f5`.
Five backend/resource/test files differ from the prior qualified `fc9ce36b`
source. Frontend/research source is unchanged. Evidence prefix:
`long-r3-macro-label-`; retained first recovery failure:
`long-r3-reference-provider-failure.json`. No additional quota or operator
budget grant was applied. Smoke-r4 stays suspended at its old boundary.

### Actual Fourth-Volume Recovery and Semantic Review Pause

At 2026-10-02T05:58:05Z the real provider's fourth-volume output passed and
the workflow reached `novel_plan_review_node`. Read-only candidate validation
at 05:59:47Z proved 80 contiguous slots and exactly 336,000 planned characters.
The original first 60 raw slots, blueprint and frozen snapshot were unchanged.
This is a candidate plan, not an accepted book or 80 archived chapters.
Evidence: `long-r3-volume4-provider-recovered.json` and
`long-r3-volume4-recovery-validation.json`.

The actual complete semantic report then paused execution with
`plan_review_protocol` at 2026-10-02T06:00:42Z, preparation 28/60.
Its five issues are real planning concerns, not a passing score: conflicting
seven-day start points, a witness summary requested before creation, repeated
curve-copy acquisition, incompatible review-start chapters and a previously
admitted takeover later described as unadmitted.

The retained report's one incorrect path points to event index 1 of chapter
45, while its unchanged literal quote occurs only once in the full immutable
input, within event index 0 of the same chapter. The other nine paths are valid.
The context SHA-256 matches the saved review:
`314c12305d5e46bd5b337d4a1e5303ba4f83c568aab4863486adcc6cd40032bd`.

- [x] Retain the raw model report, full checkpoint and exact input context in
  `long-r3-plan-review-protocol-failure.json`.
- [x] Reproduce the cached-report pause through the real review node.
- [x] Reject a whole-event-only locator candidate after actual report replay:
  the quote is a literal substring, as allowed by the existing evidence contract.
  Do not deploy that ineffective candidate despite 1,100 passing unit tests.
- [x] Restrict correction to an existing same-chapter `must_happen` array,
  exactly one adjacent position and exactly one literal quote occurrence in
  the entire input. Never change already-valid proofs, verdicts, issues or quotes.
- [x] Verify 78 affected/static tests, including duplicate/global duplicate,
  repeated-in-one-event, cross-chapter, nonadjacent and malformed-index rejection.
- [x] Replay the actual report: exactly one path changes, all five issues
  and all classifications remain, raw report unchanged, zero provider calls.
- [x] Finish full regression qualification and deploy the bounded locator:
  1,103 full backend tests, Ruff, mypy and 13 zero-provider offline cases.
- [x] Resume this same book; retain the model version and append a normal
  system repair version through production code, then perform the existing
  bounded planning repair. The new candidate is not yet independently accepted.
- [ ] Independently review the repaired candidate before accepting the plan.
- [ ] Complete and inspect all 80 actual archived chapters and final exports.

Current qualified deployed source is 640 files,
`192998001ad9995b652a5f4c0d1b98575023057349a6e37bd7acd3e0a860b931`;
only the review module and its new regression file differ from `115ee27e`.
At 2026-10-02T06:22:22Z both services were healthy and public readiness 200.
The pre/post baseline proved all captured original data, counters, flags and
checkpoints unchanged. Normal retry resumes the same book as
`1376c629-2465-437e-961e-0aad251c33f4`.

At 06:24:28Z production receipts proved raw model version 1 retained, system
version 2 corrected only the path with the same context hash, all five issues
retained and a normal bounded repair requested. Preparation reached 31/60
at 06:24:54Z during fresh volume generation; archived prose is still 0/80.
Evidence prefix: `long-r3-review-index-v2-`, including full tests,
actual-report replay, release baseline comparison, resume, production receipt
and live monitor. Complete delivery and AC-2/AC-5 remain open.

### Current Remaining Planning Boundary (2026-10-02T06:31:09Z)

The same run stopped normally on `plan_consistency`, preparation 34/60,
0/80 archived, accepted plan version 0. The independently reviewed repair
resolved the original five issues: timeline, single-use and ending-causality
now pass. Two evidence-bound cross-layer failures remain:

- The father's delivery of the second carbon copy occurs in both chapters
  70 and 80 and the fourth-volume ending state, while the family arc treats
  chapter 70 as delivery and chapter 80 as sealing.
- The water-debt relabeling is performed in chapter 78 and again in chapter
  80; the antagonist arc places it at 78 but the main arc places it at 80.

Retain candidate `6aad8e5f-ad8a-41cb-bf95-8afee1a9cac9`, checkpoint
`1f1be2a8-577d-692f-8026-05541a736081` and both raw reviews.
Evidence: `long-r3-repaired-plan-candidate.json`,
`long-r3-repaired-plan-semantic-failure.json` and the final live monitor.
The ordinary one-shot full-planning repair was consumed; it was not reset.

The existing explicit milestone repair does not cover this boundary:
it requires an accepted plan version and an evidence-cited arc escalation
point in every issue. The first remaining issue instead cites chapter event
strings and a volume ending. Changing only an arc would not fix it.

Do not blind-retry the cached rejection, increase repair limits, accept the
candidate, rewrite checkpoints, edit manuscript/canon or replace this book.
The proposed next bounded extension is a named-initial-proposal cross-layer
repair: authorize only evidence-related future planning string leaves, enforce
the exact source proposal/version/context hash and before text, preserve every
identity, scale, word target, hard constraint and locked/archived artifact,
retain raw model changes and require fresh complete semantic review before
acceptance. The existing full-regeneration bound and request budgets stay
unchanged. This is a new repair path, not a claim that the book is complete.
The user explicitly approved this extension with "是" on 2026-10-02.
Execute inline in the existing task workspace; do not delegate or make commits.

### Approved Initial Cross-Layer Repair Delivery

Use `superpowers:executing-plans` with `superpowers:test-driven-development`.
The accepted design above is the specification; no renewed design approval is needed.

- [x] Add `tests/test_plan_cross_layer_repair.py` and run it in Tencent QA
  before production edits. Exercise the real initialize/review nodes and API
  seeding. An initial named candidate must become a new reviewed proposal,
  not an accepted plan. Reject uncited paths, stale identities/context,
  wrong before text, completed candidates and ordinary version-zero replans.
- [x] Add `application/creative/plan_cross_layer_repair.py` and its prompt
  resource. Derive paths from valid full-review evidence: preserve earliest
  event chapters; permit cited later event/delta leaves, same-chapter event
  siblings for cited deltas, cited volume endings and cited later arc changes.
  Only string replacement is supported; chapter numbers, IDs, budgets,
  scale, targets, ending contract and all other leaves remain unchanged.
- [x] Extend the existing named `plan_replan` command with explicit
  `repair_mode: cross_layer`, expected version zero and future scope.
  Seed only the current trusted initial checkpoint; refuse client plan JSON
  and accepted-plan conflicts before charging quota or creating a provider.
- [x] Route the repaired candidate to the existing complete initial review,
  retaining mode initial, accepted version zero, raw reports and consumed
  automatic full-regeneration allowance. Clear the repair intent only after
  generating the new candidate. A failed fresh review must still pause.
- [x] Verify affected tests, full backend regression, static constraints,
  Ruff, mypy and offline harness on the exact packaged source.
- [x] Capture fresh production preservation baselines and pin current live
  images, build/deploy only the qualified source at zero active leases,
  verify readiness and preserved data. Submit the explicit command through
  authenticated public HTTPS for candidate
  `6aad8e5f-ad8a-41cb-bf95-8afee1a9cac9`, then inspect actual patch and review
  receipts before continuing the same 80-chapter run.
- [ ] Complete the original 80-chapter manuscript, text inspection, isolation
  and exports acceptance. Test success or a planning pass does not close it.

Qualified and deployed source:
`97d10cd85eba19324d7bdaade49e3c5198b4a49ea7bf97d9b400e30f89361bb0`
(643 files; six changed/added backend files). Tencent QA: 1,141 full backend
tests, 107 affected/static tests, Ruff, mypy (60 sources) and 13 zero-provider
offline cases passed. Red evidence retained for the missing initial repair
and invalid non-string API mode. One existing upstream LangChain pending
deprecation warning remains. Frontend/research source unchanged.

The actual failed candidate/context replay derived exactly six authorized
leaves in chapter 80, volume 4 ending and main-arc ending; the first 79 slots,
scale and ending contract remain unchanged. This was a zero-provider,
zero-production-write diagnostic, not semantic acceptance.

Deployment preserved all captured 31 existing chapters, flags, sessions,
creative records, budgets and retained checkpoint tables. Public readiness 200
and both application services healthy. Current live images:
backend `sha256:3cf0d7988436d2121e300a17ab772a8145cf1e3b45dd4adbbfbea82e2729b1e3`;
frontend `sha256:9ac3ca939c94de097e58f5a9ae96b5c0b46179bb3b7267255aa50e8757986bee`.
Rollback pins the previous `19299800` live images and 45-second shutdown.

The normal authenticated public-HTTPS command references the original
candidate and starts run `987dd783-244f-4a5c-8c0a-7a02aad43e3b`.
Initial receipt: running, accepted version 0, 0/80 archived, review 1 and
preparation 34. No counter reset or budget grant. Actual patch, fresh complete
review and all manuscript acceptance criteria remain to be verified.
Evidence prefix: `long-r3-cross-layer-`.

At 2026-10-02T07:16:32Z actual production receipts proved five string leaves
changed, all first 79 slots/scale/ending contract retained, and the original
consumed automatic repair record unchanged. New proposal
`fde83839-1033-4178-8057-9d18604defe9` passed fresh complete semantic review
with all four criteria true and no issues. Normal accepted plan version is 1.
The planning repair/deployment delivery is verified, not full-book completion.

At 07:17:19Z the same run paused before prose at `creative_decision_node`:
`cast_coverage`, nine admitted characters and six role slots. Counters:
review 1, preparation 35, chapter:1 1. No cast assignment was accepted.
The existing cast code validates before saving; its failed model result was
lost, so the exact mismatch cannot yet be diagnosed without guessing.

- [x] Write/run the failing rejected-cast evidence test; persist rejected
  model payload separately before propagating the unchanged validation pause.
  Never apply partial duties, change IDs, fill assignments or weaken coverage.
- [x] Qualify/deploy this narrow observability repair with preservation checks,
  then normal retry the same book to obtain raw identity/coverage evidence.
- [ ] Diagnose actual payload discrepancy from retained inputs/outputs and
  fix its source, then continue the original 80-chapter acceptance.

The cast observability repair changes only `application/creative/cast.py` and
`tests/test_cast_binding_evidence.py`. Exact qualified source:
`594c2c2656435d75cad3c3a7c42709e8c258b97fcc3600c8bc07020384eb1f18`,
644 files. Tencent QA: 1,142 full backend tests / 103.59 seconds, 17 focused
and static tests, Ruff, mypy (60 sources) and 13 zero-provider offline cases.
The failed cast result is saved as a separate rejected model decision; the
original coverage pause is propagated without applying any partial duties.
Input identity lists use JSON strings, preserving CreativeRecord's scalar
input_versions contract. No validation or retry allowance change.
The first focused command referenced a nonexistent test path and ran zero
tests; corrected commands retained separately (`green-v2`, `green-v3`), with
the final valid run and full regression qualifying the current source.
Evidence prefix: `long-r3-cast-evidence-`.

Deployment at 2026-10-02T07:29:19Z preserved all captured chapter content,
flags, sessions, records, budgets and the three retained-book checkpoint sets.
Both application containers healthy, public readiness 200. Live images:
backend `sha256:a460d2a592dc61ad8b4bb8e3f636158e631aa011da7a2a3a8ffda7373d2272c8`;
frontend `sha256:0c4e14c1e421a7087a96be59339854977fa3e4dcb4e67da816ac55b1763028ee`.
Rollback pins the prior `97d10cd8` images. Research services unchanged.

Normal public-HTTPS retry resumes the same book as
`c58fd0fd-4851-477f-80d1-d5a1ef629536`. Its real binding
`cast_plan:1:5bd588ea163a` covers all nine characters and six role slots,
with no duplicates. No failure record was needed for this valid result.
The first discarded response cannot be reconstructed; do not assert its
unobserved mismatch was an ID typo or omitted specific character.
At 07:33:11Z execution is in `chapter_writer_node`, preparation 35,
review 1 and chapter:1 10; no interrupts, accepted plan version 1, still
0/80 archived. Evidence: `long-r3-cast-evidence-actual-valid-binding.json`
and `long-r3-first-chapter-live-monitor.json`.

### First-Chapter Fact Scope Failure (2026-10-02T07:38:07Z)

The same run is released at `fact_review_node`, no chapter archived,
chapter:1 16/32, preparation 35 and review 1. It exhausted semantic fact
repair (2); extraction retry is 1. Do not reset those counters.
Checkpoint `1f1be340-0596-6c88-8044-020b9035ef98`, retained current draft
3,470 characters, SHA-256
`43bfa36660b0c6634b40b4ec1d23db16672ffcebd872e0df551e6a2b5e071e65`.
Evidence: `long-r3-first-chapter-fact-failure.json`,
`long-r3-first-chapter-backend.log`, `long-r3-first-draft-observation.json`.

The final report has no findings and a valid surname assertion plus four
registered-entity mentions. Its partial coverage instead requires resolving
the damaged document's owner and unresolved glue/page traces. The preceding
report required explicitly restating a known surname despite only naming
the registered person. This contradicts v4's actual-assertion-only contract.
The base judge still contains broader uncertainty/unsupported-type wording
that pulls suspense clues into the five supported fact predicates. The scope
contract is surname/family/ancestral_hall_owner/location/life_status, not
solving the chapter's mysteries or forcing all canonical attributes into prose.

- [x] Prove old partial reports/frozen broad prompts reproduce the block.
- [x] Introduce an unambiguous versioned judge prompt and extraction v5,
  preserving every existing evidence check and canonical conflict rule.
- [x] Freshly evaluate old unknown/no-finding reports using the existing
  extraction retry allowance. Preserve spent semantic/physical counters and
  prevent normal explicit retry from resetting them during this migration.
  New uncertainty still fails; never filter old reasons into a passing report.
- [x] Qualify, deploy with preservation, then recheck the same immutable draft
  through the normal public API. Do not alter prose, canon, budget or old books.
- [ ] Continue full 80-chapter archived manuscript and quality/export acceptance.

Qualified and deployed source
`4bed81554f0f032a57a1dd90118b9ed0c43c05a3051d87fe895c16a34e1f56d4`,
646 files/eight changed backend files, 1,147 full backend tests (104.07 seconds),
78 affected/static checks, Ruff, mypy and 13 zero-provider offline cases.
The two current-template freeze tests pin the new v2 judge resource; all their
immutability and structured-output assertions remain intact. No old snapshots
were edited. Real v4 report digest remains exactly compatible with v5 code.

Deployment at 2026-10-02T08:03:21Z preserved the captured 31 chapters, all
flags, budgets, sessions, records and retained checkpoints, readiness 200.
Live backend `sha256:f3554ba4213ac82355fe08533d59efa0c3ea47d092d98056157852e3bc059414`;
frontend `sha256:0f9dd8dd76b90b7c0445d0602eb38d2c13855326f5050576d22bd596460b20c0`.
Rollback pins the previous `594c2c26` live images. Research unchanged.

Same-book normal retry `1441c799-6913-476a-986c-85610b0d486b` produced a real
v5 fact pass, same draft hash, semantic repairs still 2 and extraction retries
now 2. Physical chapter:1 calls increased only from 16 to 17. No acknowledgement,
canonical change, budget grant or counter reset. Actual receipt:
`long-r3-fact-scope-production-receipt.json`, checkpoint
`1f1be37c-3188-6e83-8046-fcef125590b2`.

### Revision Source Staging Boundary

The next node `revision_review_node` rejected its own candidate as stale:
the pending revision was generated from source
`617c79029cdbf199411436871347b276f536816d1de366588142faf2dcf61eb8`;
the fact gate preserved candidate
`43bfa36660b0c6634b40b4ec1d23db16672ffcebd872e0df551e6a2b5e071e65`
as current body while evidence was unavailable. Fresh fact review then restored
the pending revision but left its source binding pointing at the pre-revision
body. Candidate and current body are identical; this is not an author overwrite.
All source/goal guards must remain; do not alter that old proposal in place.

- [x] Reproduce the real fact-staging path through revision generation,
  unknown fact gate and a fresh fact recheck. Negative cases must reject newer
  body, changed goal, missing/old/unknown/wrong-scope receipts and repeated rebind.
- [x] Permit one fresh proposal only for the already-staged identical candidate
  with unchanged goal and a current-version complete fact pass reverified
  against a fresh server snapshot. Preserve old source/proposal/report digest
  as provenance; no model call, prose edit or counter reset.
- [x] Require normal revision confirmation and independent quality/goal review
  after the new proposal. Retain staging provenance in revision history.
- [x] Qualify/deploy with preservation and retry the same book. Do not declare
  manuscript acceptance from this metadata recovery.

Qualified source
`2c556facc1af289ff21a463114c5eae6d7d5219baa08e504a5d40c9187a2debe`,
647 files, only the revision node and its new 15-case regression module changed.
Initial RED: 1 failed/10 passed. Final affected/static: 71 passed; full backend:
1,162 passed in 104.24 seconds. Ruff, mypy 60 sources and all 13 zero-provider
offline cases passed. The intermediate expanded fixture failed because it
accidentally created another tenant rather than a changed same-tenant ledger;
corrected to preserve scope and increment actual fact versions. No gate weakened.
Canonical conflict, newer body/goal, stale/incomplete/wrong-scope receipts,
absent repository, repeated rebinding and empty-ledger restoration all reject.

Read-only current author configuration and accepted brief reproduced normal
runtime assembly; the real checkpoint replay preserved goal ID and exact
3,470-character body, used zero provider calls and routed through a fresh
revision proposal to independent reflection. This is offline recovery proof,
not semantic manuscript acceptance. Evidence prefix: `long-r3-revision-staging-`.

Deployment at 2026-10-02T08:34:53Z preserved all captured chapters, tenant
flags, sessions, records, budgets and the three retained checkpoint sets;
public readiness 200, research images unchanged. Live backend
`sha256:65e359e3c0d20391e23e7806765e531a90271b70fbbe37f3db62f42e325fbfb8`;
frontend `sha256:ff806457459e516e4ae70e9150b95b2d884577ec79c1c4b493644f81a914a352`.
Rollback pins the previous `4bed8155` live images.

Normal public-HTTPS same-book retry `ab27efb2-0b4c-45b3-8190-ed57590829eb`
entered `reflection_node`. Actual checkpoint
`1f1be3c3-08cd-66b4-8049-78643dfa1fd4` retains the old proposal/source/report
digest as history provenance; before and after body hashes both `43bfa366...`.
Semantic/extraction recovery remains 2/2. Preparation 35, review 1,
chapter:1 18 includes the independent reflection provider call. Still 0/80
archived; complete prose quality, ending and export acceptance remain open.

### Same-Book Quality And Budget Boundary (2026-10-02T09:00:11Z)

Actual autonomous quality review identified the mixed archive/work-sheet
identifiers and a stroke-description finding, then independently checked
the 3,646-character repair. A subsequent editorial pass also found a page
sequence contradiction; the generated third candidate corrected it.
All prose changes were normal model-produced revisions, not direct edits.

The second main quality review passed the chapter events but classified
`author:hard:3` (do not present model market assumptions as real reader
feedback) as unknown because the chapter does not discuss feedback or sales.
Its reason explicitly says the text does not violate this prohibition.
This exposed a negative-constraint evidence problem: a universal prohibition
is being treated like a positive event requiring an occurrence quote.
The high score does not override the blocked goal result.

The third candidate is 3,705 characters, SHA-256
`94ebaca6e7a21f5486411558960a74fbcb33b53042b8a7e06253b8f7d176b09d`,
checkpoint `1f1be3ef-8be4-662c-8055-ddd920c051fd`.
Its real current fact report passes; its fresh editorial receipt is complete.
The latter flags a seal-ink state after the newly added wait until afternoon.
This is a model finding, not independently established physical impossibility.
The third candidate has not received a completed fresh main quality/goal
review: the checkpoint's main quality result still binds the preceding draft.
Do not reuse that old result or automatically accept the new draft.

The producer stopped normally on `creative_paused/budget_exhausted` at
32/32 chapter:1 calls; actual status is 0/80 archived and next reflection.
Preparation 35 and review 1; all physical limits remain
60/32/660/3280, search and preparation search 0.
Semantic fact/extraction recovery remains 2/2; quality recovery is 3,
baseline 0 and revision_attempts 3. No retry, reset, extension or acceptance
has been issued at this boundary. A normal legacy reflection retry would
reset recovery metadata, so it must not be used as a workaround.

Evidence: `long-r3-first-chapter-review-observation.json`,
`long-r3-first-chapter-quality-repair-receipt.json`,
`long-r3-first-chapter-second-quality-receipt.json`,
`long-r3-first-chapter-budget-boundary-status.json`,
`long-r3-first-chapter-budget-boundary-receipt.json`,
`long-r3-first-chapter-live-watch.jsonl`.
At 09:03:48Z all captured original chapter content and tenant flags remain
unchanged, active leases 0 and public readiness 200. The deployed revision
recovery is qualified; the full production/manuscript goal is NOT complete.

Historical proposal, not executed and superseded on 2026-10-02:

- Clarify negative-constraint review without accepting unknown results,
  loosening positive event goals, fabricating evidence or inserting
  compliance commentary into the manuscript. Require a fresh full-body
  review; evidence sufficiency must be tested before changing its contract.
- Authorize only this marked acceptance book's chapter limit 32 to 40,
  total ceiling 3,280 to 3,920, leaving existing tenant/monthly/search limits,
  preparation/review budgets and other books unchanged. This is a book-wide
  chapter ceiling, not an existing per-chapter override API.
- Permit at most one additional audited quality repair for this book's
  first chapter only (3 to 4), preserving cumulative counters and already
  spent fact/extraction allowances. A trusted book/chapter-bound control
  is required; never change the global reflection-loop setting.
- Resume only through normal authenticated workflow APIs after qualifying
  any required repair/recovery code; no direct checkpoint/prose/canon writes.
- Continue the same full 80-chapter manuscript and final quality/export
  acceptance. Additional exhaustion still stops; no unbounded extensions.

### Approved Budget Optimization

The user requested budget-mechanism optimization and renewed validation.
Execute `2026-10-02-elastic-budget.md` inline. Do not raise the total to 3920,
grant an additional quality attempt, change tenant limits or reset counters.
Use audited opt-in elastic allocation for long-r3 with total 3280 unchanged;
validate on Tencent QA before deployment and same-book normal API retry.

### Current Budget Verification

The first elastic release crossed the old32-call boundary normally, then
stopped at46 calls on purpose accounting. A qualified1195-test release
distinguishes4 prose repairs from1 proved same-body fact confirmation while
preserving aggregate2/2/5 and the existing effective quality maximum5.
Source490c499d was deployed with all fresh data/environment baselines intact.
The normal same-book retry preserved the3828-character draft, spent2 fresh
review calls and safely paused at48 before a repair requiring18 calls.
Only16 remain below the unchanged64 hard cap. Still0/80 archived.

The active budget plan now qualifies a narrow15-call local-only repair
without generation retries/full rewrite fallback. Independent fact,
editorial and main review remain required; no blind retry, cap raise,
counter reset or direct manuscript edit is authorized by this continuation.

### Final Budget Continuation Boundary

Qualified/deployed source5b5ea0af passes1214 full backend tests, Ruff/mypy
and13 zero-provider cases. Normal same-book continuation uses server-owned
paragraph references, and the real model patch changes only two linked
front-side labels to back-side. Fresh v5 fact receipt passes; normal extraction
consumption increases2 to3, without resetting earlier semantic2/quality5.

On the current3828-character body SHA-256085a7e46, fresh main review
event15816 has score0.922857 and no editorial must-fix finding, but fails
original goalch1:must:1 on establishing the named water archive institution.
The first chapter's5 actual prose repairs are exhausted; event15818 stops.
At2026-10-02T11:42:38Z the book is STOPPED,0/80 archived, chapter57,
preparation35/review1, total3280 and cap64 unchanged. Same hold15/remaining6.
All93 calls retain token receipts. Monthly23/102, original31 chapter rows,
tenant flags and other marked books unchanged; public ready200, active leases0.

No further retry or extra quality/chapter allowance is authorized/applied.
The budget plan documents a proposed scoped one-goal repair control with
sufficient bounded capacity, pending user authorization. Do not claim full
production readiness, complete manuscript quality or80-chapter acceptance.

### Approved Scoped Continuation

Latest explicit user approval authorizes one goal repair for long-r3 chapter1
only and hard72, keeping total3280/historical counts/fact caps unchanged.
The owner API controlbd885baf is applied with idempotent replay; sessionv4.
Current source6a42690c is qualified/deployed (1234 tests, Ruff/mypy,
13 offline cases/provider0), with fresh data/environment preservation.
Normal runc0295a42 generated a bounded patch,3845characters/bodyad107369;
fresh complete v5 fact receipt passes. Editorial/main review and archive
remain pending. Continue the same80-chapter book, never substitute a smaller
book or force acceptance. Detailed current evidence is in the elastic plan.

Fresh2026-10-02T12:14:09Z outcome: goal repair passes independent goals/score
0.922857 onad107369, but editorial blocks on paired glove action-state
contradiction already present in the unchanged previous prose. Prior full
coverage receipt missed it; new valid evidence must not be suppressed.
Normal bound stops before an unapproved extra repair. Still0/80 archived,
chapter63/72, book99/3280, original counters intact; all99 token receipts,
monthly23/102,31 original chapters/tenants/other books preserved, ready200,
active leases0. Full production acceptance remains incomplete; next scoped
mechanism change needs explicit approval, not blind retries or cap increases.

### Approved Progress And Actual Feedback

The user's "改进一下" authorizes the proposed action-state/progress-budget
improvement. Preserve the same80-book goal, whole3280/chapter72/64 bounds,
past spend/recovery and original data. Editorial v3, owner-only progress_v1
and a real one-line glove patch are implemented; no manual prose edit.
The first run8148dc15 nevertheless stopped0/80 on invalid predecessor
reports, chapter71/book107, with old review retry2 preserved.

Actual feedback is addressed by precise link diagnostics and prompt
instructions, immediate pause on two invalid reports, new-request independent
review accounting in the existing660 pool, and one body/protocol-bound
legacy unavailable-proposal migration. No refund, refill or cap increase.
Source61cfc56a passed1274 backend tests, Ruff/mypy and13 provider0 cases,
then deployed with fresh rollback and all data/environment baselines equal.
Run50f62609 continues the exact same3846-character body through fresh review,
new review2/chapter71 unchanged. At2026-10-02T14:09:50Z still0/80 archived.
Full production readiness remains UNVERIFIED; see the elastic-budget plan
for current status and private evidence references.

### First Archive, Same Full Book

Source0f12290d (1275 tests, Ruff/mypy,13 provider0 cases) also routes the
independent persist_node fact acceptance to the existing review pool.
No chapter/whole-book cap, old counter or fact check is bypassed.
Fresh deployment preserves all data/environment baselines and readiness200.
Normal run132cef66 archives chapter1 through passed goals/quality0.914286,
complete editorial v3/41 checks and complete passed v5 facts. Archived
3846-character body equals the reviewed da3f3177 exactly. All8 revision
entries retained; chapter1 stays72. Postprocessing succeeds and releases
the review hold,4 unspent, without refund. Original31 rows/flags/other sessions
remain unchanged. At2026-10-02T14:27:03Z same book1/80 and chapter2 generation
active; full production acceptance is still open, not completed.

### Second Chapter Evidence Correction

Normal chapter2 local repair changed only two grounded time/count errors,
with revision history retained. Run6fbd88fc then paused on a false server
rejection: genuine p4/p23 glove evidence was disallowed because p4's single
primary-object action check selected the register. Full source evidence is
not limited to those scalar labels or paragraphs containing action cues.
Two isolated failures reproduce the defect. The correction preserves
quoted-source validation, chronology, exhaustive coverage, predecessor
links and must-fix archive barriers.

Source49b3b383 passes1279 tests, Ruff/mypy and13 provider0 cases; deployed
with immutable rollback, all32 rows/checkpoints/counters/flags/other sessions
and environment hashes unchanged, ready200. Normal retry982a935f continues
the same3606-character second chapter (SHA411492d4); preparation35/review19/
chapter1=72/chapter2=12 at2026-10-02T15:26:29Z. Actual archive remains1/80.
Full production acceptance and human-quality validation remain open.
Evidence and remaining work: the elastic-budget plan and private
`long-r3-progress-full-source-pair-*` receipts.

### Semantic Review Follow-Up

Normal review accepted the glove pair; a one-paragraph repair preserves
the state. Subsequent review wrongly compared different source volumes'
paper sounds, exposing semantic identity risk. Normal cancellation stops
run982a935f, but third normal revision had already completed:3888 characters,
SHAf3ad0535/history3, chapter2=16/review28/total151.150 completed requests
have token receipts; one interrupted usage-unknown stays counted. No manual
manuscript/checkpoint rollback or refund. Archive remains1/80.

Sourcefefb978d4 qualifies1283 tests, Ruff/mypy,13 provider0 cases with explicit
source/object/time criteria and bounded rejected-report correction context.
Actual redeployment, new model review and second archive still require
verification. The original80-book contract is unchanged and unfulfilled.

Deployment verification at2026-10-02T15:56:27Z confirms exactfefb978d4,
backend6f87d7a0/frontend97e35f08, all paused data and environments unchanged,
ready200. Normal retry74e9ef0b continues3888-character chapter2. At15:57:41Z
archive1/80/preparation35/review29/chapter1=72/chapter2=16; new semantic
review and second archive still pending. No original acceptance is waived.

### Second Archive, Same80 Continuation

Real chapter2 archive now verified:3888 characters/SHAf3ad0535,
review_statuspassed/quality0.894286, fresh goal event21555 on original
c3603159 contract, editorial104 paragraphs/39 actions/findings[], complete
passed fact-v5 gate and all3 history entries. DB/API bytes match exactly;
postprocessing completes. Previous32 rows/tenant flags/other sessions remain
unchanged;33 rows now. Same book2/80,7734 characters, chapter3 reviewing
at2026-10-02T16:14:05Z, preparation35/review38/ch1=72/ch2=16/ch3=9.

Main review still labels a count-identifier discrepancy and ambiguous volume
referent optional. Preserve these as content-review risks, not "all errors
solved." Full80-book quality/ending/word range/exports and human-quality
acceptance remain UNVERIFIED; this is deployed mechanism and two-archive
evidence only. Private receipts: `long-r3-progress-second-archive-*.json`
and the source-identity watch/current-status files.
