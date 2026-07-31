# Semantic retrieval (RAG) API contract

All endpoints use the `/api/v1/projects/{project_id}/rag` prefix. Embedder configuration lives
in the `rag` section of `/api/v1/settings/integrations`.

## Ownership and integration

- This branch owns `routes/rag.py`, `schemas/rag.py`, and `services/rag/**`.
- Papers, repositories, and traces are read-only dependencies: retrieval derives its corpora
  from `PaperDocument.pages_json`, `CodeRepository.symbols_json`, and reviewed `TraceLink` rows.
- Retrieval is an **accelerator layered on top of the exhaustive read tools, never a verdict**.
  A rank orders where to look; the Agent must still read the real block/source and quote it
  verbatim before publishing. Any consumer that treats a score as a semantic conclusion is
  violating this contract.
- Every failure path degrades to "no results" with a machine-readable reason. A missing index,
  a failed embedder, or a disabled feature must never break parsing, tracing, or chat.

## Index scopes and invalidation

Indexes are maintained automatically; the endpoints below exist for visibility and for cases
automation cannot cover (switching embedder, recovering a failed remote call, seeding a project
imported before this feature existed).

| Scope | Corpus | Generation key | Rebuilt when |
|---|---|---|---|
| `paper` | MinerU page blocks, falling back to `paragraphs_json` | `PaperDocument.content_hash` | paper parse succeeds |
| `code` | indexed symbols + path/signature/docstring/callees + real source slice | `{repository_id}:{analysis_revision}` | code analysis becomes current |
| `trace` | reviewed (`accepted` / `rejected`) `TraceLink` rows | digest of reviewed link ids + statuses | a review verdict changes (marked stale, rebuilt lazily on next search) |

A scope whose source is absent (no parsed paper, no reviewed link) reports `status: "pending"`
with `chunk_count: 0`, and any stored generation is dropped so a search cannot answer from a
corpus whose source has gone away.

## Read index status

```text
GET /api/v1/projects/{project_id}/rag/status
```

```json
{
  "enabled": true,
  "embedder": "local",
  "model": "local-hashing",
  "scopes": [
    {
      "scope": "paper",
      "status": "ready",
      "chunk_count": 128,
      "embedder": "local",
      "model": "local-hashing-512",
      "dimensions": 512,
      "error": null,
      "built_at": "2026-07-29T10:12:03.114Z"
    }
  ]
}
```

`status` is one of `pending`, `building`, `ready`, `failed`. `error` carries the embedder
failure reason when `status="failed"` (e.g. `embedding_unauthorized`, `embedding_timeout`).

## Rebuild

```text
POST /api/v1/projects/{project_id}/rag/rebuild
```

```json
{ "scope": "paper", "force": false }
```

Omit `scope` to rebuild every scope. `force` re-embeds even when the stored generation already
matches the source; without it a current index is reused and reported as `reused: true`.

Runs inline and returns real counts — a rebuild is bounded by corpus size and the caller asked
for it, so there is no job to poll. Allow a generous client timeout when a remote embedder is
configured.

```json
{
  "results": [
    { "scope": "paper", "status": "ready", "chunk_count": 128 },
    { "scope": "code", "status": "ready", "chunk_count": 412, "reused": true },
    { "scope": "trace", "status": "pending", "chunk_count": 0 }
  ]
}
```

## Search

```text
GET /api/v1/projects/{project_id}/rag/search?query=...&scope=paper&limit=5
```

`scope` defaults to `paper`; an unknown scope is `422`. `limit` is 1–20. A not-ready scope is
built on demand before searching.

```json
{
  "ok": true,
  "query": "loss that down-weights easy examples",
  "scope": "paper",
  "embedder": "local:local-hashing-512",
  "items": [
    {
      "ref": "p1-b1",
      "score": 0.4637,
      "text": "We adopt a focal loss that down-weights easy negatives ...",
      "kind": "paragraph",
      "page": 1,
      "section_path": ["Method", "Loss"],
      "window": 0
    }
  ],
  "searched": 128,
  "reason": null
}
```

Retrieval failure answers `200` with `ok: false` and a stable `reason`, not an HTTP error, so a
caller can fall back to exhaustive reading:

| `reason` | Meaning |
|---|---|
| `rag_disabled` | retrieval switched off in settings |
| `rag_index_empty` | scope has no indexed corpus (source absent or empty) |
| `rag_index_failed` | last build failed; `status` endpoint carries the embedder reason |
| `rag_empty_query` | blank query |
| `rag_vector_deps_missing` | `lancedb` selected but optional `rag` extra not installed |
| `embedding_*` | live embedder failure while embedding the query |

`ref` is always an id that can be fed straight back into an existing read tool
(`get_paper_block`, `get_symbol_source`, a `trace_id`). Per-scope extra keys: `paper` adds
`kind` / `page` / `section_path`; `code` adds `path` / `kind` / `name` / `line_start` /
`line_end`; `trace` adds `status` / `relation_type` / `paper_ref` / `code_ref` / `paper_quote` /
`code_quote` / `rationale` / `confidence`. One hit per underlying object — overlapping windows
of the same block are collapsed.

## Agent tools

Retrieval reaches the Agents as three read-only tools (see [agent contract](agent.md)):

| Tool | Scope | Available to |
|---|---|---|
| `semantic_search_paper` | `paper` | trace (+ subagents), conflict, chat |
| `semantic_search_code` | `code` | trace (+ subagents), architecture, conflict, chat |
| `recall_trace_cases` | `trace` | trace (+ subagents), chat |

Each result carries an `instruction` restating that a rank is not a verdict. When an index is
unavailable the tool returns `found: false` plus a fallback instruction naming the paging and
text-search tools; the run continues.

`recall_trace_cases` returns **precedents, not evidence**. Both verdicts are included: an
accepted case shows the evidence standard that held up, a rejected one shows a lexical
near-miss that did not. A recalled case must never be cited as a quote, and its verdict must
never be reused without re-reading the current code.

The trace job's system prompt additionally injects up to four similar reviewed cases for this
project, recalled by the paper's own title/abstract, under an explicit "NOT evidence for this
run" header. Absent any reviewed link, no block is injected.

## Settings

```text
GET  /api/v1/settings/integrations
PUT  /api/v1/settings/integrations
```

The `rag` section:

```json
{
  "enabled": true,
  "embedder": "local",
  "base_url": "",
  "model": "",
  "dimensions": 512,
  "timeout_seconds": 30.0,
  "api_key_configured": false,
  "vector_store": "sqlite"
}
```

`embedder` is `local` (offline signed feature hashing — no key, no network; the default so
retrieval works on a fresh install) or `remote` (any OpenAI-compatible `POST {base_url}/embeddings`).
When `remote` is fully configured and the optional backend `rag` extra is installed, embeddings
go through LangChain's `OpenAIEmbeddings`; otherwise the httpx client is used.

`vector_store` is `sqlite` (exact in-Python cosine scan over `rag_chunk` — the default) or
`lancedb` (optional LanceDB ANN under `data/rag-lancedb/`). LanceDB requires
`uv sync --extra rag`; without it, search returns `rag_vector_deps_missing` rather than
crashing the agent.

On `PUT`, write the key as `rag.api_key` or drop it with `rag.clear_api_key: true`; it is never
echoed back. The whole `rag` section is optional so an older client keeps working — omitting it
preserves stored values rather than resetting the embedder.

Changing `embedder`, `model`, `dimensions`, or `vector_store` marks **every** project's indexes
`pending`: vectors from different generations or backends are not comparable. An incomplete
remote configuration (URL without key or model) silently falls back to the local embedder, so
clients should validate completeness before saving rather than letting the fallback look like an
ignored setting.

## Storage

`rag_chunk` holds one row per embedded unit when `vector_store=sqlite` (`project_id`, `scope`,
`source_key`, `ref`, `text`, `embedding`, `dimensions`, `embedder`, `metadata_json`);
`rag_index_state` holds one row per `(project_id, scope)` with the indexed generation and status
for **both** backends. With `vector_store=lancedb`, embeddings live only under
`data/rag-lancedb/{project_id}/{scope}` (not duplicated into SQLite). Schema for the SQLite
path was created by migration `0013_rag_index`; `rag_vector_store` was added by
`0015_rag_vector_store`.
