# Ray RAG Pipeline

A production-grade Retrieval-Augmented Generation (RAG) document processing
pipeline built on Ray, ECS Fargate, and OpenAI. Processes clinical trial PDFs
through 5 stages — extract, chunk, enrich, embed, load — and stores vectors
in Pinecone for semantic search.

Built for the **Applied GenAI** course at Vidya Sankalp.

---

## What It Does

```
Clinical Trial PDF
       │
       ▼
  ┌─────────┐    ┌────────┐    ┌─────────┐    ┌────────┐    ┌──────────┐
  │ Extract  │───▶│ Chunk  │───▶│ Enrich  │───▶│ Embed  │───▶│  Load    │
  │ (Docling)│    │(Semantic│   │(NER/PII)│    │(Ada-002│    │(Pinecone)│
  └─────────┘    │ 1500ch) │   │(GPT-4o) │    │ 1536d) │    └──────────┘
                  └────────┘    └─────────┘    └────────┘
```

**Per document:** ~$0.02–0.08 | ~2–3 minutes | fully parallelized on Ray

---

## Quick Links

| Doc | What's in it |
|-----|-------------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Local dev setup in 5 minutes |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | ECS/CloudFormation deploy guide |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline flow, stage contracts, S3 key conventions |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common errors: encoding, OOM, Ray scheduling |
| [deploy/cloudformation/EXPLAINED.md](deploy/cloudformation/EXPLAINED.md) | CloudFormation template resource walkthrough |

---

## Project Structure

```
ray-rag-pipeline/
│
├── core/                        # Shared utilities
│   ├── config.py                   Config loader (env vars / Secrets Manager)
│   ├── s3.py                       S3Helper — download/upload with retries
│   ├── workspace.py                LocalFileManager — temp dirs per document
│   ├── encoding.py                 Unicode defense (Latin-1 patch, PUA sanitizer)
│   └── logging.py                  Structured logging, format_duration()
│
├── stages/                      # 5 pipeline stages (run standalone or via Ray)
│   ├── extract.py                  PDF → Markdown pages (Docling + GPT-4o)
│   ├── chunk.py                    Boundary-aware semantic chunking
│   ├── enrich.py                   NER + PII redaction (GPT-4o-mini)
│   ├── embed.py                    text-embedding-ada-002 → 1536-dim vectors
│   └── load.py                     Upsert to Pinecone (idempotent, sanitized)
│
├── orchestration/               # Ray coordination layer
│   ├── orchestrator.py             Polling loop — DynamoDB → Ray dispatch
│   ├── tasks.py                    @ray.remote wrappers for each stage
│   └── dynamodb.py                 Atomic claim/update with conditional writes
│
├── deploy/
│   ├── prerequisites/           # Pre-deployment validation (10 checks)
│   │   ├── check.py                Cross-platform (macOS, Linux, Windows)
│   │   └── check_windows.py        Windows-enhanced (charmap fix, ANSI colors)
│   │
│   ├── cloudformation/          # AWS infrastructure
│   │   ├── 1_ray-pipeline-cloudformation-public.yaml
│   │   ├── cloudformation-parameters.json
│   │   └── EXPLAINED.md            Resource walkthrough
│   │
│   └── steps/                   # Deployment scripts (run from laptop)
│       ├── orchestrator.py         Chains all 3 steps
│       ├── step1_deploy_stack.py   CloudFormation create/update
│       ├── step2_download_pdfs.py  Download clinical trial PDFs
│       └── step3_upload_to_s3.py   Upload to S3 (triggers Lambda → DynamoDB)
│
├── docker/                      # Container build
│   ├── Dockerfile                  Ray 2.53 + Docling + pre-baked models
│   ├── requirements.txt            Pinned dependencies
│   └── sitecustomize.py            UTF-8 encoding fix for Ray workers
│
├── docs/                        # Documentation
│   ├── QUICKSTART.md
│   ├── DEPLOYMENT.md
│   ├── ARCHITECTURE.md
│   └── TROUBLESHOOTING.md
│
├── README.md                    # This file
└── pyproject.toml               # Package metadata, ruff, pytest config
```

---

## Prerequisites

- Python 3.10+ (3.12 recommended)
- AWS account with ECS, S3, DynamoDB, Secrets Manager access
- OpenAI API key (GPT-4o for extraction, Ada-002 for embeddings)
- Pinecone API key (free tier works for 20 documents)
- Docker Desktop (for building the Ray container image)

---

## Getting Started

### Local Development

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY="sk-..."
export PINECONE_API_KEY="pcsk_..."

# Process a single PDF through all stages
python -m stages.extract --pdf sample.pdf --output-dir ./output/extracted/
python -m stages.chunk --input-dir ./output/extracted/pages/ --output ./output/chunks.json
python -m stages.enrich --input ./output/chunks.json --output ./output/enriched.json
python -m stages.embed --input ./output/enriched.json --output ./output/embeddings.json
python -m stages.load --input ./output/embeddings.json --index my-test-index
```

### AWS Deployment

```bash
cd deploy/prerequisites && python check.py       # Validate + provision (8-12 min)
cd deploy/steps && python orchestrator.py         # Deploy + upload docs (15-20 min)
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full walkthrough.

---

## Key Design Decisions

**Public subnet (no NAT Gateway):** Saves $32/month. ECS tasks get public IPs
via Internet Gateway. VPC endpoints route S3/DynamoDB traffic internally for
free. Suitable for teaching/demo. Switch to private + NAT for production with
sensitive data.

**Conditional DynamoDB claims:** `claim_document()` uses a conditional update
(`status = PENDING` → `IN_PROGRESS`). If two orchestrators try to claim the
same document, exactly one succeeds. Prevents double-processing without
distributed locks.

**Three-layer encoding defense:** Container ENV vars → urllib3 monkey-patch →
application-level PUA sanitization. Clinical PDFs are full of Unicode
surprises. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#encoding-errors).

**Interruptible sleep:** The orchestrator uses 1-second chunked sleep instead
of `time.sleep(60)`. This lets ECS SIGTERM response happen within ~1 second
instead of waiting for the full sleep to expire.

---

## Cost Summary

| 20 documents | First month | Ongoing (idle) |
|-------------|-------------|----------------|
| Compute (ECS) | ~$5–15 | ~$3/month |
| Storage (S3 + ECR) | < $1 | < $0.50/month |
| Database (DynamoDB) | < $0.01 | $0 (PAY_PER_REQUEST) |
| Secrets Manager | $0.80 | $0.80/month |
| OpenAI API | ~$1–2 | $0 |
| **Total** | **~$8–20** | **~$4–5/month** |

Tear down the CloudFormation stack when not in use to stop all charges
except Secrets Manager ($0.80/month) and ECR storage (~$0.32/month).

---

## Author

**Prudhvi Akella** — Lead Data & AI Engineer, Thoughtworks
Applied GenAI Course, Vidya Sankalp
