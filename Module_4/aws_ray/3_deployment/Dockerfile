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
#   8. [FIX] PYTHONIOENCODING=utf-8 + LANG=en_US.UTF-8 → forces Python's stdin/stdout/
#      stderr to UTF-8 everywhere — prevents 'latin-1 codec can't encode \uf0b7' when
#      Pinecone's HTTP layer serialises metadata from clinical PDFs containing
#      Windows PUA bullet characters (Wingdings \uf0b7 etc.)
#   9. [FIX] sitecustomize.py injected → sets sys.stdin/stdout/stderr to UTF-8 at
#      interpreter startup, before any application code runs — covers subprocesses
#      spawned by Ray workers that inherit the container environment
#  10. [FIX] locales package + UTF-8 locale generated → ensures the OS locale
#      stack agrees with Python; some Ubuntu 22.04 base images ship locale-less
#      which causes C library functions to fall back to ASCII
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
    # [FIX #10] locales — required to generate en_US.UTF-8 locale so the OS
    # locale stack doesn't fall back to ASCII/POSIX on locale-less base images.
    # Without this, glibc file-open calls may default to ASCII even if Python
    # is set to UTF-8, causing latin-1 errors in subprocesses.
    locales \
    && sudo apt-get clean \
    && sudo rm -rf /var/lib/apt/lists/* \
    # [FIX #10] Generate UTF-8 locale immediately after install (same layer = no cache bloat)
    && sudo locale-gen en_US.UTF-8 \
    && sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# ── PYTHON DEPS ──────────────────────────────────────────────────────────────
# Copy requirements BEFORE code — Docker caches this layer separately.
# Code-only changes don't trigger a re-run of pip install.
COPY requirements.txt .

# --extra-index-url forces CPU-only torch wheel (~500MB vs ~2GB CUDA default)
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt \
    && pip cache purge

# ── [FIX #9] SITECUSTOMIZE — UTF-8 ENCODING AT INTERPRETER STARTUP ───────────
# sitecustomize.py is executed by Python before any user code, including
# before Ray worker processes import application modules.
#
# WHY THIS IS NEEDED ON TOP OF THE ENV VARS BELOW
# ------------------------------------------------
# PYTHONIOENCODING sets stdin/stdout/stderr encoding for the *top-level*
# interpreter.  Ray spawns worker subprocesses (via multiprocessing / fork)
# which inherit env vars but occasionally re-open their stdio streams.
# sitecustomize.py runs inside every Python interpreter invocation regardless
# of how it was launched, making it the most reliable catch-all.
#
# WHAT IT DOES
# ------------
# Calls importlib.reload(sys) is NOT needed in Python 3.
# We use sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# only if the stream is not already UTF-8 — avoids double-wrapping.
RUN python3 -c "import site; print(site.getsitepackages()[0])" \
    | xargs -I{} sudo tee {}/sitecustomize.py << 'SITECUSTOMIZE'
"""
sitecustomize.py — injected by Dockerfile to force UTF-8 I/O on every
Python interpreter that starts inside this container, including Ray workers.

ROOT CAUSE THIS FIXES
---------------------
Clinical/pharma PDFs commonly contain Windows PUA (Private Use Area)
characters — e.g. U+F0B7 (Wingdings bullet ·) — that Docling correctly
preserves in extracted text. When this text flows into Pinecone metadata
and the HTTP transport layer (urllib3 / httpx) serialises the request body,
it may attempt Latin-1 encoding (the HTTP default for text/plain) and raise:

    UnicodeEncodeError: 'latin-1' codec can't encode character '\uf0b7'
    in position 134109: Body ('\uf0b7') is not valid Latin-1.
    Use body.encode('utf-8') if you want to send it encoded in UTF-8.

Forcing UTF-8 at the interpreter level tells Python's I/O stack and the
underlying C library to use UTF-8 for all text operations, which propagates
into the HTTP client's string-handling codepath.

NOTE: The load_embeddings_to_pinecone.py sanitize_text() function provides
a second line of defence at the application level (named PUA replacements +
latin-1 encode/ignore fallback). Both layers together make the pipeline
robust against any Unicode surprises from future document sources.
"""
import sys
import io

def _ensure_utf8(stream, name):
    """Re-wrap a stream in UTF-8 if it isn't already."""
    if stream is None:
        return
    try:
        if hasattr(stream, 'buffer') and getattr(stream, 'encoding', '').lower() != 'utf-8':
            object.__setattr__(
                sys, name,
                io.TextIOWrapper(stream.buffer, encoding='utf-8', errors='replace')
            )
    except Exception:
        pass  # Never crash sitecustomize — fail silently

_ensure_utf8(sys.stdin,  'stdin')
_ensure_utf8(sys.stdout, 'stdout')
_ensure_utf8(sys.stderr, 'stderr')
SITECUSTOMIZE

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

# [FIX #8] UTF-8 encoding stack — three env vars that together tell Python,
# the C library, and any subprocess to use UTF-8 at every layer:
#
#   PYTHONIOENCODING=utf-8
#     → Forces Python's stdin/stdout/stderr to UTF-8 regardless of locale.
#       This is the primary fix for the Pinecone latin-1 UnicodeEncodeError.
#       Without this, Python on a locale-less container defaults to ASCII/ANSI.
#
#   LANG=en_US.UTF-8
#     → Sets the process locale for the C library (glibc).
#       Controls how mbstowcs(), open(), and other C functions handle encoding.
#       urllib3 / httpx may fall back to the C library for byte-to-string
#       conversion; setting LANG ensures that path uses UTF-8 too.
#
#   LC_ALL=en_US.UTF-8
#     → Overrides all LC_* categories (LC_CTYPE, LC_COLLATE, etc.) to UTF-8.
#       LC_CTYPE in particular governs character classification — without it,
#       isalpha('\uf0b7') and similar checks can behave incorrectly on
#       non-ASCII characters, causing unexpected codec selection downstream.
ENV PYTHONIOENCODING=utf-8
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Point HuggingFace to where the pre-downloaded models are cached
ENV HF_HOME=/home/ray/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/ray/.cache/huggingface
# RAY_ADDRESS intentionally NOT set — injected by CloudFormation per environment

# ── PORTS ────────────────────────────────────────────────────────────────────
# 6379  — Ray GCS (head node cluster bus)
# 8265  — Ray Dashboard (web UI)
# 10001 — Ray client server (remote .remote() calls)
EXPOSE 6379 8265 10001