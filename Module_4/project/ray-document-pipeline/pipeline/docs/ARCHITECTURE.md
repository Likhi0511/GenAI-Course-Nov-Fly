# Architecture

## System Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                         AWS ECS Fargate                                │
│                                                                        │
│  ┌──────────────────────┐     ┌────────────────────────────────────┐  │
│  │      RAY HEAD         │     │         RAY WORKERS (1–10)         │  │
│  │                        │     │                                    │  │
│  │  orchestration/        │     │  orchestration/tasks.py            │  │
│  │    orchestrator.py     │────▶│    @ray.remote functions           │  │
│  │    dynamodb.py         │     │                                    │  │
│  │                        │     │  stages/                           │  │
│  │  Polls DynamoDB        │     │    extract → chunk → enrich        │  │
│  │  Dispatches to workers │     │    → embed → load                  │  │
│  └──────────┬─────────────┘     └──────────────────┬─────────────────┘  │
│             │                                       │                    │
└─────────────┼───────────────────────────────────────┼────────────────────┘
              │                                       │
    ┌─────────▼──────────┐              ┌─────────────▼──────────┐
    │     DynamoDB        │              │         S3              │
    │  control / audit    │              │  input/ → extracted/    │
    │                     │              │  → chunks/ → enriched/  │
    └─────────────────────┘              │  → embeddings/          │
                                         └────────────┬────────────┘
                                                      │
                                         ┌────────────▼────────────┐
                                         │       Pinecone           │
                                         │   Vector Database        │
                                         │   (1536-dim cosine)      │
                                         └──────────────────────────┘
```

---

## Package Dependency Graph

```
orchestration/
  ├── orchestrator.py  → orchestration.dynamodb, orchestration.tasks
  ├── dynamodb.py      → core.config
  └── tasks.py         → stages.*, core.config, core.s3, core.workspace, core.logging

stages/
  ├── extract.py       → (no core imports — standalone)
  ├── chunk.py         → (no core imports — standalone)
  ├── enrich.py        → core.encoding
  ├── embed.py         → core.encoding
  └── load.py          → core.encoding

core/
  ├── config.py        → (no internal deps — reads env vars / Secrets Manager)
  ├── s3.py            → core.config
  ├── workspace.py     → core.config
  ├── encoding.py      → (no internal deps — pure Unicode/JSON utilities)
  └── logging.py       → (no internal deps — formatting helpers)
```

**Key design rule:** `stages/` never imports from `orchestration/`.
`orchestration/` imports from both `stages/` and `core/`.
`core/` has no upward dependencies. This ensures stages can be tested
and run standalone without Ray, DynamoDB, or any infrastructure.

---

## The 5-Stage Pipeline

Each stage reads from S3, processes, writes back to S3. The orchestrator
passes the output S3 key from each stage as input to the next.

```
PDF (S3)
  │
  ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1: EXTRACT (stages/extract.py)               │
│  PDF → Markdown pages with boundary markers          │
│  Tables/images described by GPT-4o                   │
│  Cost: ~$0.01–0.05/doc  Time: 30–60s                │
│  Output: s3://bucket/extracted/<doc_id>/             │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Stage 2: CHUNK (stages/chunk.py)                   │
│  Boundary-aware semantic chunking (~1500 chars)      │
│  Respects document structure (never splits mid-table)│
│  Cost: FREE (pure CPU)  Time: 2–5s                  │
│  Output: s3://bucket/chunks/<doc_id>_chunks.json     │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Stage 3: ENRICH (stages/enrich.py)                 │
│  PII redaction + NER + key phrases (GPT-4o-mini)     │
│  Single API call per chunk handles all three tasks   │
│  Cost: ~$0.001–0.002/chunk  Time: 20–30s            │
│  Output: s3://bucket/enriched/<doc_id>_enriched.json │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Stage 4: EMBED (stages/embed.py)                   │
│  text-embedding-ada-002 → 1536-dim vectors           │
│  Batch processing with exponential-backoff retry     │
│  Cost: ~$0.003–0.01/doc  Time: 15–25s               │
│  Output: s3://bucket/embeddings/<doc_id>_emb.json    │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Stage 5: LOAD (stages/load.py)                     │
│  Upsert vectors to Pinecone (idempotent MD5 IDs)     │
│  Metadata flattened, Unicode sanitized for Latin-1   │
│  Cost: free tier  Time: 10–15s                      │
│  Output: vectors live in Pinecone (no S3 output)     │
└─────────────────────────────────────────────────────┘
```

**Total per document:** ~$0.02–0.08 | ~2–3 minutes

---

## Stage Contracts

Every `@ray.remote` stage function in `orchestration/tasks.py` returns a
dict with this shape:

```python
# On success:
{
    "status": "COMPLETED",
    "output_s3_key": "enriched/doc_123_enriched.json",   # Input for next stage
    "duration_seconds": 25,
    "metadata": { ... }                                   # Stage-specific metrics
}

# On failure:
{
    "status": "FAILED",
    "error": "descriptive error message",
    "duration_seconds": 12
}
```

The orchestrator checks `status` after each `ray.get()`. If any stage
returns `FAILED`, the pipeline aborts and marks the document as `FAILED`
in DynamoDB. A separate retry job can re-set it to `PENDING` later.

---

## S3 Key Conventions

All pipeline artifacts follow a consistent prefix structure:

```
s3://<bucket>/
│
├── input/                              ← User uploads PDFs here
│   └── NCT04368728_Remdesivir.pdf
│
├── extracted/<doc_id>/                 ← Stage 1 output
│   ├── pages/
│   │   ├── page_1.md                   ← Boundary-marked markdown
│   │   └── page_2.md
│   ├── tables/
│   │   └── p3_table_1.md               ← Raw table markdown
│   ├── images/
│   │   └── fig_p3_1.png                ← Extracted figures
│   └── metadata.json                   ← Page count, timing
│
├── chunks/<doc_id>_chunks.json         ← Stage 2 output
├── enriched/<doc_id>_enriched.json     ← Stage 3 output
├── embeddings/<doc_id>_embeddings.json ← Stage 4 output
└── pipeline-logs/                      ← Processing audit trail
```

---

## DynamoDB Document Lifecycle

```
    PDF lands in S3
         │
         ▼
    Lambda creates
    PENDING record    ──────────────────┐
         │                               │
         ▼                               │
    Orchestrator polls                   │
    claims document                      │
    (conditional update)                 │
         │                               │
         ▼                               │
    IN_PROGRESS                          │
    ├── STAGE_1_EXTRACTION               │
    ├── STAGE_2_CHUNKING                 │  Another orchestrator
    ├── STAGE_3_ENRICHMENT               │  instance tries to
    ├── STAGE_4_EMBEDDING                │  claim → ConditionalCheck
    ├── STAGE_5_LOADING                  │  FailedException → skip
    │                                    │
    ├── ✓ COMPLETED ──── done            │
    │                                    │
    └── ✗ FAILED ──── retry job can      │
                       re-set to PENDING ┘
```

The **conditional update** (`claim_document()`) prevents double-processing
when multiple orchestrator instances run simultaneously (rolling deploy, HA).

---

## Encoding Architecture

Clinical/pharma PDFs contain Unicode characters (Windows PUA bullets like
U+F0B7) that cause `latin-1` encoding errors when Pinecone's HTTP layer
serializes metadata. The fix is a three-layer defense:

| Layer | Where | What |
|-------|-------|------|
| **1. Container** | `Dockerfile` ENV vars + `sitecustomize.py` | Forces UTF-8 at OS + interpreter level |
| **2. Transport** | `core/encoding.py` → `patch_urllib3_latin1()` | Monkey-patches urllib3 to encode request bodies as UTF-8 |
| **3. Application** | `core/encoding.py` → `sanitize_metadata()` | Replaces known PUA chars, strips anything that can't survive Latin-1 |

See `core/encoding.py` for the full implementation and `TROUBLESHOOTING.md`
for debugging encoding errors.

---

## Auto-Scaling Strategy

```
                    CloudWatch Metric
                    "PendingDocuments"
                    (published every 60s
                     by MetricPublisher Lambda)
                           │
              ┌────────────┼────────────┐
              ▼                         ▼
     ScaleOut Alarm              ScaleIn Alarm
     (pending > 0)              (pending = 0 for 5 min)
              │                         │
              ▼                         ▼
     Add 1 worker               Remove 1 worker
     cooldown: 120s             cooldown: 300s
              │                         │
              ▼                         ▼
     Min: 1 worker              Min: 1 worker
     Max: 10 workers            (never scales to 0)
```

Asymmetric cooldowns: scale out fast (don't let documents queue up),
scale in slow (avoid thrashing if new documents arrive soon after).

---

## Graceful Shutdown (ECS SIGTERM)

```
ECS sends SIGTERM
       │
       ▼
signal_handler() sets shutdown_requested = True
       │
       ▼
interruptible_sleep() wakes within 1s
       │
       ▼
Between each ray.get(): check shutdown_requested
       │
       ▼
Current stage completes → pipeline aborts
       │
       ▼
ray.shutdown() → sys.exit(0)
       │
       ▼
ECS marks task STOPPED (not FAILED)
```

**Why this matters:** `time.sleep(60)` is not interruptible. If ECS
`stopTimeout` is 30s and the orchestrator is mid-sleep, it gets SIGKILL
before it can clean up. The 1-second chunked sleep guarantees response
within ~1s of SIGTERM.
