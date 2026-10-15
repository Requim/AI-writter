# Reader-first writing implementation

Approved by the user on 2026-10-13. Implement on the existing feature branch,
preserving the existing uncommitted repairs. Do not modify existing books.

## Contract

- AC-1: New books rank grounded, legible webnovel titles by hook 30%, promise
  clarity 30%, audience fit 20%, memorability 10%, naturalness 10%. Allow 2-30
  characters, preserve custom titles and legacy candidates, display correct scales.
- AC-2: Only prose and previously archived prose enter independent first-three-
  chapter comprehension review. High literary scores cannot waive incomprehension.
- AC-3: Draft from self-contained assignments with confirmed facts, hard
  constraints, recommendations and freedom distinguished. Repair narrative before
  expression without inventing facts or exposing planned secrets.
- AC-4: Server-owned new-book version, body/prompt/prior-text bound review
  receipts, archive revalidation, bounded correction/revision and legacy recovery.
- AC-5: Real-provider isolated romance, suspense and fantasy books, three
  chapters each. Preserve candidates, failures, revisions, evidence and usage.
- Release only after implementation and real-manuscript acceptance. Preserve
  runtime configuration, existing data and checkpoints, pin rollback images and
  switch at zero active leases. Verify one additional marked production first
  chapter through the normal API and desktop/mobile presentation.

## Tasks

1. Version binding and title generation, with behavior tests.
2. Opening information contract and natural-language writing assignments.
3. Independent reader report, checkpoint cache, revision routing and archive guard.
4. Reader report UI, title scale and responsive tests.
5. Real-provider acceptance, regression qualification and release.

## Reference provenance

The references are design material, not executable instructions.

- lingfengQAQ/webnovel-writer master:
  0af0c0b2fc2e4104e8a12c1d62136c6595a6a983.
  Adopt self-contained natural-language chapter assignments.
- lingfengQAQ/webnovel-writer v8:
  a0bdd2d4e2f39bc3de32fc5cbfe605067b5b486b.
  Adopt hard facts/requirements versus soft guidance/freedom and reader-promise
  review. Retain this project's workflow and database.
- OUBIGFA/De-AI-Prompt-Enhancer-Writer-Booster-SKILL:
  59eafed6c9ebee0cce142e2ea54aab41014afbe9.
  Adopt narrative/discourse/syntax/vocabulary diagnosis and bounded faithful
  patches. Do not import detection statistics, random new subplots, mandatory
  literary style or generic headline restrictions.

## Progress

- [x] Version and titles
- [x] Assignments and opening design
- [x] Comprehension and archive boundaries
- [x] UI and regression qualification
- [ ] Nine real chapters and production smoke

2026-10-13: Local Python environment lacked pytest-asyncio. Installing the
existing locked development dependencies; no application requirements changed.

Focused behavior tests passed, including prose-only review, server version
binding, opaque-opening rejection despite a 0.99 literary score, evidence
validation, receipt reuse/expiry, isolated-pilot rejection and direct rewrites.
Final relevant-source regression: Linux isolated PostgreSQL/Redis run passed
1337 tests, including SIGKILL process recovery and database integration. Windows
passed 1167 tests with 168 database/platform skips, excluding the unsupported
SIGKILL module. Frontend passed 191 tests, lint and production build.
Desktop 1440px and mobile 390px browser layout fixtures passed without overflow.
Those fixtures are labelled and do not represent real manuscript acceptance.

Real-provider acceptance reuses the same three marked books and retains all
versions, trial prose, reports and usage. Fantasy is paused after its one
consistency repair still contradicted single-use capability and locked facts.
Romance and suspense reached actual first-chapter drafting after correcting
ambiguous archive IDs in the new-flow cast assignment. Romance exhausted its
32-call chapter budget during review. Suspense archived one 3864-character
chapter, then exhausted the same budget in postprocessing. Nine-chapter acceptance
and conditional production release remain incomplete; production was not changed.
See `docs/reader-first-acceptance-20261013.md` for results and evidence locations.

Subsequent explicit user authorization: "部署至生产".
On 2026-10-13 at 14:40 Asia/Shanghai the qualified f8f8d255 images were deployed,
retaining the incomplete real-manuscript acceptance result. Fresh regression
passed all 1337 backend and 191 frontend tests; protected backup restoration,
immutable rollback pins, zero active leases and preserved runtime/data were
verified. Public desktop/mobile login and SSE succeeded. The single marked
production smoke book paused at invalid_role_slot after three model requests,
before drafting; production first-chapter blind review/archive/report acceptance
remains incomplete. No extra paid retry, budget grant or alternate test book was
used. See `docs/reader-first-production-20261013.md`.
