# Production Readiness Delivery Record

## Contract

Date: 2026-10-01, Asia/Shanghai.
Target: make the existing application reliable enough for production use and
validate automatic book creation on the Tencent host, including actual prose.
Authorization: update and deploy this project on 124.220.67.163; preserve existing
books, credentials, databases, reverse-proxy integration and unrelated services.
Confirmed acceptance scale: 80 chapters, target 336,000 characters, using the
existing long-form preset and its 10% total-length tolerance. This confirmation
does not authorize shortening the final acceptance to the historical ten-chapter
book. A smaller preliminary run is a smoke test, not final acceptance.

- AC-1: Current source passes backend, frontend and research regression checks on
  the server. PostgreSQL tests use a dedicated database ending in `_test`; skipped
  database tests do not qualify as passed.
- AC-2: A fresh automatic-writing run produces a complete book with contiguous
  archived chapters, accurate actual word counts, independent quality reviews,
  a closed ending and no review JSON in the prose. A stopped or rejected draft
  does not qualify as completion.
- AC-3: Disconnecting a reader does not cancel writing. Cancellation stops model
  work. Retry and recovery preserve accepted artifacts and quota idempotency.
  Restart recovery must be tested explicitly rather than inferred from leases.
- AC-4: Read/export/edit paths, tenant isolation, stale-write rejection and
  database/checkpoint consistency work with the released application.
- AC-5: Review actual prose for opening clarity, motivation, causal progression,
  repeated material, continuity and payoff. Model scores are not human reader
  feedback and cannot prove parity with professional web-fiction authors.
- AC-6: Deployment records source and image identity, preserves the effective
  Compose chain, takes a database backup and retains a data-preserving rollback.
  Restore testing uses a separate database, never the production database.

No deletion of user books, no production migration downgrade, no disabling of
fact/goal/quality guards, no fabricated human reviews, no unrelated host cleanup,
no external publication. Real-model validation is limited to clearly marked
test books and bounded retries. Larger long-form and human-reader evaluations
remain explicitly unverified until performed.

## Baseline

- Local HEAD: `35d5cd6`, branch `codex/harness-usability-reliability`; worktree clean
  at initial inspection.
- Strict-host-key SSH succeeded as `ubuntu` on `VM-0-15-ubuntu`.
- Server project directory: `/opt/novel-writer`.
- Backend: `novel-writer-backend:materials-20260922-r2`.
- Frontend: `novel-writer-frontend:collection-fix-20260924`.
- Research API/worker: `novel-writer-research:collection-fix-20260924-r2`.
- Application containers healthy; active writing leases: 0.
- Migration: `0009_autonomous_author`.
- Effective planning switch on; autonomous-author and automatic-provider-retry
  switches off. Model: `deepseek-v4-flash`, OpenAI-compatible provider.
- Host memory: approximately 3.7 GB; available disk: approximately 5.8 GB.
- Existing production source differs from local HEAD. Historical ten-chapter
  results are context, not evidence for this release.

## Execution Plan

### 1. Server Regression Baseline

- [x] Verify SSH identity, containers, migration, active leases and resource limits.
- [x] Package current source and upload to a distinct release/QA directory.
- [x] Run PostgreSQL 16 in a dedicated QA container and internal QA network.
- [x] Reuse backend/frontend dependency images where the locks match; verify
  dependency compatibility before testing.
- [x] Run `ruff check .`, `mypy`, `pytest -q` and `scripts/harness_eval.py` for
  the backend, with `REQUIRE_DATABASE_TESTS=true`.
- [x] Run frontend `npm run lint`, `npm test -- --run`, `npm run build`.
- [x] Run research regression tests and migration checks.

### 2. Evidence-Led Fixes

- [ ] For each observed failure, record expected/actual behavior and root cause.
- [ ] Add a regression test and observe its failure before implementation.
- [ ] Apply the smallest production fix; rerun the failing test and affected suite.
- [ ] Inspect restart scheduling, export and complete-book termination against
  AC-2 through AC-4; implement only confirmed gaps.

### 3. Controlled Release

- [x] Capture the effective application Compose files, image IDs and source
  hashes without exporting credentials.
- [x] Back up production PostgreSQL, inspect the dump and restore into isolated QA.
- [x] Build the qualified release; recheck active leases before switching.
- [x] Update only project application containers, preserving research/Redis/edge
  configuration. Roll back image/configuration on failed health checks.

### 4. Actual End-to-End Acceptance

- [x] Create clearly marked test identities/books through the application's API.
- [ ] Verify browser/API workflows, tenant isolation, conflict handling and export.
- [ ] Run bounded real-model automatic writing and inspect archived prose.
- [ ] Verify disconnect and restart recovery in QA, then verify released behavior.
- [ ] Record current evidence and each unresolved requirement separately.

## Current Status

In progress, not production-qualified for automatic full-book delivery.
Backend/frontend have been deployed and are healthy. Migration is now
`0010_workflow_recovery`. The global autonomous availability switch is enabled;
the four original tenants' autonomous flags remain off and unchanged. Only a new,
clearly marked QA tenant is enabled, with finite request and generation quotas.
Research, Redis, PostgreSQL and unrelated services were not restarted.

Earlier inception regression: 812 passed against isolated PostgreSQL, no database
skips; locked ruff and mypy passed. Frontend: 178 passed, lint and production build
passed. Research: 42 passed. Harness rerun after the inception changes: 13 cases
passed with zero provider calls. Actual subprocess tests cover both graceful
shutdown and SIGKILL followed by real lease expiration, preserving PostgreSQL
checkpoints, quota identity and review budgets. These are controlled, no-provider
process probes, not proof of long-book prose quality.

Backup restore passed in a separate database: 11 books, 26 chapters, archived
content checksum unchanged (`27781e0517e4d2cb84368e4cd8ae69b6`). Protected dump:
`/opt/novel-writer/releases/production-20261001/production-before.dump`,
62,180,651 bytes, SHA256
`884397db912883d6eb3c19719794f22ca314ce51dcfe391a044d2cf5f72f199f`.
The original 61-file Compose chain and image rollback are retained. Rollback
does not restore old data over new user work or downgrade the additive migration.

Real-model smoke book `4ed0c270-b3ce-559d-9293-69c46001ecd0` stopped at inception:
14 preparation requests, zero archived chapters, all artifacts retained.
The deterministic gates were not bypassed. Observed defects: user title/summary
omitted from candidate input, model-request budget mistaken for chapter count in
independent planning, paraphrased evidence incompatible with exact-quote
validation, and an oversized 7,301-character repaired pilot. New regressions
cover input separation, motivation-preserving isolated context, and distinct
model/length/evidence rejection reasons. A fresh marked `smoke-r2` run is allowed
only after these fixes are qualified and deployed, using the same finite limits;
the failed book and its repair allowance are not reset.

R2 smoke book `79335525-cd8c-5249-8b56-cc44fb61a3b6` passed inception
automatically, planning and character design, then stopped at first-chapter
outline fact extraction. Both isolated pilots passed
the model and exact-evidence/length gates; the independent planner used the actual
3-chapter/12,600-character contract. No formal chapter is archived yet.
Production cancellation passed on this marked book: calls stopped with counters
unchanged over 22 seconds and original artifacts were preserved. It did not
restart automatically; a subsequent explicit authenticated retry resumed work.
Disconnect-after-first-event and browser reload do not stop the background run.
Cancellation evidence: `evidence/smoke-r2-cancellation.json`.

Fact-extraction diagnosis: the 22,250-character JSON outline contains repeated
strings. A bounded, recorded real-provider diagnostic returned nine claims,
including two quotes occurring five and three times. All entity references were
known, but deterministic evidence validation rejected the ambiguous quotes.
The model also interpreted absence of some supported attributes as incomplete
coverage. The first diagnostic used the wrong helper setting (`OPENAI_MODEL`
instead of the actual `DEFAULT_MODEL_NAME`) and received a provider 400; that
failed request remains recorded and counted. The corrected request used the
actual released model, without changing canonical facts or review decisions.
Evidence: `fact-diagnostic.txt`, `fact-diagnostic-r2.txt`.

Bounded repair: optional JSON Pointer evidence localization validates an exact
string leaf and a unique raw quote within that leaf; the receipt still binds the
complete original artifact and canonical snapshot. Body quotes remain globally
unique. Runtime protocol instructions distinguish absent attributes and future
plans from explicit current claims, including with old immutable prompt
snapshots. Empty claims, unknown entities, missing canonical facts and unresolved
evidence still cannot pass. An exhausted old failed report can be rechecked once
under the new protocol, without resetting recovery counts; another failure
cannot repeatedly invoke this upgrade. Regression evidence: three expected
failures before repair; 52 affected tests passed after repair. The combined
candidate subsequently passed all 812 backend tests and all 13 offline harness
cases, then was deployed with healthy application containers. The same R2 book
was resumed by an explicit authenticated retry, with original physical-request
caps and quota identity retained. The existing user-retry API starts a new
bounded fact-recovery cycle; it is not a process restart and does not prove
recovery counts remain unchanged.

The first candidate full run had 809 passes and one naming-fixture failure:
random tenant UUIDs changed candidate ordering, so the fake "valid" model could
recommend two core names with the same last character before reaching the
intended transaction-conflict assertion. The fixture now chooses a compatible
pair; production naming rules are unchanged.

A subsequent full run had 809 passes and one hard-crash recovery failure.
The retained PostgreSQL checkpoint was step 0 with durable initializer writes
and a `branch:to:complete` pending write, but no next full snapshot. LangGraph's
public state applied those writes and returned empty `next_nodes` with a
completed initializer task. Both the recovery service and restart admission
mistook the empty next-node list for completed work. The repair uses durable
pending task information as well as next nodes, without resetting execution
budgets or replaying initialization. A deterministic interrupted-snapshot graph
test and a real PostgreSQL recovery-service regression failed before repair.
These failures are retained as `fact-path-full.txt`, `fact-path-full-r2.txt` and
`pending-write-red.txt`; they are not counted as qualified full runs. Qualified
combined evidence: `combined-full.txt`, `combined-harness.json`,
`combined-ruff.txt`, `combined-mypy.txt`, `combined-build.txt`,
`combined-deploy.txt`. Browser normal login, desktop/mobile layout and reload
were repeated against this published image with no browser errors.

Real-provider validation of extraction v3 is still failing: the R2 book stopped
again with unknown coverage, zero assertions, and a Pydantic ValidationError.
Its preparation counter remains 16, chapter-one physical counter is 14 before
the subsequent one-request diagnostic. No formal chapter has been archived.
Evidence: `smoke-r2-fact-v3-watch.txt`. This is not a completed smoke run and not
proof that semantic fact extraction is fixed in production.

Two subsequent, separately metered one-request diagnostics were recorded. The
builtin-prompt diagnostic returned structurally valid data with zero claims and
partial coverage; unresolved reasons included attributes absent from the
outline. The diagnostic reproducing the saved prompt snapshot and creative
node rules returned an extra top-level `type` field, rejected by the strict
Pydantic contract, plus a `family` assertion based on a father/daughter relation
without a registered family entity. These observations are not permission to
discard unknown evidence, remove the extra-field validator, fabricate a family
fact or accept zero-assertion reports.
Evidence: `fact-diagnostic-v3.txt`, `fact-diagnostic-v3-bound.txt`.
Both calls consumed the existing chapter-one physical budget (now 16/32).

The user explicitly directed continued engineering and server deployment without
additional ordinary design approval. Extraction v4 separates explicit property
assertions from grounded mentions of registered entities. A complete report
without property assertions needs exact entity-name evidence backed by an active
canonical fact, with a unique raw quote (or exact JSON string leaf). This evidence
does not create a property or canonical fact. Real contradictions, missing
canonical support for actual assertions, malformed responses, partial coverage
and empty reports remain blocking. Archive transactions revalidate mention
identity, proof hash, location and full snapshot, then check snapshot currency.
Old v1/v2/v3 report digests and human acknowledgement bindings are preserved.

The independent extractor no longer inherits creative output instructions.
The versioned v4 protocol preserves immutable author templates while avoiding
reuse of an old extraction protocol. It explicitly distinguishes family/clan
membership from parent-child relationships and missing attributes from actual
unresolved assertions. Expected red evidence: `entity-mentions-red.txt` (9
failures, 15 passes), followed by `entity-mentions-snapshot-red.txt` (one old
protocol snapshot failure, 67 passes). Focused green: 68 passed. The qualified
v4 release passed 836 backend tests in 97.67 seconds, ruff, mypy (58 sources)
and all 13 offline harness cases with zero provider calls. Evidence:
`entity-mentions-full.txt`, `entity-mentions-qualification-binding.json`.
It was deployed with healthy app containers and research unchanged.

R2 then passed outline fact extraction after two rejected path responses,
generated a 4,490-character first chapter, and passed body fact review with five
grounded named-entity mentions and no property assertions. It has still not
archived a chapter. The retained body receipt binds full hash
`1f4089504f3eb05c59bb1db349fa2b603fb48df71233776a83196776c36cb7bd`.
It then stopped before quality review with a goal-source mismatch.
Physical counters are preparation 16 and chapter one 25/32.
Evidence: `smoke-r2-v4-grounded-report.json`,
`smoke-r2-v4-checkpoint-error.json`, `smoke-r2-goal-provenance.json`.

The production wrapper stack caused this mismatch: research binding ran inside
prose projection, treated the missing projected research field as unbound and
persisted the projected brief/total outline, losing author goal sources. Prose
projection also removed the goal contract, bypassing writer entry validation.
Five failing tests reproduce this combination. Material binding now runs outside
the measured creative/projection wrapper. Server-only scoped source validation
is kept apart from model-visible current chapter requirements, with future
author truth excluded. Previously bound approved material is preserved.

The damaged source can only recover from the same tenant's saved novel when
the exact original bound contract matches; it cannot be rebound to a weaker
contract or guessed from the generated prose. A read-only production check
confirmed the saved source recompiles to the original goal ID
`9b84bf908ddbf0b80562823e040b775292171270bf628ecae0445566ce0320d8`.
Evidence: `smoke-r2-saved-goal-source-check.json`. Recovery leaves the body,
physical budgets and upstream targets intact. Additional red evidence:
`goal-recovery-red.txt` (6 failures, 2 passes); focused green: 55 passed, ruff and
mypy clean. The qualified repair passed all 844 backend tests, static checks
and all 13 offline harness cases, then was deployed with healthy containers.
Evidence: `goal-boundaries-full.txt`, `goal-boundaries-harness.json` and
`goal-boundaries-qualification-binding.json`.

The retained R2 run continued into actual quality review. The first review
scored 0.902857 but blocked a contradictory missing-number sequence and a
miscounted quoted phrase. Patch evidence failed validation, so the existing
automatic policy generated a full revision rather than applying an ungrounded
patch. The revised 4,508-character body passed fact review and scored 0.917143,
but the goal verdict remained blocked: inception's provisional names differed
from adopted character names. The reviewer also attributed names to the user's
unnamed seed; that claim is not accepted as evidence. R2 safely paused at the
unchanged chapter-one physical cap of 32/32, with zero archived chapters.
Its goals, counters and artifacts have not been reset or manually accepted.
Evidence: `smoke-r2-first-quality.json`, `smoke-r2-budget-stop-quality.json`.

The next candidate binds each model-generated provisional name to an exact
creative-brief quote and an accepted character identity before goal compilation.
It updates generated brief/strategy and relationship prose, not user seed,
source quotations or already-bound goals. Five expected regression failures
were observed before implementation, followed by 21 affected passing tests.
Full regression then caught excess helper nesting; an additional failing test
caught unsynchronized relationship prose. Both defects were repaired.
Qualified evidence: 852 backend tests passed in 97.24 seconds, all 13 offline
harness cases passed with zero provider calls, ruff/mypy passed and application
containers were deployed healthy. Evidence:
`character-source-names-qualification-binding.json`.

A new independent R3 smoke book was created through authenticated APIs:
`4866fe84-f7ae-5a37-add7-00bcef40c598`, three chapters / 12,600 characters.
Its physical caps remain preparation 60 and each chapter 32, with search
disabled. It started successfully and continued after the API reader
disconnected. R3 is preliminary, not the 80-chapter acceptance deliverable.
Real-provider execution, archived prose and exports remain under verification.
R3's adopted design supplied two exact provisional-name bindings; original
names no longer appear in its generated brief, strategy or plan sources.
Its accepted three-chapter plan is retained. It subsequently stopped at
`creative_decision_node`: a previously accepted future-role window contained
`ch1`/`ch3`, which the integer contract only checked during late initialization.
Preparation counter remains 15 and zero formal chapters are archived.
Evidence: `smoke-r3-name-source-check.json`, `smoke-r3-planning-stop.json`.

The next repair validates all candidate future-role windows before persistence.
Only an explicit `chN` chapter reference is canonically parsed at this model
boundary; ambiguous text, booleans, reversed/out-of-book windows and duplicate
slot IDs are rejected. The strict RoleSlot value object is unchanged.
Recovery reads the original accepted selection without rewriting it and
validates every slot before any initialization write. Ten regression cases
failed before repair; 30 affected tests and static checks subsequently passed.
The repair passed all 862 backend tests in 97.96 seconds, all 13 offline
harness cases and static checks, then deployed healthy. Evidence:
`role-slots-qualification-binding.json`. R3 resumed through authenticated retry,
preserving its accepted plan and preparation count of 15. It successfully
crossed initialization/cast binding and entered tactical/first-chapter planning
under the original 32-request chapter cap.

R3 then stopped safely at outline fact extraction after three invalid-path
responses. A separately metered one-request diagnostic reproduced the
failure: a mention selected `/plan_context/current_action/...`, but that
`current_action` key does not exist in the original 26,546-character JSON.
Four other mentions had valid paths; the entire response was rejected, not
partially accepted. Chapter-one physical counter is now 9/32, including that
diagnostic. Evidence: `smoke-r3-outline-fact-stop.json`,
`smoke-r3-fact-path-diagnostic.json`.

The next candidate provides source-derived entity-name locator hints for
JSON outlines while retaining the full original input and its hash. Hints
come only from exact string leaves with a unique name occurrence and an
applicable confirmed fact; future plan contexts are excluded. They are not
property assertions or a completeness verdict. The model still must review
the complete artifact; incorrect returned paths, unresolved assertions and
empty reports still fail. Three expected failures were observed before
implementation; 64 affected regressions and static checks passed afterward.
The candidate then passed all 866 backend tests in 97.17 seconds, all 13
offline harness cases and static checks, and deployed healthy. Evidence:
`fact-evidence-catalog-qualification-binding.json`.
R3 continued through real model extraction with four grounded mentions,
complete coverage, zero assertions/findings/unresolved reasons. Its current
outline receipt binds full artifact hash
`ff61b68245bf8f93e5003f6fc50d7ace8e31e1adcbafde825e1ad272dc7fa5c2`
and the first chapter's goal ID is
`922c5c1b217da4e334461a4fff6f47ed0c0040dc6e367801bc4741800c4f1a49`.
Evidence: `smoke-r3-grounded-outline.json`. This proves the extraction
boundary, not completed prose or whole-book quality.

R3's first chapter was subsequently reviewed and genuinely archived:
4,702 characters, independent model score 0.925714, all original goal checks
passed with valid source quotations, no hard failures. Its body SHA-256 is
`7eb80d40044b70f9e17d96ec74becfc0ab06cee49b6c6dc7011122c46db61e43`.
Authenticated TXT/Markdown exports retained the exact archived text and UTF-8
BOM; outsider export returned 404. The real public HTTPS browser also downloaded
the manuscript successfully. This is one of three preliminary chapters, not
a completed book. Evidence: `smoke-r3-first-archived-goals.json`,
`smoke-r3-first-archive-export.json`.

Two preceding high-scoring reviews had accepted event reasoning but malformed
quotations, so the old recovery route performed full prose revisions instead
of repairing review evidence. Operator cancellation arrived after final
acceptance and preserved the archived chapter; it is now paused at postprocess
with chapter-one physical counter 29/32. No quotas or goals were reset.
The next candidate resolves model-selected contiguous source paragraph spans
to exact original text and retries evidence-only review at most twice without
rewriting prose or consuming revision attempts. Actual failed/unknown goals
still cannot pass. Six expected failures were observed before repair; 51
affected regressions and static checks passed. All 874 backend tests and all
13 offline harness cases subsequently passed; the repair deployed healthy.
Evidence: `goal-evidence-recovery-qualification-binding.json`.

The first review also identified generated address-system metadata retaining
old nicknames (`砚砚`, `小沈`) despite adopted full-name alignment. It was correctly
nonblocking for this chapter's consistent actual dialogue. New designs now
reconcile only generated address metadata after official name selection and
before character confirmation. Missing/duplicate identities, extra fields and
replaced full names are rejected; all other identity/profile/source fields
remain unchanged. Four expected regression failures were reproduced first.
Existing bound R3 goals and archived prose were not rewritten.

R3's subsequent postprocess attempt stopped with an invalid literal-text
position. A single physically metered diagnostic reproduced the cause:
all five model quotes existed uniquely, but all five integer offsets were
wrong. Original counter is now 31/32; it was not increased/reset. Raw diagnostic
is retained, not applied as reader truth. Unique literal quotes now resolve
their exact positions on the server; ambiguous quotes still need a correct
offset, and fabricated quotes/draft/stale-version evidence still fail. Reader
responses are cached before validation and invalid responses retained for
diagnosis. Six added regressions initially produced four expected failures;
49 affected cases passed after both repairs.
The actual diagnostic then passed on the deployed backend at positions
290/1250/1412/1787/3056 with zero provider calls and no state mutation.
Evidence: `smoke-r3-postprocess-evidence-diagnostic.json`,
`smoke-r3-postprocess-fixed-replay.json`.

Both repairs passed all 884 backend tests in 97.61 seconds, ruff/mypy and all
13 offline harness cases, and deployed healthy. The original research services
were unchanged. Evidence: `postprocess-addresses-qualification-binding.json`.
The public HTTPS browser verified normal login, loaded desktop/mobile state,
reload and a real partial-manuscript download on this deployed release.

The final 80-chapter/336,000-character acceptance book has now been created and
started through authenticated APIs:
`bd11a3a8-7b78-59a2-8e6c-f697836cd9e2`. It continues on the server after the
stream reader disconnects, under preparation 60 / chapter 32 / search 0 caps.
The validation strategy now uses its first three chapters as preliminary
milestones, then continues the same full-size book. This replaces repeated
new smoke-book creation, not the final contract. Retained R3 remains a partial
one-chapter sample with insufficient remaining chapter-one budget for all
three postprocess model tasks; it is not marked complete or reset.

The long-form run first stopped at character review because JSON output mode
required an explicit JSON instruction. The saved prompt snapshot was preserved;
the request now supplies that protocol in its system instruction. Three red
regressions also covered overlapping quote occurrences, which must not be
treated as unique. All 887 backend tests passed and the fix deployed healthy.
The same book resumed at preparation counter 14, then its actual eight-person
address design passed and its 80-chapter plan was accepted at preparation 21.
Evidence: `long-character-review-stop.json`,
`json-overlap-qualification-binding.json`, `long-character-address-check.json`.

Readonly inspection found legacy provisional names in the original accepted
story engine. New initialization and recap views now project those names
through admitted stable character IDs/current canonical names. Original
selection/engine history, quoted sources and identity fields are not rewritten.
Four regressions reproduced missing alignment and an ID/name collision before
repair; all 891 backend tests passed for this intermediate candidate.

The first long-form chapter genuinely archived at 3,751 characters with model
score 0.911429 and original goal checks passed. It then stopped in thread
postprocessing: a quoted code occurred five times and its model-estimated
offset was wrong; the model also returned unsupported status `planted`.
The reader-state result was already saved and retained. Evidence:
`long-postprocess-stop.json`, `long-postprocess-geometry.json`.

The combined repair supplies server-indexed paragraph references to all three
postprocess tasks, retains exact chapter/version/hash checks and rejects
fabricated, reversed or nonexistent references. Source-span positions are
shared with goal-evidence repair. Foreshadow states are supplied from the actual
value-object enum; unknown character references fail before writes. Each
metadata task execution may try at most two proposals under the unchanged
physical cap, retaining rejected proposals and reloading partially applied
state. Lifecycle/canon conflicts cannot be retried into acceptance. No prose
or bound goal is rewritten. Five expected failures plus an unknown-character
failure were reproduced; 74 affected tests passed, then all 902 backend tests,
static checks and 13 offline harness cases passed. The combined candidate
deployed healthy. Evidence: `postprocess-spans-qualification-binding.json`.

The same book then completed all first-chapter postprocessing, using 19/32
physical chapter requests, and automatically entered chapter two. A readonly
audit verified ten exact archived proofs and the completed postprocess receipt.
The projected engine contains none of its five provisional full names while
the original engine history is unchanged. Authenticated TXT/Markdown partial
exports retained the exact 3,751-character first chapter and BOM; outsider
export returned 404. Evidence: `long-first-postprocess-proof.json`,
`long-first-archive-export.json`, `long-first-milestone-watch.jsonl`.

The original long-form sample subsequently archived three sequential chapters
(3,751 / 3,452 / 5,051 characters; total 12,254), all with model-review status
passed and completed postprocess receipts. A readonly audit verified 71 archived
proofs against exact versions, hashes and source spans; authenticated TXT/Markdown
exports preserved all three bodies and outsider export returned 404. Chapter
three used 31/32 physical requests. The workflow automatically entered chapter
four, whose draft/checkpoint was preserved by controlled QA-only API cancellation.
Evidence: `long-three-chapter-archive.json`, `long-three-postprocess-proof.json`,
`long-three-postprocess-watch.jsonl`. This is a technical milestone, not a
passed literary or whole-book acceptance.

Two real recovery defects were reproduced and repaired before this milestone.
Partial semantic fact reports without structured findings previously rechecked
the identical draft rather than revising it; bounded draft repair now receives
the actual report/artifact without confirming unknown facts. All 905 tests passed
and the repaired chapter-three outline received a real passing fact receipt.
Then a tactical window had committed before fact review paused, while its
checkpoint still retained the old expected version. Recovery now reuses only
the exact latest committed window, under the novel lock and current plan-link
check, and checkpoints its committed version even when outline facts pause.
Changed content, older versions, ordinary stale writes and replan-invalidated
windows remain rejected. Three regressions failed before repair; all 908 tests
passed. Evidence: `fact-partial-qualification-binding.json`,
`long-tactical-fact-stop.json`, `tactical-fact-qualification-binding.json`.

Actual reading exposed count errors and glove-action discontinuity in chapter
two. Chapter three also inherited the erroneous count and introduced another
count mismatch. The original sample therefore FAILED literary acceptance despite
high model scores; no manuscript, accepted goal, review receipt or physical
counter was edited to manufacture a pass. Server-owned checks now recompute
adjacent explicit Han-only written-text counts, conservatively excluding dialogue,
mixed-script or unsupported cases. A versioned copyediting contract adds action,
tool, time, quantity, information and repetition checks to real reviews while
preserving legacy prompt snapshots. Tactical generation now carries the current
confirmed fact snapshot. Explicit fact retry also preserves the quality revision
baseline instead of accidentally discarding unrelated recovery metadata.

The final acceptance runner independently rejects known copyediting errors even
if archived model-review status says passed. Three further red regressions covered
the inherited reverse-order count, the unchanged full-size rerun contract and
false full-book acceptance. The current combined release passed 73 affected and
all 924 backend tests, static checks and 13 zero-provider-call offline cases,
then deployed healthy. Evidence: `editorial-final-qualification-binding.json`,
`long-second-editorial-replay.json`. A real metered retrospective chapter-two
review is a diagnostic, not a rewrite or human evaluation.
The completed real retrospective review used two metered physical requests and
returned `refactor` despite a 0.814285714 score. It supplied valid literal evidence
for the glove-action break, the 1.75-metre water-level difference incorrectly
reused as paper length, and the nine-Han-character phrase called six characters.
No manuscript or canonical fact was changed. Evidence:
`long-second-real-editorial-review.json`.

After the pre-archive corrections, a fresh full-size acceptance book was created
and started through normal authenticated APIs:
`ed4eafa6-81be-58de-b956-842d155502fb` (`long-r2`, title suffix `长篇R2`).
Its contract remains 80 chapters / 336,000 characters / original 10% tolerance,
with preparation 60, chapter 32 and search 0 caps. Original failed books,
manuscripts and counters remain retained. This is a new complete E2E qualification
after relevant fixes, not a shortened acceptance or renewed exhausted budget.
It is not yet complete or literarily accepted.
Its accepted version-one plan covers all 80 chapters and it generated a
3,614-character first-chapter draft. Readonly whole-plan inspection then found
that the tide appraisal completed at chapter 28 is scheduled to restart its
seven-day wait at chapter 63, in the final-deadline-day volume. The initial plan
had only deterministic structural validation, not semantic consistency review.
The marked QA workflow was cancelled through its normal API with zero archived
chapters; preparation 27 and chapter-one 13 physical requests remain retained.
Evidence: `long-r2-plan-consistency-stop.json`. This is an additional observed
production-acceptance failure, not a successful whole-book qualification.

A candidate complete-plan gate reviews all slots, volume/arc chronology,
single-use resources and causal ending support before autonomous acceptance.
Reports are bound to exact complete-input hashes and string-leaf JSON Pointer
quotes; malformed or unsupported reports fail closed and remain retained.
One persisted repair request is admitted per base plan version, with independent
review of the regenerated candidate. Replaying the same request does not request
another review or consume another repair; a second failed candidate pauses.
Normal scale, completed/locked-slot, ending and replan policies remain in force.
Manual legacy mode is unchanged. The first red run had seven genuine missing-gate
failures and two invalid test-fixture failures; the fixture was corrected rather
than counted as a product repair. The corrected regressions were also run against
the immutable previous release: 13 failed / the manual-mode isolation case passed.
Readonly review found the remaining autonomous minor-drift direct-accept path.
That path now checkpoints its candidate for complete-plan review; benign deferral
does not consume structural-replan allowance. Existing-plan review uses the
original review budget rather than the following chapter's cap. Two additional
red failures reproduced the bypass and wrong budget bucket. The fixed focused
review had no remaining findings. The combined candidate passed all 944 backend
tests, 74 affected tests, static checks and 13 zero-provider-call offline cases,
and deployed healthy with no active leases. A mistakenly API-prefixed readiness
probe returned 404; the actual backend-root `/health/ready` returned 200/ready.
Research image IDs and original tenant flags remained unchanged.
Evidence: `plan-consistency-red.txt`, `plan-consistency-focused-r2.txt`.
Final bound evidence: `plan-consistency-baseline-red.txt`,
`plan-consistency-drift-red.txt`, `plan-consistency-code-review.json`,
`plan-consistency-reviewed-qualification-binding.json`.

The same `long-r2` book entered normal authenticated, versioned future replanning
from expected version one, retaining 80 chapters / 336,000 characters / 10%
tolerance, its first-chapter draft, preparation 27 and chapter-one 13 counters.
No manuscript or accepted goal was manually modified, no counter was reset,
and no additional acceptance book was created. The disconnected stream reader
does not stop its server-side run. Evidence:
`long-r2-plan-replan-request.json`, `long-r2-plan-replan-watch.jsonl`.
The first actual model consistency review rejected two supported defects:
chapter 32 still waits for the appraisal completed at chapter 28, and volume
two's opening state already includes the father's admission first scheduled at
chapter 35. A model evidence pointer also omitted `ending_contract`; the raw
version-one report is retained. The workflow paused at `plan_review_protocol`
with preparation 27, chapter-one 13 and review 6 requests, zero archived chapters,
and the original version-one accepted plan unchanged.

The next candidate admits evidence-path localization only for a missing pointer
whose entire quoted string exactly matches one unique leaf in the complete
input. Existing wrong leaves, fragments, duplicate leaves, non-string targets,
malformed pointers and invalid escapes remain rejected. A derived system report
is versioned separately; its semantic rejection is not changed. Plan review also
receives durable historical execution receipts for completed chapters so that a
planned event is not silently treated as an actual occurrence. Future prerequisites
are still required, and changed receipts invalidate old review hashes. The
zero-completed-chapter input stays byte-compatible with the existing cached review.
Readonly review found no remaining focused findings after the strict pointer
boundary corrections. Red regressions reproduced missing localization, missing
execution context and malformed-pointer admission before their fixes.

All 956 backend tests, 101 affected tests, Ruff, mypy and 13 zero-provider-call
offline cases passed for the exact source below. A readonly replay of the actual
paused report confirmed its unique corrected path without model calls or
production-state mutation; both semantic failures remained rejected. The candidate
was deployed with zero active leases and backend-root readiness 200. A normal
authenticated retry resumed the same QA book and entered automatic regeneration;
preparation 27 and chapter-one 13 stayed unchanged, review advanced to 7.
Actual independent model review of this regenerated plan rejected four
evidence-supported issues and the workflow paused at its existing automatic repair
limit: chapter 13 and chapter 21 both initiate the seven-day wait; chapter 60 and
chapter 72 change the intended reputation-versus-water-rights dilemma into a
correction-versus-water-rights dilemma; a family-arc milestone differs from its
slot location; the ending then grants both newly declared mutually exclusive
outcomes without a mechanism. The model did not accept the candidate. The original
accepted version one, zero archives, 3,614-character draft and physical counters
(preparation 27 / chapter-one 13 / review 12) remain. All four reports have valid
literal evidence bound to the complete input, not merely a model score.
Evidence: `plan-evidence-execution-red.txt`,
`plan-evidence-pointer-boundary-red.txt`, `plan-evidence-escape-red.txt`,
`long-r2-plan-review-paused-fixture.json`,
`long-r2-plan-review-locator-replay.json`,
`plan-evidence-execution-qualification-binding.json`,
`long-r2-consistency-repair-watch.jsonl`.
The rejected regenerated plan and report are retained in
`long-r2-consistency-regenerated-plan.json` and
`long-r2-consistency-repair-rejected.json`.

The next scoped generation correction addresses an observed input boundary:
historical generated `main_plot` is labelled confirmed macro outline, while
volume generation lacks the admitted story engine and complete cross-volume
blueprint. Both blueprint and each volume now receive the persisted accepted
selection, author constraints and the full serialized global boundaries.
Historical unlocked planning is explicitly editable when repairing contradictions;
completed/locked chapters and author intent remain protected. Brief and engine
narrative names are projected together through admitted identities, preserving
raw research/source quotes and original records. Older generation checkpoints
hydrate missing derived context without restarting completed volumes, and older
prompt snapshots retain their original templates plus the new contract supplement.
Manual legacy behavior and physical request caps are unchanged.

A further API-to-node regression reproduced explicit versioned replanning routing
back into the previous rejected proposal. Valid new replan commands now clear
only transient proposal/generation/feedback state after the accepted-version check.
Retries, resumes, stale version rejection, accepted plans, drafts, persisted repair
requests and physical counters are unaffected. Red evidence:
`plan-generation-source-red.txt` (four expected failures / legacy pass),
`plan-generation-brief-red.txt`, `plan-generation-restart-red.txt`.
The intermediate full run had 962 passes and one unchanged 50-line maintenance
limit failure; the replan-input boundary was extracted as a typed local helper.
The following static run exposed a missing helper annotation before deployment;
it was corrected without weakening the type policy. Both failed candidates remain
unpublished with their evidence retained. The exact final generation candidate
`67209f2753e07ba1fcee80d154a01d8963c49445f01d291ae49d3e7ed26b011f`
passed all 963 backend tests, 63 affected/maintenance tests, Ruff, mypy and 13
zero-provider offline cases. Focused readonly rereview found no remaining issues.
Evidence: `plan-generation-qualified-full.txt`,
`plan-generation-qualified-r2-mypy.txt`, `plan-generation-qualified-r3-*`.
Deployment then completed with zero active leases, preserved configuration,
healthy backend/frontend and backend-root readiness 200. Running image labels
match the qualified source. Research services remain unchanged.
An ordinary authenticated, expected-version-one future replan was submitted for
the same book after the source correction. It explicitly addresses the preserved
real report without changing the contract, editing manuscripts or resetting
automatic repair allowance/counters. The new request entered a fresh planning
batch (review 13 / preparation 27 / chapter-one 13). Actual model acceptance,
archival and whole-book completion remain pending.
Evidence: `plan-generation-qualified-r3-qualification-binding.json`,
`long-r2-plan-source-replan-request.json`,
`long-r2-source-contract-replan-watch.jsonl`.

The subsequent real full-plan review rejected proposal
`e85ff825-d420-4fec-80d1-fbfda8321187` with complete coverage. Timeline and ending
causality passed, but literal evidence identified one favor consumed at chapters
18 and 22, the same signature-time comparison at chapters 26 and 42, and freezing
the same archive at chapters 60 and 71 without a stated stage distinction.
The workflow correctly paused: accepted plan version one and the 3,614-character
draft remain unchanged, zero chapters archived, preparation 27 / chapter one 13 /
review 19. Evidence: `long-r2-source-consistency-rejected.json`.

Source tracing found that volume generation received only the last four prior
slots and outstanding setup IDs; earlier resource consumption and evidence
conclusions were absent. A regression failed on the missing full prior-event
context (`plan-generation-history-red.txt`). The candidate now supplies all
earlier planned chapter numbers, story functions, required events and state
deltas, explicitly labeled as planning rather than archived facts. Later-volume
history excludes future retained slots; manual behavior, retries, repair limits,
physical counters and acceptance gates are unchanged. The exact candidate
`bf5e6f1792b4bca28869f15ec14bc70eda6d9623f68666d87f36bf67a7687920`
passed 964 backend tests, 60 affected tests, Ruff, mypy and 13 offline cases with
zero provider calls. Readonly incremental review found no blocking issue;
future retained slots are covered by the regression. The actual final-volume
history projection of 60 slots is 16,014 serialized characters, excluding
irrelevant metadata. Deployment completed at 2026-10-01T13:49:33Z with zero active
leases, preserved configuration and healthy backend/frontend; readiness returned
`ready`. The unchanged research containers retain their original image IDs.
An ordinary expected-version-one replan of the same book now runs with the
preserved prior constraints and the three new literal defects as correction
instructions; no manuscript edit, counter reset or repair-allowance reset.
Evidence: `plan-generation-history-final-qualification-binding.json`,
`long-r2-plan-history-replan-request.json`,
`long-r2-history-context-replan-watch.jsonl`. Model acceptance and archival remain
pending.

The real complete review of history-bound proposal
`2e9872ed-245d-4345-adee-e95846d80add` passed timeline, single-use resources and
ending causality. It still rejected one literal cross-layer defect: the main
arc's chapter-60 escalation incorrectly says the heroine is first suspended,
while immutable facts, chapter 58 and the volume climax locate that first
suspension at chapter 58. Chapter 56 records testimony, 57 names responsibility,
58 applies suspension and 60 accepts/freezes the archives. The exact original
arc wording was independently read; this is not an evidence-pointer failure.
The accepted version-one plan, 3,614-character draft and counters remain intact
(review 25 / preparation 27 / chapter one 13); zero archived chapters.
Evidence: `long-r2-history-consistency-rejected.json`.
The unchanged qualified code now runs a normal versioned replan with that newly
supported arc-alignment correction, preserving all prior passing constraints.
Evidence: `long-r2-plan-arc-replan-request.json`,
`long-r2-arc-alignment-replan-watch.jsonl`.

The next complete review rejected proposal
`212324be-feff-4228-af5c-179511c6278d`: three criteria again passed, but a different
evidence-chain milestone was assigned chapter 35 instead of the chapter-36 slot.
Exact context hash and literal evidence were verified independently; the earlier
56/57/58/60 correction did not regress. Evidence:
`long-r2-arc-consistency-rejected.json`, `long-r2-arc-candidate-preflight.json`.
Rather than regenerate every unrelated layer again, the candidate adds an
opt-in, named-proposal milestone correction to the existing future-replan API.
The server reads the authenticated tenant's actual checkpoint and rejects custom
input, stale IDs/base versions and manual mode before reserving quota. A valid,
complete, exact-context-bound report with only cross-layer failure may authorize
one cached model patch to its cited escalation text and chapter number.
Other fields and metadata, all slots, scale, volumes and ending are preserved.
Both old and new milestone chapters must be beyond the completed/locked boundary.
The new proposal still requires new whole-plan review, locked transition and
author replan policy/contract audit; existing automatic-repair allowance is not
reset. Invalid raw results are retained and retries reuse them rather than
consume unbounded physical requests.

Twelve initial regressions failed against the old implementation
(`plan-milestone-red.txt`). Initial focused tests caught an incorrectly placed
volume-prompt return and a test-only attribute/nesting error; those unpublished
errors were corrected. A 983-test intermediate candidate passed but readonly
review identified metadata deletion and missing milestone lock protection.
Three additional regressions reproduced both findings before repair
(`plan-milestone-boundary-red.txt`); only the authorized keys are now updated,
with old/new chapter guards. Readonly rereview found no remaining blocking
findings. The final milestone candidate passed all 986 backend tests, 66 affected
tests, Ruff, mypy and 13 zero-provider offline cases, then deployed healthy at
2026-10-01T14:34:21Z. Its exact source was
`25c0bb2540c034ee47403d051caf8d6d17cd824b291d1d9de0169efcc2d6a22f`.
Evidence: `plan-milestone-final-qualification-binding.json`.
No failed/intermediate candidate was deployed.

The actual named-proposal repair then exposed a missed entry-chain defect:
reuse of the already accepted character design cleared the unrelated pending
novel-plan proposal before initialization. It stopped before any provider call;
accepted version one, the 3,614-character draft and review 31 / preparation 27 /
chapter one 13 remained unchanged. Readonly history inspection confirmed that
the same run's earlier checkpoint still held the exact source proposal with all
protected inputs equal. Evidence: `long-r2-milestone-entry-failure.json`.

Character reuse now preserves unrelated proposals. Standard retry may recover a
lost named proposal from at most 16 checkpoints of the same workflow run, only
when author mode, accepted plan, generation, complete request, draft, chapter
index and proposal versions all match. It deep-copies only the original proposal,
clears any old decision, and does not reset physical counters or allowances.
Changed inputs, a different run, or an absent original proposal fail closed.
The normal consistency hash and full review still run afterwards.
Real-node and InMemorySaver regressions reproduced the lost proposal. Independent
review also found a recovery route overwritten by subsequent draft routing;
another real-graph regression failed before the early-return correction.
Intermediate fixture/maintenance failures remain unpublished.

The final entry-chain candidate passed 997 backend tests in 98.57 seconds,
53 affected tests, Ruff, mypy (58 sources) and 13 offline cases with no provider
calls. Readonly rereview found no remaining blocking findings. Deployment
completed healthy at 2026-10-01T15:02:01Z, preserving configuration and research
services. Standard authenticated retry resumed the same book and quota identity.
The real cached model patch changed only
`/plan/arcs/3/escalation_points/6/chapter_number` from 35 to 36; its change text and
all other plan fields were independently compared against the rejected original
and remained equal. The new proposal's full review passed all four criteria;
the subsequent replan-contract audit and acceptance were still pending at the
2026-10-01T15:05:03Z observation. Counters were review 34 / preparation 27 /
chapter one 13, zero archives, with the same 3,614-character draft.
Evidence: `plan-milestone-entry-red3.txt`,
`plan-milestone-entry-routing-red.txt`,
`plan-milestone-entry-final3-qualification-binding.json`,
`long-r2-milestone-entry-retry-request.json`,
`long-r2-milestone-entry-retry-watch.jsonl`,
`long-r2-milestone-live-patch.json`.

The contract audit then passed and the repository accepted plan version two.
Normal continuation paused at cast alignment with `cast_coverage`: the existing
validator rejected incomplete character coverage before applying any new duties.
The failed cast response was not persisted by the existing cast implementation,
so its exact missing assignments cannot be reconstructed. A single diagnostic
using the same bound task input and normal chapter-one request meter returned
all eight admitted character IDs and all seven role-slot IDs; the unchanged
validator passed. This is evidence for one justified standard retry, not
acceptance of the missing earlier response or a counter reset.
Counters after the diagnostic were review 34 / preparation 27 / chapter one 15.
The normal post-replan progress node clears the active unarchived draft; the
original 3,614-character draft remains in the checkpoint history rather than
being manually rewritten or removed. The accepted plan, source goals and
original physical cap remain in force. The authenticated retry then completed
cast/decision alignment and produced tactical version two; new chapter planning
is running. Exact original-response retention at cast failure remains a diagnostic
gap, and the book still has zero archived chapters.
Evidence: `long-r2-accepted-plan-cast-stop.json`,
`long-r2-cast-exact-input-diagnostic.json`,
`long-r2-cast-normal-retry-request.json`,
`long-r2-cast-normal-retry-watch.jsonl`.

The accepted version-two goal source then produced a 3,852-character first
chapter, with a complete passing body fact report. Actual prose inspection
found an inappropriate paper-thickness unit ("薄了一寸") and contradictory
binding-line inspection state. The real quality review rejected a separate
1998-record/1986-binding-date inconsistency, but did not report those two
copyediting defects. Its score of 0.8742857142857142 did not authorize archival.
The automatic revision produced 3,684 characters and retained the unit error.
At 2026-10-01T15:24:35Z, the run stopped with zero archives: physical chapter-one
requests reached 32, with preparation 27 and review 34 unchanged.
The body fact report was unknown; the extraction recovery allowance had
also been exhausted. Neither allowance was reset.
Evidence: `long-r2-version-two-goal-source.json`,
`long-r2-version-two-first-prose-review.json`,
`long-r2-version-two-quality-rejection.json`,
`long-r2-version-two-request-cap-stop.json`.

Fresh production logs traced the last unknown reports to `CreativePause`
raised before provider invocation, not newly malformed model evidence.
The generic extraction exception handler swallowed the trusted budget pause
and caused four model-free failures before reporting recovery exhaustion.
Four focused regressions and one real PostgreSQL/compiled-LangGraph regression
failed on this behavior before repair. Extraction now rethrows control pauses
unchanged to the existing measured-node interrupt handler. Ordinary malformed
evidence still fails closed. Drafts, fact receipts and counters remain unchanged;
this does not grant another attempt to the already exhausted book.
The qualified candidate passed 1,002 backend tests in 96.24 seconds, 74 affected
tests, Ruff, mypy (58 sources) and 13 zero-provider offline cases. Readonly review
reported no blocking findings. Source:
`f707b760d4184ba563f647995221e0d17692a966297512432b83602edca99df3`.
Evidence: `fact-control-red.txt`, `fact-control-pg-red.txt`,
`fact-control-focused.txt`, `fact-control-full.txt`,
`fact-control-code-review.json`, `fact-control-qualification-binding.json`.
This candidate deployed healthy at 2026-10-01T15:47:47Z. Readonly production
verification against the actual 3,684-character body and real chapter meter
now raises `budget_exhausted` directly, with no provider call, no checkpoint
change and no counter change (review 35 / preparation 27 / chapter one 32).
The one prior retrospective editorial diagnostic accounts for review 34 to 35;
it did not grant chapter budget or accept a manuscript.
Evidence: `fact-control-deploy.txt`, `fact-control-live-boundary.json`.
The baseline comparison at 2026-10-01T15:50:35Z found all 26 original chapters
unchanged: `fact-control-original-data.json`.

The single body-only retrospective review returned complete coverage, but
classified the paper-thickness error only as optional and still omitted the
binding-line state contradiction. Most supplied character offsets were wrong,
although the literal quotes had unique positions. Its full prompt, original
response, exact body hash and normally metered request are retained in
`long-r2-body-only-editorial-diagnostic.json`. It is a failed quality probe,
not evidence for introducing an effective independent editor or for archival.
No new body-only production review stage has been added.

Fresh public browser reload after the control-pause release exposed a further
presentation defect: a capped, failed checkpoint was labeled recoverable and
offered continuation. The next candidate derives a read-only budget blocker
only for a failed autonomous checkpoint with a matching trusted tenant/book
session and exhausted actual node budget. The frontend preserves checkpoint
flags but displays the server's reason and offers inspection, not blind retry.
Completed graphs, nonmatching sessions, running commands and remaining budget
are not budget blockers. A real PostgreSQL race test also reproduced a new task
starting during the budget query; the response now rechecks execution and
clears the obsolete blocker. Initial backend/frontend reds and the race red
are retained. The first targeted frontend qualification also exposed a missing
explicit accessible button name; the implementation was fixed rather than
loosening the assertion. At that stage, combined final qualification and
deployment were pending; neither intermediate candidate was published.
Evidence: `budget-snapshot-red.txt`, `budget-snapshot-front-red.txt`,
`budget-snapshot-race-red.txt`.

Readonly rereview found that refreshing every running snapshot would discard
its inactivity marker. A real execution regression reproduced this failure;
the refresh is now restricted to execution that begins during the awaited
budget lookup. The preexisting stale-running marker remains intact. A separate
frontend fixture failure came from using one shared spy for both inspection
and starting writing; the new regression now records start independently and
retains the assertion that inspection never starts writing. Moving the helper
import to module scope also restored the existing 50-line maintenance limit.
Neither failed intermediate candidate was deployed.

The final candidate has 623 source files and SHA-256
`a842a5439dea8ab4ae3395ab6197c474bf1f018dec004b8dc38cff57903011ea`.
It passed 1,008 backend tests in 130.50 seconds, 44 affected tests, Ruff,
mypy (58 sources) and all 13 offline cases with zero provider calls.
The frontend affected suite passed 45 tests and ESLint passed. The first full
frontend run had 179 passes and one 5-second ResearchConsole timeout while
backend qualification ran concurrently. Its original failure log is retained.
The unchanged ResearchConsole file passed all four tests in isolation; the
unchanged full suite passed all 180 tests in 101.69 seconds with one worker
and file parallelism disabled. No timeout or assertion was weakened.
This supports constrained-host scheduling as a contributor, not a proven
application defect. Its production frontend build subsequently passed, but
this intermediate candidate was not deployed.
Evidence: `budget-snapshot-stale-red.txt`,
`budget-snapshot-front-fixture-failure.txt`,
`budget-snapshot-maintenance-failure.txt`, `budget-snapshot-final2-full.txt`,
`budget-snapshot-final2-front-timeout.txt`,
`budget-snapshot-final2-front-isolated.txt`,
`budget-snapshot-final2-front-sequential.txt`.

Before publication, inspection found that the error panel still advised retry
for a retained draft even when retry permission was false. A new false/true
rendering regression reproduced the misleading text (one failure, 16 passes).
The retained-draft message now recommends retry only when retryable is true;
otherwise it states retention only. Normal retry advice and buttons remain
unchanged. The tests were moved into their own describe group after ESLint
correctly rejected the expanded group exceeding its existing 50-line limit.
No static rule was exempted. Readonly review reported no remaining blockers.
The final combined source is
`7946158794a04680a5f21f1e041772c2d98444ea0843e43713218a639807e116`.
Manifest comparison against the 1,008-test backend qualification proves only
WorkflowError.tsx and WorkflowPresentation.test.tsx differ; backend, scripts
and research source entries are identical. Backend evidence is explicitly
bound to its original archive rather than presented as a new run. The current
62-test affected frontend suite, all 182 frontend tests (99.91 seconds),
ESLint and the production frontend build passed.
The pre-switch readonly checkpoint has the same 3,684-character body and
physical counters (preparation 27 / review 35 / chapter one 32).
Evidence: `budget-snapshot-draft-note-red.txt`,
`budget-snapshot-final3-front-lint.txt`,
`budget-snapshot-final4-evidence-reuse.json`,
`budget-snapshot-final4-front-focused.txt`,
`budget-snapshot-final3-book-before.json`.

The exact combined candidate deployed healthy at 2026-10-01T16:36:25Z
(2026-10-02 00:36:25 Asia/Shanghai) with zero active writing leases.
The previous qualified backend/frontend image IDs, not mutable tags, were
retained as the rollback target. Effective deployment configuration and
research image IDs remained unchanged. Local/root and public HTTPS readiness
both returned 200. The initial evidence-binding attempt stopped before
deployment because the rollback evidence was incorrectly named final4 rather
than its actual final2 capture; the corrected binding references the original
file rather than creating a substitute or rebuilding already qualified images.

Fresh public HTTPS browser verification at 2026-10-01T16:37:58Z used normal QA
password login and the actual exhausted `long-r2` book. Its state API reports
budget_exhausted, retryable false and 32/32. Desktop and mobile reload retain
the pause reason; inspection opens the failure panel without a writing request.
There are no continuation/retry writing buttons, no misleading retained-draft
retry advice, no browser errors and no horizontal overflow. Both screenshots
were visually inspected. The existing 0/80 chapters and 0/336,000 characters
remain visible; whole-book export is unavailable and acceptance is still failed.
Counters are unchanged at preparation 27 / review 35 / chapter one 32.
Post-deployment database checks found all 26 original chapter body hashes,
word counts and statuses unchanged, and all four original tenant autonomous
flags unchanged. A direct checkpoint comparison at 2026-10-01T16:43:03Z
confirmed the complete checkpoint hash, ID and 3,684-character draft hash
are identical before/after deployment and browser inspection.
Evidence: `budget-snapshot-final4-qualification-binding.json`,
`budget-snapshot-final4-deploy.txt`,
`budget-snapshot-final4-public-browser.json`,
`budget-snapshot-final4-original-data.json`,
`budget-snapshot-final4-original-flags.json`,
`budget-snapshot-final4-live-preservation.json`.

With the isolated QA-tools container idle, cleanup verified that the explicitly
scoped test-cache directories under its /tmp contained only non-symlink .pyc
files before removing 169,691 generated files (2,276,943,023 bytes). Server disk
free space returned from 2.1 GB to approximately 4.6 GB. No production source,
images, volumes, databases, manuscripts, backup or evidence was deleted.
Evidence: `budget-snapshot-final4-qa-cache-cleanup.json`.

The remaining delivery failure is not a presentation or infrastructure issue:
the actual original/revised prose still demonstrates missed physical-unit
and action-state errors. Overall scoring and the single focused body-only
probe have not established a reliable manuscript-quality gate. Any new
structured editorial workflow requires an explicit architectural discussion
and validation against both these failures and legitimate counterexamples;
no additional production editor stage, budget increase or chapter acceptance
has been introduced. The complete 80-chapter delivery remains incomplete.

Fresh public HTTPS browser login, loaded desktop/mobile layout and reload passed
for the entry-chain release; both screenshots were visually inspected. Export
remains unavailable before archival. Readonly comparison against the isolated
restored baseline at 2026-10-01T15:04:24Z found all 26 original chapters' body
hashes, word counts and statuses unchanged. Evidence:
`plan-milestone-entry-final3-public-browser.json`,
`plan-milestone-entry-final3-original-data.json`.

Fresh public HTTPS browser verification of the history release passed login,
loaded progress, desktop/mobile layout and reload; export remains unavailable
before archival. A readonly post-deployment comparison with the restored backup
again found all 26 original chapters' content hashes, counts and statuses intact.
Evidence: `plan-generation-history-final-public-browser.json`,
`plan-generation-history-original-data.json`, `long-r2-history-live-context.json`.

The latest public HTTPS browser pass used normal QA login and loaded the actual
new `long-r2` workflow on desktop and mobile, with reload and no overflow or
browser errors. Its report explicitly marks manuscript download unavailable
before archival; earlier partial downloads belong to retained previous samples.
Evidence: `editorial-final-long-r2-public-browser.json`.
The subsequent 956-test release also passed a fresh loaded browser run:
`plan-evidence-execution-public-browser.json`. A readonly comparison with the
restored pre-deployment backup found all 26 original chapters' body hashes,
word counts and statuses unchanged:
`plan-evidence-execution-original-data.json`.

Disk free space fell to 1.8 GB during repeated isolated tests. Inspection found
3.2 GB of generated Python caches in the owned QA-tools container. With no test
process running, cleanup verified 122 explicitly scoped directories contained
only non-symlink `.pyc` files, removing 2,818,761,901 bytes of generated caches.
Free space returned to 4.9 GB. No production data, images, volumes, source
archives or backups were deleted. Evidence: `qa-python-cache-cleanup.json`.

Actual completed
book export, closed-ending quality and human
reader parity remain unverified. Existing platform-admin initialization password
does not authenticate; it was not reset. The new QA tenant was enabled through a
strictly scoped operator fixture, not by granting platform-admin permissions.
Browser normal login, desktop/mobile layout, reload and actual partial-book
download passed; final full-book download is still pending.
The production chapter-version mismatch negative returned 409, outsider
chapter read/write returned 404 and ordinary-user gray-release modification
returned 403; original chapter/version/review/body hash stayed unchanged.
This tests a deliberately wrong version, not a genuine concurrent stale editor.
Evidence: `postprocess-addresses-api-write-boundaries.json`.

Server evidence directory:
`/opt/novel-writer/releases/production-20261001/evidence`.
Latest published source:
`4777fe57b52c800265ce8e3607e1ae07ef995e552ace00ba8b2b007772bd2971`.
Backend image: `sha256:717cec3f7948b96a27a50939623c04c808b2a6456954dd0ee43012f65fe5af71`.
Frontend image: `sha256:d33c5f47e19739f7dd8a20619d33bf85793e3a322c66ffc58e9b0ffae4657674`.
Published labels and health were verified; research image IDs remain unchanged.
Immutable source archives identify each candidate separately.

Public HTTPS browser verification also passed normal password login, loaded
workflow state, desktop/mobile layout and reload on the marked R3 book.
Evidence: `character-source-names-public-browser-loaded.json`. Initial
heading-only screenshots were loading placeholders and are not used as
evidence of loaded progress; the browser runner now waits for actual progress
loading to finish before capture.

Implementation details and verification steps:
`docs/superpowers/plans/2026-10-01-production-readiness.md`.

## Source-Bound Editorial Review: October 2

The user reaffirmed execution of the proposed editorial evidence/revision route,
not another goal approval loop. Retrospective probes preserved the actual failed
draft unchanged. A giant ledger returned invalid JSON. A compact ledger detected
action/date contradictions but made the physical-unit defect optional. A combined
measurement/observation response detected all original hard defects but falsely
treated a yesterday/today recollection in the corrected counterexample as one
time frame. Its initially empty normalized findings were an early validation
failure, not a clean raw response; that candidate is rejected.

Separate compact observation and indexed-quantity responses validate against
the same full body. Production validators confirm three known original hard
defects and no issues in the corrected counterexample. This is limited fixture
qualification, not complete semantic coverage or professional-reader parity.
Explicit hyperbole may be physically implausible without being a narrative error,
provided a real nearby nonliteral cue exists. Unknown quantity judgments cannot
authorize archive. All actual retrospective calls remain in the ordinary review
bucket: old long-r2 review=42, chapter:1=32, preparation=27; no limits were changed.

Autonomous reflection commits validated observations, then the complete editorial
receipt, through checkpointed same-node commands before literary evaluation.
Changed body or either prompt invalidates reuse. Each invocation captures actual
template strings before provider awaits, preventing old reports from being labeled
as a newly hot-updated prompt. The autonomous archive guard revalidates the current
receipt and refuses missing, stale or blocking reports before side effects.
Existing goal/fact gates and manual legacy behavior remain intact. Production
editorial requests stay in the physical chapter bucket: two normally, up to four
with one format correction per component; no extra identity or review-budget move.

Readonly review identified durable-checkpoint and template-binding risks. Real
LangGraph regressions reproduced both provider/control-pause loss and the
one-request partial boundary; a mid-request template mutation also failed before
repair. The current source passed all 1,051 backend tests (114.15 seconds),
129 affected tests, Ruff, mypy (60 sources), static gates and 13 offline
cases with zero provider calls. Actual frontend/research manifest comparison
supports reuse of 182/42 prior tests; all 1,007 current distribution assets matched
the previously qualified running frontend.

Deployment completed healthy at 2026-10-02T01:51:03.529331Z
(October 2, 09:51 Beijing time), public readiness 200. All 26 original chapter
body hashes/counts/statuses and four original tenant flags remain unchanged.
The failed long-r2 checkpoint and 3,684-character draft, counters and limits are
identical before/after release. Research services/images are unchanged. Rollback
uses the previous running image IDs, not overwritten mutable production tags.

Fresh marked smoke-r4 `f74f4cb7-45c7-5b03-9067-97b0cdd4fe6c` was created and
started through authenticated API with the same QA identity and original budget.
Public normal login, desktop/mobile loaded state and reload passed with zero
browser errors, no overflow and no browser workflow POSTs. Screenshots were
visually inspected. The new book is still in development with zero archived
chapters, so exports are unavailable and manuscript acceptance is not passed.

Evidence: `editorial-final-qualification.json`, `editorial-final-*.log`,
`editorial-final-evidence-reuse.json`, `editorial-final-frontend-assets-reuse.json`,
`editorial-final-images.json`, `editorial-final-deployment.json`,
`editorial-final-original-preservation.json`, the raw diagnostic reports and
the public browser report/screenshots. Design and next checks:
`docs/superpowers/specs/2026-10-02-editorial-ledger-design.md`,
`docs/superpowers/plans/2026-10-02-editorial-ledger.md`.

The real three-chapter smoke, subsequent complete 80-chapter book, unchanged
exports, closed ending and actual literary quality remain unverified.
# Incremental Quantity Lexer Qualification (2026-10-02)

Candidate source `c0f745290a0c627759c794ce7c68e16a1581b9f8dad70dcdf570314190dcfebb`
has 630 files and is not yet deployed. Three regression failures proved that
`一点五米`, `三分之一米` and `1/2米` were truncated to their final numeric
component. The fix captures whole decimal/fraction amounts; editorial protocol
`editorial-ledger-split-v2` makes old full/partial receipts stale.

Tencent QA gates passed: 51 affected tests, 1,055 full tests (115.59 seconds),
Ruff, mypy (60 sources), 13/13 offline cases and zero provider calls.
The LangChain future-default deprecation warning remains visible; it is not a
test failure. Readonly incremental review found no significant blockers.
Red/green/full/static/harness logs are retained under
`evidence/editorial-numbers-*`. Existing production writing remains uninterrupted;
deployment waits for no active lease.

The real smoke-r4 archived its first chapter, 4,221 characters, after one
revision. Archived receipt body hash matches actual prose. Source-grounded
editorial review detected a work-order number appearing on a note without a
prior copying action, and the revision actually supplied it. Literary review
also repaired stale character forms of address. Both full prose and stored
revision metadata were inspected. This is chapter-level evidence only, not a
passed 3-chapter smoke, completed 80-chapter book or professional literary parity.

## Chapter-2 Identity Repair And Current Release (2026-10-02)

The real smoke-r4 stopped at chapter 2 outline generation, with persisted error
`ValueError('场景出场人物必须引用已准入的character_id')` and chapter budget 4/32.
Readonly reconstruction showed that all seven canonical IDs were absent from
the outline's compact story-bible input, whose character index listed names and
roles only. The generator also caught only `RuntimeError`, so scene identity
`ValueError` bypassed its existing bounded correction loop.

Three red regressions reproduced the missing input and error boundary. Initial
fix qualification passed 1,059 tests, but readonly review correctly rejected it:
the new primary-template placeholder was absent from the existing checkpoint's
immutable prompt snapshot. A real `measured_node` regression reproduced that
compatibility failure. The final fix preserves the old snapshot, appends a
versioned server-authoritative ID/name/role directory, and corrects validation
errors within the original three-attempt limit. Provider errors stay outside the
catch; no IDs are inferred from renamed characters and no admission check is
removed. No request budgets, counters or quota policies are reset or increased.

Current published source:
`caee11ba3877308f3ade48cf0a78b8b1e8ead2affa4a373d4682a8211de1f18a`,
632 files. Tencent qualification: 92 affected tests, 1,060 full tests in 113.12
seconds, Ruff, mypy (60 sources), 13/13 offline cases/provider calls 0.
Unchanged frontend/research manifests reuse 182/42 qualified tests; all 1,007
current frontend build files exactly match the previously qualified manifest
and live output. 38 inherited static assets remain, so complete-directory
equality was not an appropriate preflight assumption; no current asset changed.

Published at 2026-10-02T02:39:00.906276Z (October 2, 10:39 Asia/Shanghai):
backend `sha256:2f2f623eaac5290a3a554c27a5dce82d7db10547c16d800296fea1b39eebbde5`;
frontend `sha256:1345b5969dd9271b6209122817dd2ae77dfb2cc7a7b49a16f55d8fe93c237eea`.
Both are healthy, public readiness 200; research containers keep their original
image and health. Rollback pins the actually previous running images rather
than mutable tags. Effective configuration is preserved.

Post-deploy comparison confirms all existing 31 chapter rows, including the
26 original chapters, four original tenant flags, both old-long/smoke checkpoint
hashes, body hashes, counters and limits unchanged. Deployed-backend reconstruction
with the actual old prompt snapshot now includes all seven canonical IDs.
Same-book normal authenticated retry started run
`91c32fff-9282-4db1-9355-bdb61ca7a902`; its chapter 2 counter advanced from 4 to 5.
Reader disconnection again leaves the background writing job active.
The three-chapter smoke and subsequent complete 80-chapter book remain pending.

Evidence: `outline-identity-red.log`, `outline-snapshot-red.log`,
`outline-snapshot-*.log`, `outline-release-qualification.json`,
`outline-release-build.log`, `outline-release-images.json`,
`outline-release-deployment.json`, `outline-release-original-preservation.json`,
`smoke-r4-first-stop-events.json`, `smoke-r4-archive-receipts.json`.

## Latest Acceptance State (2026-10-02)

Public password login, desktop 1440x1000 and mobile 390x844 reload/archived
chapter display passed at 2026-10-02T02:41:11.339Z, with zero horizontal
overflow, no browser errors and no browser workflow POSTs. Screenshots and the
JSON report are retained as `outline-release-*` evidence. Export was deliberately
not tested as a complete manuscript while only one chapter is archived.

Normal chapter-2 generation and subsequent revisions are in progress. Full
reading of the latest 5,422-character body confirms fixes for missing note
retrieval, material-slip ownership/copying, and an incorrect decades-long
interval described as twenty days. The phone-in-badge wording remains a
specific concern pending final review; this is not a passed smoke test.

The QA tenant has used 20 of its 100 monthly units. After the remaining smoke
chapter, a new 80-chapter run's planning-plus-chapters would be short by two
units. Authorization was requested specifically for that QA tenant's cap
100 to 102. No quota policy, request limit or gate has been changed while
awaiting the answer. Complete 80-chapter output, ending/prose review and whole
manuscript export remain unverified.

## Current Published Budget-Pause Repair (2026-10-02)

This section supersedes the earlier current-release and in-progress statements.
Published source:
`8cafbb1c86b8f79935bdfcad93090015ee284b2463e9a3f0293421112b102965`,
632 files. Deployment was verified at 2026-10-02T03:34:26.599276Z
(October 2, 11:34 Asia/Shanghai). Backend:
`sha256:a75f38b5a4251fa4c7e8e2b289e9aa63b9bd142bbfcf395ff5b003ab75cd08fc`;
frontend:
`sha256:caf88068d30915dfcda01884e7c1ed3a129695bde1b3aa4251954cb3e361c9fb`.
Both are healthy and public readiness is 200. Research images are unchanged.
All 31 chapter rows, tenant flags, old-long/smoke checkpoints, manuscript
hashes, limits and counters match the pre-deployment baseline.

Two real defects were repaired without changing allowances or quality gates:
editorial quote-correction feedback now identifies the rejected paragraph and
bounded quote, and a normal budget-pause interrupt no longer offers ineffective
recovery. Existing persisted interrupts are normalized read-only from actual
session counters. A new execution during snapshot reading clears stale pause
information. Frontend shows the pause reason rather than offering blind retry.

Tencent qualification passed 1,066 backend tests (102.12 seconds), 66 affected
and static tests, Ruff, mypy (60 sources), 185 frontend tests, 24 affected
frontend tests, lint/build and 13 offline cases with zero provider calls.
Unchanged research sources reuse 42 qualified tests. All 1,007 current build
files match the deployed frontend; 38 inherited assets are not current output.
The serializer future-default deprecation warning remains, not a test failure.
Evidence: `budget-pause-final-qualification.json`, `budget-pause-final-*.log`,
`budget-pause-front-*.log`, `budget-pause-final-source-binding.json`,
`budget-pause-final-live-static.json`, `budget-pause-release-live-before.json`,
`budget-pause-release-rollback.json`, `budget-pause-final-deployment.json`.

Fresh public browser verification at 2026-10-02T03:43:28.654Z passed password
login, desktop 1440x1000/mobile 390x844, reload, 4,221 archived characters and
the actual nonretryable 32/32 pause message. Browser errors, horizontal overflow
and workflow POSTs were zero. Screenshots were visually inspected and saved
with the report on the server at mode 0600. The first mobile test selected an
exact accessible name excluding the icon and timed out; selecting the actual
progress tab fixed the test selector without application changes.
Evidence: `budget-pause-final-public-browser.json`,
`budget-pause-final-desktop.png`, `budget-pause-final-mobile.png`,
`budget-pause-final-resource-boundary.json`. No partial export was performed
or counted as a complete-book export.

### Actual Manuscript Blocker

Smoke-r4 is paused at `reflection_node`, chapter 2 used 32/32 requests,
preparation 18/60, chapter 1 used 26/32. Only 1/3 chapters is archived.
Latest chapter-2 draft is 5,506 characters, SHA256
`da7dd7d3acaa592ef8196363ab6cb273556f31f7dd4de730645a653f3cc995fc`.
Normal revision corrected the same-evening timeline from "last night" to
"tonight" and separated institutional ordering from evidence collection order.
Its paid observation component was checkpointed before the quantity component
hit the cap; the current receipt is partial, not full editorial acceptance.

The sentence `手机在工作证里震了一下。` remains a concrete unresolved physical
wording error. Earlier editorial and literary reviews did not flag it, and the
latest observation report also has no findings. That is evidence of a remaining
quality gap, not professional literary parity. The draft remains unarchived;
no manuscript, canon, acceptance decision or request counter was overwritten.
Evidence: `smoke-r4-ch2-second-quality.json` and preserved checkpoint/receipt
hashes in the release baseline and deployment record.

QA monthly usage remains 20/100, with 80 units remaining. Finishing chapter 3
then planning and generating a fresh 80-chapter book is short by two monthly
units. No answer to the prior QA-only monthly-cap request has been received.
The deployed `BudgetLimits.chapter` schema has maximum 32: requesting 48 is
not currently supported by the normal API. Any authorized exception needs a
scoped server-side policy change and requalification, not a direct database
counter edit. A proposed bounded allowance is QA monthly 100 to 102 and only
this three-chapter test's per-chapter 32 to 48, deriving total 200 to 248;
preparation/review limits, consumed counters, other tenants, long-book defaults
and quality gates must stay unchanged. This proposal has not been applied.

The three-chapter smoke has not passed, long-r3 has not been created, and the
80-chapter/336,000-character contract, closed ending, actual prose quality and
unchanged complete-manuscript exports remain unverified. Overall delivery is
not complete.

## Authorized Budget Exception And Current Release (2026-10-02)

The user explicitly approved QA monthly 100 to 102 and only the existing
three-chapter smoke's chapter 32 to 48 / total 200 to 248, with counters,
other tenants, long-book defaults and gates unchanged. That exception is now
implemented using a strict, latest-version system operator grant bound to one
tenant/book and the normal authenticated CAS/idempotent budget API. New-book
`BudgetLimits` still caps chapter at 32. Forged, malformed, revoked, wrong-scope,
over-grant and over-tenant requests are rejected; retained consumption reaches
the new hard cap and still pauses.

Current source:
`fc9ce36b2c7be8422600b9b38fb69ca9c897808a98223220eed99c3c3469aea6`,
637 files. 115 affected/static and 1,085 full backend tests passed in Tencent
QA; full suite took 102.58 seconds. Ruff, mypy (60 sources) and 13 offline
cases/provider calls 0 passed. Unchanged frontend/research sources reuse their
185/42 qualified tests; all 1,007 current static files match running output.
Readonly review approved the final candidate. The first same-name prompt edit
failed real old-snapshot recovery regressions and was not published; v2
editorial/copyediting template names now work with the preserved old snapshot.
Actual deployed-backend reconstruction rejects the old partial receipt.

Published deployment verified at 2026-10-02T04:26:54.970820Z
(October 2, 12:26 Asia/Shanghai). Backend:
`sha256:2d396fd99a7398b446a57194698217f662a50d6ee9cff9e8239bbaf3c455bf3e`;
frontend:
`sha256:f6798300b0f1076ef8ea9cf2f9b05258b6dfbecfd70b4be9cc37683ea575e129`.
Both are healthy, public readiness 200, research images unchanged. All 31
chapter rows, tenant flags, sessions, checkpoints and bodies were preserved
before resource changes. Rollback pins the actually previous running images.

Approved monthly change and immutable operator grant were applied at
2026-10-02T04:28:07.438440Z. Monthly usage remains 20/102, remaining 82.
Smoke counters are unchanged at chapter 1=26, chapter 2=32, preparation=18;
chapter limit is 48 and total 248. Review/preparation/search allowances are
unchanged. A second normal CAS retained the original nullable review default
without changing its effective allowance 44; final session budget version 5.
Exact comparison at 04:31:13Z confirmed only approved resource/config/version
changes; all other tenant flags, old-long limits/counters and both checkpoints
are unchanged. No quota ledger, body, acceptance or counter was overwritten.

Same-book normal retry started run `714a024a-83c9-4ec6-a5f9-2f26e2bfa226`;
chapter 2 advanced from 32 to 33 and background execution remained active after
reader disconnection. Only 1/3 chapters is archived so far. Real-model repair
of the phone/badge error remains pending; the prompt and unit/integration
checks alone do not prove semantic repair or professional literary parity.
The 80-chapter book, ending/prose checks and complete exports remain pending.

Evidence: `budget-grant-qualification.json`, `budget-grant-qualified-*.log`,
`budget-grant-source-binding.json`, `budget-grant-live-before.json`,
`budget-grant-rollback.json`, `budget-grant-deployment.json`,
`budget-grant-resource-applied.json`, `budget-grant-preservation.json`,
`budget-grant-snapshot-red.log`, `semantic-containment-red.json`.

## Real Recovery Result And Remaining Blocker (2026-10-02)

The actual v2 review caught the phone/badge containment defect, required
normal revision and did not archive on its high literary score. Revision 5
changed the phone to the coat pocket. A subsequent fresh review found the
material-slip front/back contradiction; revision 6 repaired it and retained
the prior correction. Inspection of the real diff also confirmed the taxi
drop-off and supervisor's source of knowledge were clarified.

Latest chapter-2 draft has 5,572 characters, SHA256
`1e5539b580d7cdbd9fe4e4ebf921c5e030dc4779b73abf7a56ac51e390a0bd88`.
Fresh complete editorial receipt is valid and body-bound, with no findings;
server literary decision, original-goal acceptance and body fact report passed.
These checks were reconstructed read-only in the actual creative runtime
context, not from an unprojected checkpoint or a fabricated provider response.
There are still two optional prose clarifications. Human readership and
professional web-novel parity have not been verified.

At 2026-10-02T04:49:46Z (12:49 Asia/Shanghai), normal execution paused at
`persist_node` before its chapter-summary request, because chapter 2 had
consumed 48/48. Its final paid request completed the literary review. No
summary request was sent beyond the authorized cap; all real counters,
review receipts and final prose are preserved. Only 1/3 chapters and 4,221
characters are archived. No further retry or grant change has been made.

The normal remaining archive/postprocessing requires at least five requests:
summary, cumulative story state, reader state, narrative threads and character
updates. The proposed next bounded allowance is only this smoke book's
chapter 48 to 56 / total 248 to 272, with all counters and quality gates intact.
This proposal is not authorized or applied. The existing hard operator-grant
ceiling is still 48, and any further extension needs scoped code/policy
qualification followed by normal CAS. Other tenants and new/old long-book
defaults stay unchanged; monthly usage is still 20/102.

Fresh public desktop/mobile browser proof at 2026-10-02T04:56:10.047Z
confirmed normal login/reload, the real 48/48 pause, hidden ineffective retry,
zero horizontal overflow, browser errors and workflow POSTs. Screenshots were
visually inspected. Complete export was not attempted on this partial book.
The three-chapter smoke, 80-chapter/336,000-character novel, ending/prose quality
and unchanged complete exports remain unpassed. Overall delivery is incomplete.

Evidence: `semantic-containment-first-green.json`,
`smoke-r4-authorized-cap48-final.json`,
`smoke-r4-authorized-cap48-gates.json`,
`smoke-r4-authorized-cap48-request-boundary.json`,
`smoke-r4-authorized-second-monitor.json`,
`budget-grant-cap48-public-browser.json`,
`budget-grant-cap48-desktop.png`, `budget-grant-cap48-mobile.png`.

## Direct 80-Chapter Acceptance Started (2026-10-02)

The user explicitly corrected scope drift and authorized direct full-book
execution. The incomplete three-chapter smoke is no longer a prerequisite.
Its artifacts, counters and 48/48 pause are preserved; the proposed 48 to 56
exception is not authorized or applied. No further smoke retry is performed.

Current canonical acceptance novel is
`9e422832-63de-5a02-ba81-476885bbe79b` (`long-r3`),
`生产验收20261001·潮汐账本·长篇R3`. It was created and started through normal
authenticated public HTTPS APIs with the existing QA identity at
2026-10-02T05:04:55Z (13:04 Asia/Shanghai). Contract is exactly 80 chapters,
336,000 characters, original 10% tolerance, so acceptable actual total is
302,400 to 369,600 characters. Normal budget is chapter 32, preparation 60,
review 660 and total 3,280, with empty counters at creation. No operator
extension, quota reset, replacement identity or forced acceptance is used.

Before starting, both current application images were healthy and labeled
with qualified source `fc9ce36b2c7be8422600b9b38fb69ca9c897808a98223220eed99c3c3469aea6`.
Public readiness was 200; all 31 existing chapter rows matched their baseline;
zero writing leases were active. Existing monthly usage was 20/102, remaining
82, against at least 81 for planning plus the 80 chapters. No monthly change
was required.

Run `cca6c72f-d32c-4293-bcd2-79788da7a1d4` was actually running after its
stream reader disconnected, with preparation counter 1 and no interrupts.
Subsequent diagnosis, qualified deployment and normal recovery must continue
this same 80-chapter book. The checks are complete archival, actual scale,
causal/character continuity, core payoffs, closed ending, actual prose quality,
unchanged authenticated complete exports and browser behavior. Starting the
run or passing individual chapters is not overall completion.

Evidence: `long-r3-preflight.json`, `long-r3-start.json`,
`long-r3-status.json`, `long-r3-first-monitor.json`.
# Full-Book Fourth-Volume Recovery (2026-10-02)

The canonical 80-chapter book remains
`9e422832-63de-5a02-ba81-476885bbe79b`, not the suspended smoke sample.
The first actual failure was fourth-volume reference validation at preparation
23/60: payoff IDs were renamed with prefixes and a chapter-76 arc was referenced
in chapter 80. All first 60 slots remained checkpointed.

A scoped reference-catalog correction passed 1,091 backend tests, static/type
checks and 13 offline scenarios, then deployed on Tencent at zero active leases.
Source SHA-256:
`661501235426424a62765efd9edde4eb74d12a527bbf75b19ca02f55cbbc3f51`.
Public readiness is 200; existing chapters, sessions, records, budgets, flags
and retained checkpoints matched before/after deployment. The normal retry
continues this same book as run `7c59700f-b550-4cd2-9bd4-d0ade7e382e1`.

At 2026-10-02T05:42:35Z actual state is fourth-volume generation,
preparation 24/60 and 0/80 archived. Validation and all budget gates remain
unchanged. Live real-provider recovery, full manuscript, closed ending, complete
exports and reader-facing quality are still unverified, not passed.

At 2026-10-02T05:47:12Z the catalog-only recovery failed again: no arc-boundary
error in the last result, but 13 prefixed payoff aliases remained. The follow-up
fix excludes macro reference labels from autonomous model input, retaining all
narrative fields and original persisted blueprint/slot identities. It does not
normalize IDs, weaken validation or change budgets.

Current qualified release is
`115ee27e250e336cd49a8fa115bdbcdd45db8f4f4e64bf267485be3ef86951f5`,
with 1,093 full backend tests and 36 affected/static tests passed. Deployment
at 2026-10-02T05:56:41Z preserved all captured production data and checkpoints.
The same book continues as run `9ebc4356-d91e-4336-b011-070c8b228635`,
preparation 27/60 and 0/80 archived. This supersedes the previous current
source identity; actual full-book acceptance remains open.

The real fourth-volume recovery subsequently produced all 80 valid candidate
slots with exactly 336,000 planned characters, preserving the original first
60 slots and blueprint. This was not archived prose. Complete semantic review
then identified five planning contradictions but paused on one incorrect
adjacent event index in its evidence report.

Current qualified deployed source is
`192998001ad9995b652a5f4c0d1b98575023057349a6e37bd7acd3e0a860b931`.
It preserves raw review version 1 and only repairs an existing same-chapter
adjacent event pointer when the unchanged literal quote occurs exactly once
in the whole bound context; all five issues and false classifications remain.
1,103 full backend tests, 78 affected/static checks and 13 offline scenarios
passed. Deployment at 2026-10-02T06:22:22Z preserved captured production
data/checkpoints and passed public readiness. Production receipt at 06:24:28Z
verified normal system version 2 and the existing bounded repair, not forced
acceptance.

The same book is running as `1376c629-2465-437e-961e-0aad251c33f4`,
preparation 31/60 at 06:24:54Z, fresh volume planning and still 0/80 archived.
Repair-candidate review, full prose quality, closed ending and complete exports
remain unverified. No counters, quotas, budgets or author constraints were reset.

Latest actual state at 2026-10-02T06:31:09Z: the same book is paused on
`plan_consistency`, preparation 34/60, accepted plan version 0 and 0/80 archived.
The original five contradictions were resolved and three review categories
now pass. Two cross-layer duplicate events remain: second-copy delivery at
70/80 and water-debt relabeling at 78/80. The complete-book acceptance still
fails; source `19299800` remains healthy, not a complete production delivery.

The ordinary bounded whole-plan repair was consumed and preserved. Existing
explicit arc-only repair cannot address initial unaccepted chapter/volume
text defects. A named-proposal, evidence-limited cross-layer repair extension
has been proposed, with unchanged budgets, scale, identities and acceptance
checks; no implementation or bypass has been performed for that extension.

The user subsequently approved the extension. It is now implemented and
deployed as source
`97d10cd85eba19324d7bdaade49e3c5198b4a49ea7bf97d9b400e30f89361bb0`.
1,141 full backend tests, 107 affected/static checks, Ruff, mypy and 13
zero-provider offline cases passed on Tencent QA. Only six backend files
changed; frontend/research source and qualified evidence remain applicable.
The actual candidate replay restricts edits to six later-event string leaves,
preserving the first 79 slots, scale and ending contract. The initial repair
retains all existing acceptance gates and the consumed full-regeneration limit.

Deployment preserved the captured 31 existing chapters, all tenant flags,
sessions/records, budgets and retained checkpoint data. Readiness returned 200.
The named original candidate was submitted through normal public HTTPS as run
`987dd783-244f-4a5c-8c0a-7a02aad43e3b`, running at review 1/preparation 34,
accepted version 0 and still 0/80 archived. Actual patch and fresh semantic
acceptance remain pending. No quota grants, counter resets or gate bypasses.

Actual production receipts at 2026-10-02T07:16:32Z proved the patch changed
only five authorized text leaves, preserving the first 79 slots, scale and
ending contract. Fresh proposal `fde83839-1033-4178-8057-9d18604defe9`
passed all four complete semantic-review criteria and was normally accepted
as plan version 1. This supersedes the pending planning status above.

The first chapter's cast binding then paused on `cast_coverage`, before any
prose was archived. Nine admitted characters and six role slots are present.
The old cast implementation discarded failed model results before storage,
so the exact mismatch remains unknown, not assumed to be an ID typo.
A narrow failure-retention fix is qualified as source
`594c2c2656435d75cad3c3a7c42709e8c258b97fcc3600c8bc07020384eb1f18`:
1,142 full backend tests, 17 focused/static tests, Ruff, mypy and 13 offline
cases passed. It retains rejected raw payloads and identity inputs, propagates
the unchanged coverage gate and applies no partial duties.
The manuscript remains 0/80; professional-quality and export acceptance remain open.

The qualified failure-retention source was deployed at
2026-10-02T07:29:19Z with all captured production data, flags, budgets and
checkpoint sets preserved, readiness 200. Same-book normal retry
`c58fd0fd-4851-477f-80d1-d5a1ef629536` produced a valid real cast binding
covering all nine characters and six role slots. No guessed ID mapping or
partial assignment was applied. The original discarded response remains
unrecoverable; the successful retry does not prove a permanent provider fix.
At 07:33:11Z the first chapter is actively generating prose, chapter:1 10,
preparation 35 and review 1, accepted plan version 1 and no new interruption.
Actual archived prose remains 0/80, not a completed book.

At 2026-10-02T07:38:07Z, the first chapter stopped on fact review after two
semantic repairs. The unchanged 3,470-character draft's report demanded solving
unresolved document clues outside the five supported fact predicates. A
versioned v2 judge prompt/extraction v5 clarified assertion-only scope, retaining
all canonical and evidence checks. Source `4bed8155` passed 1,147 full backend
tests and was deployed with preservation at 08:03:21Z. A real fresh provider
recheck passed the same draft, retaining recovery 2/2 and all existing limits.

That recovery exposed a revision-source mismatch: fact review had staged the
candidate as current body while its restored proposal still referenced the
previous draft. This is repaired without rewriting the old proposal or relaxing
the stale-source guard. Only an identical staged candidate, unchanged goal and
freshly reverified current-version complete fact pass can create one new
source-bound proposal; normal confirmation still enters independent reflection.
Empty-ledger restoration, model calls, body changes and counter resets are
forbidden during rebinding.

Current qualified deployed source:
`2c556facc1af289ff21a463114c5eae6d7d5219baa08e504a5d40c9187a2debe`.
1,162 full backend tests, 71 affected/static checks, Ruff, mypy and 13
zero-provider offline cases passed. Deployment at 2026-10-02T08:34:53Z preserved
captured production data, flags, budgets and checkpoints; readiness 200.
Research services unchanged; rollback pins the previous `4bed8155` live images.
Actual same-book run `ab27efb2-0b4c-45b3-8190-ed57590829eb` entered independent
first-chapter reflection, retaining exact body and recovery history. Evidence:
`long-r3-revision-staging-production-receipt.json`.
Still 0/80 archived; complete manuscript, professional-quality comparison,
closed ending, tenant-isolated exports and final end-to-end acceptance are open.

Latest actual boundary at 2026-10-02T09:00:11Z: the same book paused on the
unchanged chapter:1 limit 32/32, still 0/80 archived. Independent review
identified and model revisions corrected archive/work-sheet ID mixing and
page-sequence problems. A negative author prohibition was instead treated as
unknown solely because feedback/sales are absent, causing an unnecessary
refactor. No unknown goal result was converted to pass.

Current draft is 3,705 characters, SHA-256
`94ebaca6e7a21f5486411558960a74fbcb33b53042b8a7e06253b8f7d176b09d`;
fact pass and complete editorial receipt exist, but fresh main quality/goal
review does not. The editorial seal-ink timing finding remains unresolved,
not claimed to be an independently proven physical impossibility.
Preparation 35, review 1, chapter:1 32; fact/extraction recovery 2/2 and
quality recovery 3 remain intact. Active leases 0, public readiness 200,
original chapter content and tenant flags unchanged at 09:03:48Z.

Continuation needs a separate bounded spending/recovery authorization.
Proposed, NOT applied: only this acceptance book's chapter ceiling 32 to 40
(whole-book ceiling 3,280 to 3,920), plus one audited additional first-chapter
quality repair preserving cumulative counters. No global setting, tenant
flag, monthly quota, old book or gate bypass may be used. Negative-constraint
evidence and recovery semantics must be addressed before normal continuation.
This is not a completed production delivery or 80-chapter acceptance.
## Budget Allocation Update (2026-10-02)

The user approved optimizing the budget mechanism and renewed same-book
verification. The unexecuted 32-to-40/3920-total proposal is superseded.
The current marked 80-chapter long-r3 keeps total3280, preparation60,
review660, search0 and preparation_search0.

Qualified/deployed source
`3217d27676510566f0b26ac82045c8045185abc90676f72b7aecba1ed43218da`:
1184 full backend tests, 59 final focused tests, Ruff, mypy 60 sources and
13 zero-provider harness cases passed. Existing frontend/research source
was unchanged. Production readiness200; original data and environment
hashes preserved before activating the book policy.

An authenticated, scoped, CAS/idempotent allocation-only API enabled
`elastic_v1` only for long-r3. Chapter32 is a soft threshold; provisional
hard cap64, future-chapter reserve24, review/repair cycle holds12/20.
These scheduling values are not yet calibrated against an 80-chapter book.
All physical calls now enforce the whole-book total; failed/unknown provider
outcomes remain charged and carry sanitized receipts. Autonomous retries
do not reset fact, extraction or quality recovery counters.

Normal same-book retry crossed chapter:1 request32 to33 while preserving the
exact3705-character draft and recovery2/2/3. A fresh main review passed all
goals but required an editorial patch; normal generation and independent
re-review continued, then stopped at46 calls on quality-purpose accounting.
Full80 chapters, complete manuscript quality, ending,
exports and final isolation acceptance remain unverified.

Detailed current evidence and implementation status:
`docs/superpowers/plans/2026-10-02-elastic-budget.md`.

### Approved Progress Repair (2026-10-02T13:35:27Z)

The user approved action-state review and progress-budget improvements.
Sourceba7879d8 is qualified with1264 backend tests, Ruff/mypy and13 offline
cases/provider0, deployed on Tencent with fresh immutable rollback pins
and unchanged data/environment baselines. Readiness200. Other books,
tenant flags, original chapter rows and all physical limits are preserved.

Owner-only progress_v1 activation is idempotent, sessionv5; book3280,
chapter1 hard72/default64, spend99 unchanged at activation. Local cycles
use15 preferred/9 minimum only when current complete goal acceptance and
new grounded issue evidence establish real progress. No unchanged-body
refill, recovery reset, whole-chapter fallback or acceptance bypass.
Post-archive state calls use the existing book review pool.
Editorial v3 adds complete ordered action-candidate checks, stable object
states and grounded contradiction pairs; this improves structural coverage
without claiming exhaustive semantic or human-quality proof.

Normal run8148dc15 has generated only the glove sentence repair:
"她把褪下的右手手套戴回去". Exact3846 characters,
SHAda3f317741f4108f5aaee16192d00503ce8bf32b833537dd615b68d1fd38f653.
Revision history8 preserves seven prose repairs plus one prior fact
confirmation. At13:35:27Z still0/80 archived, independent review in
progress, chapter66/72. Full80 ending, manuscript quality, exports and
tenant-isolation acceptance remain UNVERIFIED.

### Production Feedback Follow-Up (2026-10-02T14:09:50Z)

The first real progress run rejected six invalid action-predecessor reports,
then safely stopped0/80 at chapter71/72/book107. This is failed real
acceptance despite passing isolated tests; provider completion is not review
validity. Historical usage is retained, including the first review's57159
reasoning tokens. No manuscript/goal acceptance was forced.

Source61cfc56a corrects action-link feedback, preserves strict checks, pauses
after two invalid reports, and assigns new independent review requests to
the existing660-call review pool. Generation/revision/fact checks retain
chapter accounting. It provides a single body/protocol-bound migration
of the old unavailable editorial proposal, preserving exhausted old counts.
Whole3280 and chapter72/64 caps are unchanged; no old spend is transferred.

Qualified1274 tests, Ruff/mypy60 sources,13 offline cases/provider0;
deployed on Tencent with fresh rollback pins, full data/environment baseline
preservation and readiness200. Backend8ca63636/frontend614bf9e8.
Normal run50f62609 is active in fresh reflection, same3846-character body
da3f3177, new counterreview2, chapter71 unchanged. Still0/80 archived.
Independent quality, ending, full manuscript, exports and final acceptance
remain UNVERIFIED. Current detailed evidence and work status are in the
elastic-budget plan and server `long-r3-progress-final-*` artifacts.

### First Independent Archive (2026-10-02T14:27:03Z)

Fresh goal/quality event15871 passes on exactda3f3177, score0.914286.
Editorial v3 covers81 paragraphs/41 action checks, findingsnone. An
archive-stage fact revalidation exposed one remaining pool-routing issue;
it safely exhausted chapter72 before archive, rather than skipping facts.
Source0f12290d fixes only opted-in persist_node's independent acceptance
accounting, passed1275 tests/Ruff/mypy/13 offline provider0 cases, and was
deployed with fresh rollback and unchanged data/environment checks.
Backend3fa29848/frontend0171ed8d, readiness200.

Normal run132cef66 actually archived chapter1:3846 characters, exact
SHAda3f317741f4108f5aaee16192d00503ce8bf32b833537dd615b68d1fd38f653,
review_statuspassed and preserved8 revision entries. Archived v3 editorial
and complete passed v5 fact receipts bind the same body. Postprocessing
succeeds in review pool and closes the hold with4 unspent calls; chapter1
remains72, no refund. Original31 chapters, flags and other sessions unchanged.
Same80-book now1/80, second-chapter generation active. Budget remains3280,
first hard72/other64; full book/ending/exports acceptance is NOT complete.

### Authorized Goal Repair Continuation

The user's2026-10-02 "yes" supersedes the pending-authorization status above.
The owner API grants only long-r3 chapter1: one additional goal repair,
hard72, total3280 and all historical counters unchanged. Controlbd885baf is
one-use, review/body/contract-bound and idempotent; no global/fact quota reset.
Source6a42690c deployed after1234 full tests, Ruff/mypy and13 offline cases.
Fresh deployment baselines preserve business data/environment and research;
public ready200. Normal runc0295a42 generated only a17-character net increase
to establish the required institution/water-fee books. Current3845-character
bodyad107369 has a complete passing v5 fact receipt. Independent review,
first archive and full80 acceptance are still pending, not passed.

Fresh final result at2026-10-02T12:14:09Z supersedes pending review:
event15835 passes all original goals, score0.922857, but the new complete
editorial receipt blocks on a grounded glove action-state contradiction
(p29 only right glove removed, p50 both donned again). The same text already
existed before the goal patch and prior review missed it. Normal automatic
repair limit stops event15837; the approved single extension is consumed.
STOPPED,0/80 archived; chapter63/72, book99/3280, active holdremaining9.
All99 provider receipts complete; original31 rows, tenants and other book
budgets preserved, monthly23/102, public ready200 and active leases0.
No blind retry, additional authorization, cap/reset or bypass was applied.
Full production/80-chapter acceptance has FAILED to complete, not passed.

### Purpose Accounting And Real Cycle Boundary

Source490c499d was qualified with1195 backend tests, Ruff/mypy and13
zero-provider cases, then deployed with fresh production data/environment
checks unchanged. Normal retry preserved the3828-character draft
SHA-256 `1515ab2a9e71d37bee156e4a2c3d45fcb217820876893c1866b20a7758d206ce`
and aggregate fact/extraction/quality2/2/5. A separate receipt classifies
4 completed prose repairs and1 same-body fact confirmation; the effective
quality maximum remains5, not increased. The configured reflection value3
was not actually forwarded into this runtime; prior descriptions of3 as
the effective maximum were inaccurate.

Actual fresh review consumed2 calls, then paused before revision at
chapter48 because the remaining16 cannot fit an ordinary18-call repair.
This is safe failure, not successful end-to-end acceptance. Still0/80
archived. A15-call local-only path is under isolated qualification: only
short, freshly goal-reviewed patch candidates qualify; one generation
attempt, no full fallback, all fact/editorial/main review gates intact.
No total, chapter hard cap, tenant or monthly limit is raised.

### Local Repair Verification

The15-call local-only path was qualified/deployed (sourcebd3a9e59,
1205 tests). Actual call49 failed patch validation and safely preserved the
draft without a full rewrite. Clarified the grouped-evidence prompt and
retained sanitized validation categories; sourcec32f0593 passed1208 tests
and was deployed with all fresh baselines intact. Actual call50 confirms
the model still omitted the primary evidence from its anchor. The same
hold remains active with13 calls; no refill, refund or recovery reset.

The current continuation uses existing server-owned paragraph IDs rather
than asking the model to copy an exact original anchor. All original patch
scope and independent review guards remain. Source5b5ea0af is qualified
with1214 backend tests, Ruff/mypy and13 offline cases/provider0; actual
archive/full80 acceptance remains open.

### Final Current Result (2026-10-02T11:42:38Z)

Source5b5ea0af is deployed and readiness200. The real paragraph-selected
patch changed only the two linked front-side labels to back-side labels.
The exact3828-character draft has SHA-256
`085a7e46758d34b48e6172770641b024a0c251a4d36bb559619223b3372c9e10`.
Fresh v5 fact review passed after one normally charged extraction recheck;
historical recovery is semantic2/extraction3/quality5, without resets.

Fresh review event15816 scores0.922857 and has no editorial must-fix finding,
but fails original eventch1:must:1 because the specified archive institution
is not explicitly established in the prose. The full institution name is
absent; earlier reviewers passed this event, so review consistency remains
a separate risk. Application code does not turn this failed result into pass.
Five actual prose repairs (plus one distinct fact confirmation) are spent;
event15818 stops before archive. Current state is STOPPED,0/80 archived.

Actual spend93 of3280 (preparation35/review1/chapter57); chapter ceiling64
leaves7, the existing15-call hold has6 remaining and was never replenished.
All93 requests retain token receipts; missing usage0. Monthly quota remains
23/102, remaining79. Original31 chapter rows, tenant flags and other books'
budgets remain unchanged; active leases0. No extra grant/retry is applied.

Budget implementation/regression/deployment is verified. Full80-book
quality, ending, exports and final acceptance have NOT passed. Continuing
past this bound requires a separately authorized first-chapter goal repair
and sufficient scoped cycle capacity, not a global limit raise or reset.
Current complete evidence and proposed control:
`docs/superpowers/plans/2026-10-02-elastic-budget.md`.

### Subsequent Authorized Progress (2026-10-02T15:26:29Z)

The owner-authorized progress_v1 mechanism preserves original limits and
historical spend. Independent editorial/main/archive acceptance now uses
the existing review660 pool; generation/revision/fact repair remains
chapter-scoped. Normal run132cef66 actually archives chapter1:3846
characters, review_statuspassed, quality0.914286, exact reviewed SHA
da3f317741f4108f5aaee16192d00503ce8bf32b833537dd615b68d1fd38f653.
Complete editorial v3 and passed fact-v5 receipts bind those same bytes.
All8 revision entries remain. Postprocessing completes without refund;
original31 chapter rows, tenant flags and other books remain unchanged.

Chapter2's normal repair corrects two grounded time/count errors. Its
3606-character draft411492d4 and one repair history are retained. A real
glove-state report exposed server false rejection when a paragraph's
primary-object action check names a different object. Corrected pairing
uses the full original paragraph catalog, retaining real quotes, chronological
evidence, coverage and all must-fix gates. Source49b3b383 qualifies1279
tests, Ruff/mypy and13 offline cases/provider0, then deploys with immutable
rollback, all data/environment baselines equal and ready200.

Normal retry982a935f is running in the same original80/336000 book.
Archive1/80; preparation35/review19/chapter1=72/chapter2=12. No alternative
book, manual manuscript/checkpoint edit, cap increase, refund or closed-hold
refill substitutes for full acceptance. Full80 chapters, ending, exports,
tenant isolation and human-quality validation remain UNVERIFIED.
Current evidence: `long-r3-progress-first-archive*.json`,
`long-r3-progress-full-source-pair-*`; see the elastic-budget plan.

### Subsequent Semantic Review Risk

Fresh review accepted the glove evidence and triggered a normal one-line
repair. A later report confused comparison sheets with original-sheet
records; equal identifiers alone cannot establish equal objects. Normal
cancellation preserved the latest already-completed third revision:
3888 characters/SHAf3ad0535/history3,151 counted calls, archive1/80.
150 completed token receipts exist; one interrupted call remains usage-
unknown, not refunded or assigned fabricated usage.

The follow-up's sourcefefb978d4 qualifies1283 tests, Ruff/mypy60 sources and
13 provider0 cases. It clarifies source identity, observation time and unknown
initial state, and provides bounded rejected-report context for the existing
second correction attempt. This does not prove model semantic reliability:
deployment and new real review/archive verification remain pending here.
Full80-book production acceptance remains UNVERIFIED.

Exactfefb978d4 is deployed and verified at2026-10-02T15:56:27Z,
backend6f87d7a0/frontend97e35f08. Data/checkpoint/counters and all service
environment hashes remain equal to the fresh paused baseline; ready200.
Normal retry74e9ef0b is running on the same3888-character chapter2.
At15:57:41Z archive1/80, preparation35/review29/chapter1=72/chapter2=16.
Fresh semantic review/second archive and full80 acceptance remain open.

### Current Verified Progress (2026-10-02T16:14:05Z)

Normal run74e9ef0b archives chapter2:3888 characters, exactSHAf3ad0535,
review_statuspassed/quality0.894286, fresh goal acceptance, complete editorial
v3 (104 paragraphs/39 actions/findings[]) and complete passed fact-v5 gate.
All3 revision entries retained, DB/API text identical, normal postprocessing
complete. Previous32 rows/flags/other sessions are unchanged;33 rows now.

Same original80-book2/80 and7734 characters, chapter3 in reflection_node;
preparation35/review38/ch1=72/ch2=16/ch3=9. No cap/old-count reset or alternative
book. Main review retains optional identifier-count/referent issues; these
remain content-quality risks, not proof of an error-free manuscript.
Full80-book/ending/aggregate word range/exports/human-quality acceptance is
still UNVERIFIED. See second-archive audit/verification and source-identity
current-status/watch private receipts.
