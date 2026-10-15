# Editorial Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and repair source-grounded manuscript contradictions before autonomous archive without replacing literary evaluation.

**Architecture:** A strict compact report is validated against server paragraph/measurement catalogs. Body- and prompt-bound receipts survive checkpointed review and are required at archive; existing revision and request metering remain authoritative.

**Tech Stack:** Python, Pydantic, existing LLMService, LangGraph, PostgreSQL, pytest; existing Tencent Compose deployment.

**Spec:** `docs/superpowers/specs/2026-10-02-editorial-ledger-design.md`

## Global Constraints

- 80 chapters / 336,000 characters / +/-10%.
- Tencent deployment only; no local application server.
- Preserve original data, service configuration and request allowances.
- No forced acceptance/canon, quota resets, unapproved budget increases,
  alternate identity, unchecked fallback or unlimited retries.
- On October 2, 2026 the user approved QA monthly 100 to 102 and only smoke-r4
  chapter 32 to 48 / total 200 to 248. Counters, other tenants, long-book defaults,
  preparation/review limits and all quality gates must remain unchanged.
- Functions at most 50 nonempty lines / nesting 3; long prompts in template files.
- No commits mixing this scoped work with the existing uncommitted delivery.

### Task 1: Source-Bound Report

**Files:** Create `writter_back/application/editorial_ledger.py`;
create `writter_back/tests/test_editorial_ledger.py`.

**Interfaces:** `measurement_catalog(content: str) -> list[dict]`;
`validate_editorial_report(raw: object, content: str) -> dict`;
`editorial_issues(report: dict, content: str) -> list[dict]`.

- [x] Write red tests: literal single-page thickness blocks; valid stack and
  explicit joke do not; unknown status fails closed; missing/duplicate catalog
  IDs, fake quotes, distant figurative qualifiers and unordered contradiction
  pairs are rejected. Expectations use hand-derived literal paragraph/offsets.
  Example:
  ```python
  from tests.test_editorial_ledger import BODY, report
  from application.editorial_ledger import editorial_issues, validate_editorial_report
  issues = editorial_issues(validate_editorial_report(report(), BODY), BODY)
  assert issues[0]["priority_action"] == "must_fix"
  ```
- [x] Upload source and run the focused tests in the existing Tencent QA container;
  confirm failures are missing behavior, not test syntax.
- [x] Implement strict typed report validation with `source_catalog/source_span`.
  Require matching ordered coverage, bound literal quotes, paired action/date
  evidence and nearby non-bare figurative evidence. Derive must-fix issues from
  literal implausibility; unknown reports cannot yield accepted receipts.
- [x] Run focused and static tests, retain red/green evidence with source hash.

### Task 2: Bounded Review And Cache

**Files:** Create `writter_back/application/editorial_review.py`;
create `writter_back/application/prompts/templates/reflection/editorial_ledger_v1.txt`;
create `writter_back/application/prompts/templates/reflection/editorial_quantities_v1.txt`;
create `writter_back/tests/test_editorial_review.py`.

**Interfaces:** `review_editorial(llm: LLMService, content: str, cached: object) -> dict`;
`advance_editorial(llm: LLMService, content: str, cached: object) -> dict`;
`editorial_receipt_valid(receipt: object, content: str) -> bool`;
`editorial_archive_ready(state: dict, content: str) -> bool`.

- [x] Write red tests for unchanged-source cache reuse, changed body/prompt/report
  rejection, unknown/invalid report and exactly one bounded format correction.
  ```python
  from tests.test_editorial_review import EditorialLLM
  from tests.test_editorial_ledger import BODY
  from application.editorial_review import review_editorial, editorial_receipt_valid
  receipt = await review_editorial(EditorialLLM(), BODY, None)
  assert not editorial_receipt_valid(receipt, "纸页略薄。")
  ```
- [x] Implement separate qualified observation and quantity prompts using
  paragraph/measurement
  catalogs; no future plans/goals/scores. Each call is structured generation with
  `max_attempts=1`; a second attempt includes the actual validation error.
  Cache identity is protocol/body/template SHA256, and report revalidation is
  mandatory. Unknown quantities raise `StructuredOutputInvalidError`. Capture both
  template strings before await; receipts use that exact digest. Each component
  permits one correction, so normal review is two calls and maximum four.
- [x] Validate both retained real raw diagnostic report pairs using production code,
  without additional provider requests. Preserve the prototype false-negative
  evidence rather than rewriting it.
- [x] Run focused tests and bind actual results to the current package.

### Task 3: Workflow And Archive

**Files:** Modify `application/schemas/agent_state.py`,
`application/agents/reflection_node.py`, `application/agents/persist_node.py`;
create `tests/test_editorial_workflow.py`; extend scoped trusted-input tests.

**Interfaces:** Add `creative_editorial_review: Optional[Dict]`; consumers use Task 2.

- [x] Write red tests using real node functions: autonomous high literary score
  still routes to revision on source-bound defects; cached valid receipt survives
  later literary failure; stale/missing/blocked receipts cannot archive; accepted
  receipts are retained in chapter metadata and cleared for next chapter.
  ```python
  from application.agents.persist_node import persist_node
  from tests.test_editorial_workflow import state_for
  command = await persist_node(state_for(), {"configurable": {}})
  assert command.goto == "reflection_node"
  ```
- [x] Integrate editorial review before literary review only for autonomous mode;
  merge issues through the existing server quality gate. Checkpoint the receipt
  after each component through same-node checkpoint commands, before literary
  generation; keep it even on physical-budget pauses and provider errors.
  Keep node size limits via focused
  finishing helper, not new exemptions.
- [x] Add archive readiness before any goal/fact/summary/database work. Missing,
  stale or blocking receipt routes to reflection; manual legacy behavior remains.
  Store receipt under chapter `user_decision.editorial_review`; clear after archive.
- [x] Prove the actual workflow seeder discards client-injected receipt data and
  reflection requests remain in the physical chapter bucket.
- [x] Run affected tests, real PostgreSQL full suite, Ruff, mypy, static and offline
  harness; fix actual regressions before image build.

### Task 4: Release And Manuscript Acceptance

**Files:** Update this plan and `docs/production-readiness-20261001.md`;
only extend existing acceptance runner if a new qualified run kind is needed.

- [x] Readonly code review of exact diff, fix findings and rerun affected gates.
- [x] Bind current source manifest to backend qualification and unchanged
  frontend/research evidence; capture rollback image IDs before image build.
- [x] Deploy healthy with zero active leases; public desktop/mobile login/reload,
  current source labels, original chapter/body hashes and tenant flags must match.
- [ ] Inspect actual full-book text/review/revisions under normal identity and
  budgets. The user's October 2 correction supersedes the smoke prerequisite:
  execute the 80-chapter acceptance directly, retaining the failed smoke.
- [ ] Check complete export, 336,000-character tolerance, ending closure, continuity,
  prose/rhythm/character quality; never mark the overall goal complete on partial
  chapters, scores or a safe pause.

## Current Evidence

Qualified/published source:
`4777fe57b52c800265ce8e3607e1ae07ef995e552ace00ba8b2b007772bd2971`,
630 files. Actual Tencent gates: 1,051 backend tests in 114.15 seconds,
129 affected tests, Ruff, mypy (60 sources) and 13 offline cases/provider calls 0.
The 126 frontend and 38 research manifest entries exactly match prior qualified
source `7946158794a04680a5f21f1e041772c2d98444ea0843e43713218a639807e116`;
all 1,007 current frontend distribution files match the prior running image.
Reuse the 182 frontend and 42 research tests without claiming a new full run.

Deployment health verified at 2026-10-02T01:51:03.529331Z, public readiness 200.
Actual original 26 chapters, four tenant flags and the failed long-r2 checkpoint,
3,684-character body, limits and counters are unchanged. The only retrospective
charges were real review requests, ending at review=42/chapter:1=32/preparation=27.
Readonly review required/fixed durable component checkpoints and immutable
template binding. Red tests for both risks and the one-request partial boundary
remain as evidence.

Fresh marked smoke-r4 `f74f4cb7-45c7-5b03-9067-97b0cdd4fe6c` was created and
started through normal authenticated API, same QA identity and unchanged budget.
Public password login, desktop/mobile loaded state, reload, no overflow/errors
and no browser workflow POSTs passed; export is unavailable at zero chapters.
The real smoke and full 80-chapter manuscript gates are still pending.

### Incremental Quantity Lexer Qualification

Candidate source `c0f745290a0c627759c794ce7c68e16a1581b9f8dad70dcdf570314190dcfebb`
retains the same 630-file scope. Three red cases demonstrated truncation of
Chinese decimals, Chinese fractions and ASCII fractions; ASCII decimals already
passed. The scoped fix preserves complete amounts and increments the editorial
protocol to `editorial-ledger-split-v2`, invalidating old full and partial receipts
without altering request allowances. Tencent qualification: 51 affected tests,
1,055 full tests in 115.59 seconds, Ruff, mypy (60 sources), 13 offline cases with
zero provider calls. Readonly incremental review found no significant blockers;
finite lexical coverage and the existing cost of re-review remain limitations.
This candidate is not yet published: the existing real smoke is kept running.

The running smoke has actually archived chapter 1, 4,221 characters, after one
normal revision. Stored body/review hashes agree. The first editorial pass caught
a missing action copying the work-order number onto the note; actual revision
added the action and a fresh review accepted it. Literary review also corrected
a stale surname/address and clarified the supervisor's restricted work scope.
Full-body reading and archived metadata were inspected, not just model scores.
Only 1/3 chapters has been observed archived, so no smoke or whole-book pass is
claimed. Raw receipts and revision history remain in server evidence files.

### Actual Chapter-2 Identity Failure

Smoke-r4 stopped at chapter 2 outline generation with checkpoint error
`ValueError('场景出场人物必须引用已准入的character_id')`; chapter 2 used 4/32
requests and no rejected outline/body was archived. Readonly reconstruction of
the actual server planning view showed zero of seven canonical character IDs
in the compact story bible, whose index only included name and role.

Three red tests reproduced missing identity mapping, failure to correct a bad
scene ID, and the unbounded-error-classification gap; a provider-origin
`ValueError` propagation counterexample already passed. The scoped fix supplies
the complete server-authoritative ID/name/role map outside the compact bible and
catches validation-origin `ValueError` in the existing three-attempt correction
loop. Provider errors remain outside that catch, and scene admission checks,
existing IDs and allowances are unchanged. Candidate source
`e95dfb88d73a42ec76a658ba6fa931bfd22b9bd9b68d790673035914b3cc0c89`
has 631 files and includes the prior quantity fix. 91 affected tests, Ruff and
mypy passed; full qualification and release are pending.

Readonly review found a real compatibility gap in that first candidate:
existing runs bind the old template from `state.prompt_snapshot`, so adding a
placeholder to the new primary template did not fix standard checkpoint retry.
A measured-node red test reproduced this. The final implementation keeps the
old snapshot and appends `chapter/character_identities_v1.txt` outside it; this
does not rewrite existing character IDs or copy hidden profile data into the
identity map. The restore test passed and readonly re-review approved the fix.

Final source `caee11ba3877308f3ade48cf0a78b8b1e8ead2affa4a373d4682a8211de1f18a`
has 632 files: Tencent QA passed 92 affected tests, 1,060 full tests in 113.12
seconds, Ruff, mypy (60 sources), 13/13 offline cases/provider calls 0. Unchanged
126 frontend and 38 research entries reuse their qualified evidence; all 1,007
current distribution files match the prior qualified manifest and running
frontend. The image also retains 38 inherited old static assets; the initial
all-files-equality preflight assertion was too broad, not evidence of changed
current output.

Deployed healthy at 2026-10-02T02:39:00.906276Z. Backend image:
`sha256:2f2f623eaac5290a3a554c27a5dce82d7db10547c16d800296fea1b39eebbde5`;
frontend:
`sha256:1345b5969dd9271b6209122817dd2ae77dfb2cc7a7b49a16f55d8fe93c237eea`.
Public readiness returned 200. All existing 31 chapter rows (26 original),
four original tenant flags, both checkpoints, bodies, limits and counters match
the pre-deployment record. Actual old-snapshot reconstruction in the deployed
backend confirmed all seven canonical IDs are present. The same smoke-r4 was
resumed through normal authenticated retry: run
`91c32fff-9282-4db1-9355-bdb61ca7a902`, chapter 2 counter advanced 4 to 5; no
reset, increased allowance, identity replacement or forced acceptance.
Whole-smoke and full-book acceptance remain pending.

### Current Public UI And Chapter-2 Manuscript Evidence

Fresh public password login at 2026-10-02T02:41:11.339Z passed on desktop
1440x1000 and mobile 390x844, including reload and actual archived chapter-1
prose. Browser errors and workflow POSTs were empty; horizontal overflow was
zero. The export control is enabled with one archived chapter, but no complete
book export is claimed or performed. Evidence:
`outline-release-public-browser.json`, `outline-release-desktop.png`,
`outline-release-mobile.png`.

After the normal retry, chapter 2 generated 4,984 characters, then a
5,155-character fact revision. Its actual literary/editorial review requested
repair of a note left at the father's table but reused at the office, and an
unexplained material-slip copy appearing in the badge. The next normal revision
has 5,422 characters, SHA256
`b96e96b42f35ff61c4a9335323f29b70cfd2be25d7d9f1d5de811147f89664e7`;
full-body reading confirms explicit retrieval/transfer/copying actions and
changes the 1998-2003 to 2026 interval from "twenty days" to "over twenty years".
It is still undergoing review, not yet archived or accepted. Reading also
identified a phone described as vibrating inside the badge; its subsequent
review and final disposition remain unverified.

Actual QA tenant usage is 20/100 for October 2026, with 80 remaining units.
Chapter 2 is already reserved, chapter 3 will consume one, and a new complete
80-chapter book needs one planning plus 80 chapter units. This leaves a two-unit
shortfall. Specific authorization to change only that QA tenant's monthly cap
from 100 to 102 was requested; no answer or quota change has occurred.
Physical per-chapter limits and quality gates are unchanged. Do not start a
supposedly complete long-book acceptance by hiding this resource constraint.

### Current Published Repair And Unpassed Smoke

Latest source is
`8cafbb1c86b8f79935bdfcad93090015ee284b2463e9a3f0293421112b102965`,
632 files, deployed healthy at 2026-10-02T03:34:26.599276Z
(October 2, 11:34 Asia/Shanghai). Backend:
`sha256:a75f38b5a4251fa4c7e8e2b289e9aa63b9bd142bbfcf395ff5b003ab75cd08fc`;
frontend:
`sha256:caf88068d30915dfcda01884e7c1ed3a129695bde1b3aa4251954cb3e361c9fb`.
Public readiness is 200; research images and all 31 chapter rows, tenant flags,
old-long/smoke checkpoints, bodies, limits and counters are preserved.

Real editorial quote-validation failures now identify the rejected paragraph
and bounded quote in the existing one-correction feedback. Real normal
budget-pause interrupts are nonretryable; public snapshots read-only normalize
legacy persisted pause data using actual counters. A newly running execution
clears stale pause information. The frontend hides ineffective retry and
provides the pause-reason action. No allowance or quality gate was changed.

Red regressions covered quote feedback, the real PostgreSQL/LangGraph paused
snapshot, unrelated/remaining-budget counterexamples, execution-start race,
live pause event and frontend recovery controls. Full backend initially exposed
a 53-line function exceeding the existing 50-line constraint; extracting the
unchanged stale-execution calculation fixed it without an exemption.
Final Tencent gates: 66 affected/static tests, 1,066 backend tests in 102.12
seconds, Ruff, mypy (60 sources), 24 affected and 185 full frontend tests,
lint/build, 13 offline cases/provider calls 0. The frontend manifest is unchanged
from its actually qualified candidate; research reuses 42 tests. All 1,007
current deployed static files match qualified output. Readonly review approved
the scoped changes.

Fresh public browser proof at 2026-10-02T03:43:28.654Z covers password login,
desktop 1440x1000/mobile 390x844, reload, 4,221 archived characters, actual
32/32 pause message, hidden ineffective retry and zero workflow POSTs, errors
or horizontal overflow. Both screenshots were visually inspected and retained
on the server at mode 0600. No complete export was attempted while incomplete.
The mobile test's initial exact-name selector missed its icon-bearing tab;
the corrected selector passed without an application change.

Actual smoke-r4 is now paused, not running or completed: only 1/3 chapters is
archived, chapter counters are 26 and 32, preparation is 18. Latest chapter 2
has 5,506 characters, SHA256
`da7dd7d3acaa592ef8196363ab6cb273556f31f7dd4de730645a653f3cc995fc`.
Normal revision corrected the same-evening "last night" error and clarified
institutional versus evidence-collection ordering. The latest observation
component is preserved, but the next quantity call stopped at 32/32, so its
receipt is partial. The remaining phone-in-badge sentence was missed by earlier
editorial/literary review and the latest observation report; it remains an
explicit quality defect, not an accepted chapter.

QA monthly usage is still 20/100. The planned remaining smoke and fresh
80-chapter planning/chapter operations are short by two units. A proposed
exception is QA monthly 100 to 102 and this three-chapter test's per-chapter
32 to 48 (derived total 200 to 248). Current deployed schema caps chapter at
32, so any approved exception needs a scoped policy implementation and
requalification, then normal versioned budget update. Do not directly edit
counters or silently extend other tenants, long-book defaults, preparation,
review or quality gates. No increase has been authorized or applied.

Evidence: `budget-pause-final-qualification.json`,
`budget-pause-final-source-binding.json`, `budget-pause-final-live-static.json`,
`budget-pause-final-deployment.json`, `budget-pause-release-live-before.json`,
`budget-pause-release-rollback.json`, `budget-pause-final-public-browser.json`,
`budget-pause-final-desktop.png`, `budget-pause-final-mobile.png`,
`budget-pause-final-resource-boundary.json` and the corresponding red/green/full
logs. Task 4 manuscript and complete-book checks remain unchecked.
Long-r3 has not been created. Overall delivery is not complete.

### Authorized Bounded Budget Exception

The user answered "yes" to the exact resource request on October 2, 2026.
Use an immutable system-origin operator grant bound to the existing tenant and
novel, not a global default or client-supplied permission. Keep new-book
`BudgetLimits` at 32. The existing versioned/idempotent budget endpoint may
accept up to 48 only with a valid matching operator grant, and must still check
the tenant total cap and consumed counters.

- [x] Prove real PostgreSQL/API red regressions for a granted extension,
  ungranted/wrong-scope/forged/revoked/malformed grants, exact allowance, retained
  counters, idempotent replay, CAS and the hard new cap.
- [x] Implement the smallest trusted operator-grant check; qualify, review and
  deploy with current rollback IDs and zero active writing leases.
- [x] Apply QA monthly 100 to 102 and the smoke-only audited grant, then update
  chapter 32 to 48 through the normal authenticated CAS budget API. Preserve
  all existing manuscripts, checkpoints and counters.
- [ ] Retain the unfinished smoke and its evidence. The user's October 2
  correction suspends further smoke execution: run full 80-chapter acceptance
  directly without increasing the smoke cap.

### Authorized Release And Real Recovery Evidence

Current published source:
`fc9ce36b2c7be8422600b9b38fb69ca9c897808a98223220eed99c3c3469aea6`,
637 files. Tencent qualification passed 115 affected/static tests, 1,085 full
backend tests in 102.58 seconds, Ruff, mypy (60 sources), 13/13 offline cases
with zero provider calls. Unchanged frontend/research manifests reuse 185/42
qualified tests; all 1,007 current frontend assets match deployed output.
Readonly review approved the final scope.

The first prompt-only candidate did not fix restoration: actual `measured_node`
red regressions proved that old snapshot contents still reused the old partial
receipt and copyediting rules. New `editorial_ledger_v2.txt` and
`copyediting_v2.txt` names resolve that without rewriting the frozen snapshot.
The original v1 contents are preserved. The editorial receipt binds the actual
v2 template. Paired action/date evidence rules and all archive gates remain
unchanged. Real retained provider output, body SHA256
`da7dd7d3acaa592ef8196363ab6cb273556f31f7dd4de730645a653f3cc995fc`,
had no findings at the impossible phone/badge paragraph p126. That semantic
failure remains a real-model regression, not a passing unit-test claim.

Deployment verified at 2026-10-02T04:26:54.970820Z
(October 2, 12:26 Asia/Shanghai). Backend:
`sha256:2d396fd99a7398b446a57194698217f662a50d6ee9cff9e8239bbaf3c455bf3e`;
frontend:
`sha256:f6798300b0f1076ef8ea9cf2f9b05258b6dfbecfd70b4be9cc37683ea575e129`.
Both are healthy; public readiness 200; research images unchanged.
All 31 chapter rows, tenant flags, both sessions/checkpoints/body hashes and
counters were preserved before applying the approved resource change.
Restoration with the actual old smoke snapshot now activates both v2 rules
and rejects reuse of its old partial receipt.

Authorized resources were applied at 2026-10-02T04:28:07.438440Z.
QA monthly usage stays 20, cap is now 102, remaining 82, unlimited false.
System-origin operator grant
`f33f29e0-d167-4e7b-a931-ed4cd07b42dc` binds only tenant
`46f40f90-d27f-4f2e-b770-40cbc73e7ac5` and smoke book
`f74f4cb7-45c7-5b03-9067-97b0cdd4fe6c`. Normal authenticated CAS budget update
set chapter 48 / total 248, retaining all counters. A second normal CAS update
preserved the original `config.budget.review=null` default rather than its
temporarily serialized explicit 44; effective review allowance remains 44.
Final budget version is 5. Exact post-change comparison confirmed only the
approved monthly cap and smoke budget/config/version changed; old long,
other tenant flags, original manuscripts and both checkpoints are unchanged.

Normal same-book retry started run `714a024a-83c9-4ec6-a5f9-2f26e2bfa226` at
2026-10-02T04:31:13Z. The reader disconnected while background writing remained
active; chapter-2 consumption advanced 32 to 33 with no reset. This proves
budgeted recovery, not manuscript completion. The real smoke, actual semantic
repair, complete 80-chapter book and whole exports remain pending.

Evidence: `budget-grant-red.log`, `budget-grant-snapshot-red.log`,
`semantic-containment-red.json`, `budget-grant-qualified-*.log`,
`budget-grant-qualification.json`, `budget-grant-source-binding.json`,
`budget-grant-live-before.json`, `budget-grant-rollback.json`,
`budget-grant-deployment.json`, `budget-grant-resource-applied.json`,
`budget-grant-preservation.json` and the current smoke status record.

### Actual Semantic Repair And Second Resource Boundary

The normal authorized recovery caught the previously missed phone/badge
relation in body `da7dd7d3acaa592ef8196363ab6cb273556f31f7dd4de730645a653f3cc995fc`.
The v2 editorial finding was `must_fix`, and the server gate required a patch
despite a high literary score. Normal revision 5 changed only that paragraph
to place the phone in the coat pocket. Revised body had 5,518 characters,
SHA256 `9b110dc090d31b56ce6888fbcab236b029ede503317a2ef3397ef54521ae036c`.
No manual manuscript or acceptance update was used.

Its fresh review then found a separate real contradiction: the material-slip
signature was on the back, but the sheet was shown front-up. Normal revision 6
changed that presentation to back-up, kept the phone repair, clarified the
taxi drop-off and supplied the supervisor's visible source of knowledge.
The actual diff was inspected. Final draft is 5,572 characters, SHA256
`1e5539b580d7cdbd9fe4e4ebf921c5e030dc4779b73abf7a56ac51e390a0bd88`.
Its full, valid editorial receipt has no findings and binds v2 prompt SHA256
`870737f4a999d1c35f7f3b9906db92df9b41ac05591894c9cd9660823b14b6e2`.
Fresh server goal acceptance, literary gate and body fact report passed.
Read-only reconstruction used the real creative node scope, persisted author
configuration and original prompt snapshot; raw checkpoint state alone is not
the runtime goal-source context. Two low-priority prose clarifications remain
optional in the literary report. This is not proof of professional parity or
absence of all unknown defects.

At 2026-10-02T04:49:46Z (October 2, 12:49 Asia/Shanghai), the same run reached
`persist_node` and paused before sending the chapter-summary request:
chapter 2 was already at 48/48. The request ledger contains exactly 48
chapter-2 reservations; its final paid request is the completed literary review,
not a summary. The last checkpoint and paid review are preserved. No retry,
counter reset, grant increase or alternate book was used after this pause.
Only chapter 1, 4,221 characters, is archived; progress is still 1/3.

Normal archive/postprocessing still needs at least five physical requests:
chapter summary, cumulative story state, simulated reader state, narrative
threads and character updates. Actual formatting/metadata repairs may need
more, so this is a lower bound, not a completion guarantee. The next proposed
bounded exception is only smoke-r4 chapter 48 to 56 / total 248 to 272;
it is NOT authorized or applied. Monthly cap stays 102, usage 20, and the
new-book/old-long chapter cap remains 32. Extending beyond 48 would require
explicit human authorization, scoped policy requalification and normal CAS,
not editing counters or bypassing quality gates.

Public browser proof at 2026-10-02T04:39:46.594Z covered normal login,
desktop/mobile and running recovery. Fresh proof at 04:56:10.047Z then covered
the actual 48/48 pause, normal password login/reload, desktop 1440x1000 and
mobile 390x844, hidden ineffective retry, zero horizontal overflow, browser
errors and workflow POSTs. Both screenshot pairs were visually inspected.
No complete-book export was attempted or passed.

Evidence: `semantic-containment-first-green.json`,
`smoke-r4-authorized-semantic-first.json`,
`smoke-r4-authorized-cap48-final.json`,
`smoke-r4-authorized-cap48-gates.json`,
`smoke-r4-authorized-cap48-request-boundary.json`,
`smoke-r4-authorized-second-monitor.json`,
`budget-grant-public-browser.json`,
`budget-grant-cap48-public-browser.json` and the corresponding desktop/mobile
screenshots. Long-r3 is still not created. Task 4 manuscript/full-book/export
checks and overall production delivery remain incomplete.

### User-Directed Full-Book Priority

After the user identified scope drift and said to begin, full-book acceptance
was started directly at 2026-10-02T05:04:55Z. Current canonical novel is
`long-r3` / `9e422832-63de-5a02-ba81-476885bbe79b`, exactly 80 chapters and
336,000 characters, original 10% tolerance. The existing identity and normal
chapter 32 / total 3,280 budget are used. Run
`cca6c72f-d32c-4293-bcd2-79788da7a1d4` continued after reader disconnection.
The smoke remains at 48/48, not completed, not retried or extended. No new
identity or counter reset was used. Subsequent fixes/recovery must target the
same full-book novel, not a series of replacement samples.

The canonical execution checklist is now the "Direct Full-Book Execution"
section of `2026-10-01-production-readiness.md`. Full-book manuscript, ending,
continuity, actual prose quality and complete exports are still pending.

## Self-Review

The specification's trust, retry, false-positive, archive, metering, deployment
and book-level conditions map to Tasks 1-4. Interfaces are consistent. The plan
uses existing scoped worktree and inline execution already requested by the user;
it does not request another authorization loop or create a separate task.
