# Dockerfile for Ray Document Processing Pipeline
#
# This image contains all dependencies for running the pipeline
# including Docling, OpenAI, Pinecone, and AWS integrations.
#
# Pipeline stages:
#   1. Extraction  - docling_bounded_extractor.py  (Docling + GPT-4o Vision)
#   2. Chunking    - comprehensive_chunker.py       (boundary-aware semantic chunking)
#   3. Enrichment  - enrich_pipeline_openai.py      (OpenAI PII+NER+key-phrases)
#   4. Embedding   - openai_embeddings.py           (text-embedding-3-small + tenacity)
#   5. Loading     - load_embeddings_to_pinecone.py (Pinecone serverless)
#
# Author: Prudhvi
# Organization: Thoughtworks

FROM rayproject/ray:2.9.0-py313

# Set working directory
WORKDIR /app

# System dependencies
# poppler-utils: required by pdf2image for PDF -> PNG rendering
# NOTE: tesseract-ocr removed - do_ocr=False in extractor (text-based PDFs only)
# NOTE: spaCy removed - NLP enrichment is now handled by OpenAI gpt-4o-mini
RUN sudo apt-get update && sudo apt-get install -y \
    poppler-utils \
    && sudo rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
# NOTE: torch / sentence-transformers / spacy removed from requirements.txt
#       Image is now significantly smaller (~4 GB -> ~1.5 GB)
RUN pip install --no-cache-dir -r requirements.txt

# Copy all pipeline code
COPY .. /app/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV RAY_ADDRESS=auto

# Expose Ray ports
EXPOSE 6379 8265 10001

# Default command (can be overridden)
CMD ["python", "ray_orchestrator.py"]
