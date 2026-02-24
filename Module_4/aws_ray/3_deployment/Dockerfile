# Dockerfile for Ray Document Processing Pipeline — PRODUCTION READY
#
# Changes from original:
#   1. ray:2.53.0-py312-cpu     → drops CUDA (~1.5GB saving)
#   2. libglib2.0-0 added       → fixes libgthread-2.0.so.0 crash (was killing all tasks)
#   3. libgl1 instead of libgl1-mesa-glx → more reliable on Ubuntu 22.04
#   4. Docling models pre-baked → no HuggingFace download at runtime (saves 2-3min/task)
#   5. CPU-only torch wheel     → saves ~1.5GB vs default CUDA wheel
#   6. RAY_ADDRESS removed      → set per-environment in CloudFormation, not image
#   7. requirements.txt before code → pip layer cached on code-only rebuilds
#
# Author: Prudhvi

# ── BASE ─────────────────────────────────────────────────────────────────────
# -cpu variant: no CUDA/GPU libraries (~1.5GB smaller than default)
FROM rayproject/ray:2.53.0-py312-cpu

WORKDIR /app

# ── SYSTEM DEPS ──────────────────────────────────────────────────────────────
# Single layer + same-step cleanup to avoid bloating image with apt cache
RUN sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    # PDF rendering — required by pdf2image / poppler
    poppler-utils \
    # OpenGL — required by EasyOCR / OpenCV (Docling layout detection)
    libgl1 \
    # GLib / GThread — required by torch/torchvision on Ubuntu 22.04 CPU image
    libglib2.0-0 \
    # OpenMP — required by PyTorch CPU builds
    libgomp1 \
    # Image codecs — required by Pillow for JPEG/PNG/TIFF
    libjpeg-turbo8 \
    libpng16-16 \
    # X11 minimal — required by some OpenCV headless builds
    libxext6 \
    libxrender1 \
    # libmagic — required by unstructured (uses python-magic for file type detection)
    libmagic1 \
    && sudo apt-get clean \
    && sudo rm -rf /var/lib/apt/lists/*

# ── PYTHON DEPS ──────────────────────────────────────────────────────────────
# Copy requirements BEFORE code — Docker caches this layer separately.
# Code-only changes don't trigger a re-run of pip install.
COPY requirements.txt .

# --extra-index-url forces CPU-only torch wheel (~500MB vs ~2GB CUDA default)
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt \
    && pip cache purge

# ── PRE-DOWNLOAD DOCLING MODELS ───────────────────────────────────────────────
# Without this, Docling downloads ~500MB of layout/table detection models from
# HuggingFace on FIRST USE inside each container.
# On Fargate every task starts a fresh container = 2-3 min model download per task.
#
# The official way is: docling-tools models download
# This bakes models into the image so they come from ECR (fast, free) not HuggingFace.
RUN python3 -m docling.utils.model_downloader || \
    docling-tools models download || \
    python3 -c "\
from docling.document_converter import DocumentConverter; \
from docling.datamodel.pipeline_options import PdfPipelineOptions; \
from docling.datamodel.base_models import InputFormat; \
from docling.document_converter import PdfFormatOption; \
opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True); \
DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}); \
print('Models cached via DocumentConverter init') \
" || echo "WARNING: Model pre-download skipped — will download at runtime"

# ── APPLICATION CODE ─────────────────────────────────────────────────────────
# Copy last — code changes don't invalidate pip or model layers above
COPY *.py /app/

# ── ENVIRONMENT ──────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
# Point HuggingFace to where the pre-downloaded models are cached
ENV HF_HOME=/home/ray/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/ray/.cache/huggingface
# RAY_ADDRESS intentionally NOT set — injected by CloudFormation per environment

# ── PORTS ────────────────────────────────────────────────────────────────────
EXPOSE 6379 8265 10001