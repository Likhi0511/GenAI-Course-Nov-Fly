# Dockerfile for Ray Document Processing Pipeline
#
# Uses Ray 2.53.0 with Python 3.12 for full compatibility with latest packages.
#
# Pipeline stages:
#   1. Extraction  - docling_bounded_extractor.py  (Docling + GPT-4o Vision)
#   2. Chunking    - comprehensive_chunker.py      (boundary-aware semantic chunking)
#   3. Enrichment  - enrich_pipeline_openai.py     (OpenAI PII+NER+key-phrases)
#   4. Embedding   - openai_embeddings.py          (text-embedding-3-small + tenacity)
#   5. Loading     - load_embeddings_to_pinecone.py (Pinecone serverless)
#
# Author: Prudhvi

FROM rayproject/ray:2.53.0-py312

# Set working directory
WORKDIR /app

# System dependencies
# System dependencies
# poppler-utils: required by pdf2image
# libgl1/libgomp1: required by Docling/PyTorch to prevent raylet initialization crashes
RUN sudo apt-get update && sudo apt-get install -y \
    poppler-utils \
    libgl1-mesa-glx \
    libgomp1 \
    && sudo rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
# All packages now compatible with Python 3.12
RUN pip install --no-cache-dir -r requirements.txt

# Copy all pipeline code
COPY . /app/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV RAY_ADDRESS=auto

# Expose Ray ports
EXPOSE 6379 8265 10001

# Default command (can be overridden)
#CMD ["python", "ray_orchestrator.py"]