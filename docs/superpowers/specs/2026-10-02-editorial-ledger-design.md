# Source-Bound Editorial Review

## Authorization And Outcome

The user explicitly reaffirmed execution of the previously proposed editorial
evidence, revision and re-review route, with deployment on Tencent only.
This is a scoped addition to the existing reflection/revision/archive pipeline,
not a replacement for literary evaluation or the full 80-chapter acceptance.
The accepted book contract remains 80 chapters / 336,000 characters / +/-10%.

## Evidence And Choice

The retained real 3,852-character draft has three independently read defects:
an implausible single-sheet thickness difference, contradictory binding-line
inspection state, and a binding date preceding the ledger's content year.
The existing high aggregate score missed two of these. Body-only scoring also
missed the action error and made the unit error optional. A giant evidence ledger
detected the defects but returned invalid JSON. Compact observation pairs detected
action/date errors but still downgraded the unit error.

Use separate compact-observation and indexed-quantity calls. The server
enumerates common length/time/temperature expressions; the model must classify
each expression and provide source evidence for figurative readings. Literal
implausible measurements become blocking issues independently of model priority.
Keep literary evaluation for voice, scenes, pacing and reader effect.

The combined quantity+observation call actually misidentified yesterday's
recollection as today's inspection; its empty normalized findings had been caused
by an earlier qualifier-validation failure, not a clean raw report. That candidate
is explicitly rejected. Separate the already-valid compact observation report
from focused quantity classification and combine only against the same full body.
Retain the failed combined report.

The corrected counterexample has legitimate paper-stack measurements, an explicit
joke, restored gloves and different-time recollections. The separate compact model
report returned no contradictions and focused quantity classification distinguishes
the expressions correctly. A prototype validator
wrongly rejected a real figurative cue because the quote also contained the
measurement. Production validation must accept that cue while rejecting bare
measurement quotes and unrelated distant evidence. These probes establish a
candidate method, not professional-writing parity or complete defect coverage.

## Interfaces And Trust

- `editorial_ledger.py`: `measurement_catalog(content)`, `validate_editorial_report`
  and `editorial_issues(report, content)` use the existing paragraph/source-span API.
  Strict typed reports require exact ordered paragraph and measurement coverage,
  literal ledger quotes, chronological paired contradiction evidence, valid
  nearby figurative qualifiers, enum values and nonempty reasons. Unknown quantity
  judgments fail closed; physical units are lexical recall, not a physics engine.
- Physical plausibility remains separate from narrative interpretation: a
  supported figurative expression may be physically implausible without blocking.
  Its nearby qualifier must include an explicit supported Chinese/English cue.
- `editorial_review.py`: `advance_editorial(llm, content, cached)` commits one
  component per graph invocation; the first receipt is a validated observation
  cache, the second a complete review. `review_editorial` is a diagnostic helper.
  Both return receipts
  bound to the body SHA256, protocol version and both prompt SHA256. Cache reuse requires
  revalidation of the actual report. Each component permits one format correction,
  each request uses `max_attempts=1`. Normal review uses two requests, maximum four
  on component contract corrections. All production requests stay in the existing
  reflection-node chapter bucket.
- `creative_editorial_review` is a checkpoint state channel. The existing trusted
  request seeder strips all client-supplied `creative_` keys. No quality-gate field
  supplied by a client is an editorial receipt.
- Reflection runs editorial review for autonomous books, merges evidence-bound
  issues into the existing quality gate and returns checkpointed same-node commands
  between components and before literary generation. Paid observations and full
  receipts survive provider errors and real control pauses. Changed prose
  invalidates the receipt. Each invocation captures both actual template strings
  before any await; generation and receipt use that same pair, never a digest
  reread after a hot update.
- Autonomous persistence requires a fresh validated receipt with no blocking
  findings. Missing/stale/blocked receipts route back to reflection before database
  writes. Store the actual receipt in chapter review metadata; clear the transient
  channel after archive. Existing manual nonautonomous behavior is unchanged.

## Safety And Verification

No forced acceptance/canon, quota resets, budget increases, alternate identity,
unchecked fallback, unlimited retries or original manuscript edits. The exhausted
long-r2 run remains a retained failure. New smoke/full-book runs require a materially
qualified new release, not a reset of that failed book.

Use red-first tests for exact evidence validation, false-positive counterexamples,
cache invalidation, unknown judgments, quality-gate blocking, trusted input and
archive refusal. Run all backend tests with actual PostgreSQL in the server QA
container, static gates and offline harness. Reuse unchanged frontend/research
evidence only with exact manifest comparison. Deploy the qualified source with
zero active leases and pinned image rollback. Verify public login, desktop/mobile
state, original data and budgets, then run fresh manuscript smoke and the complete
80-chapter acceptance. Complete export, ending and actual prose quality remain
required; model reports alone do not establish equivalence to professional writers.
