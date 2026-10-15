# Conversation Workbench, Assets and Basic RAG

Approved scope: persistent novel conversations, selectable versioned assets, keyword
retrieval with provenance, and an explicit reviewed chapter adoption boundary.
Keep the original studio and automatic generation available. Script/video generation,
vector retrieval, reranking and graph expansion remain TODOs.

## Delivery Contract

- AC-1: conversations and partial generated replies survive reload; stop/retry never
  silently starts a second paid task.
- AC-2: full replies or selected text become editable versioned assets. Copying to
  another novel retains provenance without linking subsequent edits.
- AC-3: current setting assets and accepted chapter paragraphs are retrievable with
  exact source/version/offsets. Drafts require explicit references. Hard settings
  remain present independently of top-k selection.
- AC-4: only explicit adoption changes chapters, progress and memory. Review applies
  to a content version; conflicts, duplicate adoption and concurrent original
  workflows cannot overwrite official work.
- AC-5: tenant boundaries apply to every conversation, asset, job and source.
- AC-6: existing work remains usable; mobile/desktop layout and failure states work.

## API Contract

All endpoints below live at `/api/v1/novels/{novel_id}/workbench`.

- `GET /overview`: `{novel, conversations, assets, chapters, legacy_sources, enabled}`.
- `POST /conversations`: `{title?: string}` -> conversation.
- `GET /conversations/{id}`: `{conversation, messages}`.
- `PATCH /conversations/{id}`: `{title: string}` -> conversation.
- `POST /conversations/{id}/messages`: `{text, intent, reference_ids: string[],
  chapter_index?: number, target_chapter_id?: string}` and Idempotency-Key -> job.
- `GET /jobs/{id}`: job; `GET /jobs/{id}/stream`: SSE `snapshot` frames containing job.
- `POST /jobs/{id}/stop`, `POST /jobs/{id}/retry`: job.
- `POST /assets`: `{title, kind, content, source_message_id?: string}` -> asset.
- `PATCH /assets/{id}`: `{title, kind, content, expected_version}` -> asset.
- `GET /assets/{id}/versions`: immutable asset versions.
- `POST /assets/{id}/copy`: `{target_novel_id, expected_version}` -> copied asset.
- `POST /assets/{id}/review`: `{expected_version}` -> reviewed asset.
- `POST /assets/{id}/adopt`: `{expected_version, acceptance:
  "reviewed"|"with_issues"|"unreviewed", chapter_index?: number,
  target_chapter_id?: string, expected_chapter_version?: number}` -> adoption receipt.
- `GET /search?q=...&before_chapter=...`: `{hits, available}`.
- `POST /reindex`: backfill current official sources.

Kinds: `idea`, `world`, `character`, `outline`, `chapter`, `reference`.
Intents: `discuss`, `setting`, `outline`, `write`, `continue`, `rewrite`, `review`.
Chapter indices are zero based, matching existing chapter endpoints.

Conversation: `{id,title,created_at,updated_at}`.
Message: `{id,conversation_id,role,content,status,intent,sources,job_id,created_at,
retrieval_available?,previous_attempts?}`.
Job: `{id,conversation_id,message_id,status,content,error,sources,intent,
chapter_index,target_chapter_id,created_at,updated_at,retrieval_available,
previous_attempts}`.
Asset: `{id,title,kind,content,version,source_message_id,provenance,review,
adopted_chapter_id,created_at,updated_at}`.
Source: `{source_type,source_id,title,version,start,end,text,score}`.
Errors use HTTP status and `{code,message}` where a user action is possible.

## Execution Ledger

- Baseline: current feature branch contains extensive user work. Work in place;
  do not reset, stash, commit unrelated changes, or copy an outdated HEAD worktree.
- Task 1 complete: persistence, scoped asset operations, keyword retrieval and backfill.
- Task 2 complete: persisted streaming jobs, quota, snapshot context, stop/retry and adoption.
- Task 3 complete: frontend workbench, simple creation, routing, source/asset tools.
- Task 4 complete: native PostgreSQL, focused and regression tests, build/lint/browser QA.
- Ruling: no cloud deployment or production migration is implied by implementation.
  Prepare incremental migration and document any unavailable live dependencies.
- Subsequent authorization: on 2026-10-14 the user explicitly requested production
  deployment. Released the qualified image pins after isolated backup restoration
  and migration rehearsal; production verification and rollback details are in
  `docs/workbench-production-20261014.md`.
- Independent review: fixed target chapter inclusion, exact indexed versions, current
  official source filtering, public retrieval degradation, retained partial retries,
  retry SSE replacement, and full replacement-adoption state/progress.
- Runtime scope: one worker, matching current process-local orchestration. Distributed
  task leasing and cross-worker stop signals are subsequent deployment work.
- Operations and remaining verification boundaries: `docs/conversation-workbench.md`.

## Acceptance Evidence

Verified on 2026-10-13 against the final local implementation.

| Contract | Artifact | Verification |
| --- | --- | --- |
| AC-1 | Workbench service, persisted jobs, SSE watcher | Job/API tests cover streaming, partial failure, stop, idempotency and concurrent retry; browser restores failure after reload. |
| AC-2 | Asset repository and asset workspace | PostgreSQL version/CAS/copy tests; browser saves full replies and selected text without adopting chapters. |
| AC-3 | Retrieval module and transactional index hooks | Exact offset and protected context tests; current official version filtering, old-editor update/rewind and one-time backfill tests; browser provenance and keyword search. |
| AC-4 | Review/adoption service and repository | Real database tests for explicit atomic adoption, stale settings, duplicate receipts, chapter replacement progress and story memory; HTTP test verifies quota identity. |
| AC-5 | Scoped workbench router and repository | Cross-tenant asset/job/search tests and authenticated HTTP 404 checks. |
| AC-6 | Frontend routing, simple creation and responsive workbench | Route/API/component tests, production build, browser checks at 1440/820/390 pixels, and original studio navigation. |

- Backend regression: 1357 passed; the existing Windows-incompatible SIGKILL
  test file is explicitly excluded and remains a Linux CI check.
- Workbench-specific backend checks: 22 passed on isolated native PostgreSQL.
- Frontend regression: 205 passed across 32 files with four test workers.
- Production frontend build, scoped lint, configured mypy and static complexity
  gates passed. Native migration upgrade/downgrade/upgrade passed.
- Browser report: `.release/workbench-qa/browser/verification.json`; no page
  errors, horizontal overflow or hidden composer at any checked viewport.
- Real model output quality, latency and expense remain unverified because no
  local provider key is configured. Provider fixtures do not certify that dependency.

## TODO

- Paginated conversations/messages and lazy asset/chapter bodies for long novels.
- Semantic vectors, reranking, and entity graph retrieval.
- Novel to AIGC-compatible screenplay.
- Screenplay to video generation and video asset management.
- Distributed workbench task leasing before increasing the current single worker.
