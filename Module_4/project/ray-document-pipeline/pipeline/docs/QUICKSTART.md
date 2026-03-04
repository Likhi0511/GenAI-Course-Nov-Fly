# Quickstart — Local Dev Setup

Get a single PDF through all 5 pipeline stages on your laptop in under 5 minutes.

## Prerequisites

- Python 3.10+ (3.12 recommended)
- OpenAI API key (`OPENAI_API_KEY`)
- Pinecone API key (`PINECONE_API_KEY`)

## 1. Clone & Install

```bash
git clone <repo-url> ray-rag-pipeline
cd ray-rag-pipeline

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"          # Installs all dependencies + dev tools
```

## 2. Set Environment Variables

```bash
# macOS / Linux
export OPENAI_API_KEY="sk-..."
export PINECONE_API_KEY="pcsk_..."

# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
$env:PINECONE_API_KEY = "pcsk_..."
```

## 3. Run a Single PDF (No Ray Needed)

Each stage can be run standalone — no Ray cluster required for local testing.

```bash
# Stage 1: Extract PDF → Markdown pages
python -m stages.extract --pdf sample.pdf --output-dir ./output/extracted/

# Stage 2: Chunk → semantic chunks JSON
python -m stages.chunk --input-dir ./output/extracted/pages/ --output ./output/chunks.json

# Stage 3: Enrich → NER, PII redaction, key phrases
python -m stages.enrich --input ./output/chunks.json --output ./output/enriched.json

# Stage 4: Embed → 1536-dim vectors
python -m stages.embed --input ./output/enriched.json --output ./output/embeddings.json

# Stage 5: Load → upsert to Pinecone
python -m stages.load --input ./output/embeddings.json --index my-test-index
```

## 4. Run with Local Ray (Optional)

To test the full orchestrated pipeline with Ray locally:

```bash
# Start a local Ray cluster
ray start --head --port=6379

# Set config for local mode
export RAY_ADDRESS=""                          # Empty = "auto" = local cluster
export S3_BUCKET="my-local-test-bucket"        # You need an S3 bucket
export AWS_REGION="us-east-1"
export DYNAMODB_CONTROL_TABLE="ray-pipeline-control"
export DYNAMODB_AUDIT_TABLE="ray-pipeline-audit"

# Run the orchestrator (polls DynamoDB for PENDING documents)
python -m orchestration.orchestrator
```

## 5. Verify

```bash
# Check Pinecone has vectors
python -c "
from pinecone import Pinecone
pc = Pinecone(api_key='YOUR_KEY')
idx = pc.Index('my-test-index')
print(idx.describe_index_stats())
"
```

## Project Structure

```
ray-rag-pipeline/
├── core/            # Shared utilities (S3, encoding, config, logging)
├── stages/          # 5 pipeline stages (extract, chunk, enrich, embed, load)
├── orchestration/   # Ray coordination (orchestrator, tasks, DynamoDB)
├── deploy/
│   ├── prerequisites/  # Pre-deployment validation scripts
│   ├── cloudformation/ # AWS infrastructure template
│   └── steps/          # Deployment step scripts
├── docker/          # Dockerfile, requirements.txt, sitecustomize.py
└── docs/            # This documentation
```

## Next Steps

- **Deploy to AWS:** See [DEPLOYMENT.md](DEPLOYMENT.md)
- **Understand the architecture:** See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Hit an error?** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
