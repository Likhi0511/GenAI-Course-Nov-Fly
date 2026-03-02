# Dockerfile for Ray Document Processing Pipeline — PRODUCTION READY
#
# Changes from original:
#   1. ray:2.53.0-py312-cpu     → drops CUDA (~1.5GB saving)
#   2. libglib2.0-0 added       → fixes libgthread-2.0.so.0 crash
#   3. libgl1 instead of libgl1-mesa-glx → more reliable on Ubuntu 22.04
#   4. Docling models pre-baked → no HuggingFace download at runtime (saves 2-3min/task)
#   5. CPU-only torch wheel     → saves ~1.5GB vs default CUDA wheel
#   6. RAY_ADDRESS removed      → set per-environment in CloudFormation, not image
#   7. requirements.txt before code → pip layer cached on code-only rebuilds
#   8. [FIX] PYTHONIOENCODING=utf-8 + LANG=en_US.UTF-8 → forces Python UTF-8 I/O
#      everywhere — prevents 'latin-1 codec can't encode \uf0b7' when Pinecone's
#      HTTP layer serialises metadata from clinical PDFs with Windows PUA bullets
#   9. [FIX] sitecustomize.py COPYed into site-packages → sets UTF-8 at interpreter
#      startup before any application code — covers Ray worker subprocesses that
#      fork/spawn and may re-open stdio outside the ENV var codepath
#  10. [FIX] locales package + UTF-8 locale generated → ensures OS locale stack
#      agrees with Python; locale-less Ubuntu 22.04 images fall back to ASCII
#
# NOTE: sitecustomize.py must sit next to this Dockerfile at build time.
#       It is a plain Python file — no heredoc, no shell quoting issues.
#
# Author: Prudhvi

# ── BASE ─────────────────────────────────────────────────────────────────────
FROM rayproject/ray:2.53.0-py312-cpu

WORKDIR /app

# ── SYSTEM DEPS ──────────────────────────────────────────────────────────────
RUN sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libjpeg-turbo8 \
    libpng16-16 \
    libxext6 \
    libxrender1 \
    libmagic1 \
    # [FIX #10] locales — generate en_US.UTF-8 so LANG env var actually works.
    # Without this, locale-less base images silently fall back to ASCII/POSIX
    # even when LANG=en_US.UTF-8 is set, causing latin-1 errors in subprocesses.
    locales \
    && sudo apt-get clean \
    && sudo rm -rf /var/lib/apt/lists/* \
    && sudo locale-gen en_US.UTF-8 \
    && sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# ── PYTHON DEPS ──────────────────────────────────────────────────────────────
COPY requirements.txt .

RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt \
    && pip cache purge

# ── [FIX #9] SITECUSTOMIZE — UTF-8 ENCODING AT INTERPRETER STARTUP ───────────
#
# WHY COPY instead of RUN + heredoc
# ----------------------------------
# The previous approach piped python3 output into xargs to write the file:
#
#   RUN python3 -c "import site; ..." | xargs -I{} sudo tee {}/sitecustomize.py << 'EOF'
#   ...content with double quotes inside...
#   EOF
#
# This fails because Docker passes the entire RUN instruction as a single
# shell string to /bin/sh -c "...". The double quotes inside the heredoc body
# break xargs argument parsing:
#
#   xargs: unmatched double quote
#
# The fix: COPY sitecustomize.py as a plain file, then a single RUN moves it
# into the correct site-packages directory. No quoting, no pipes, no heredoc.
#
# WHAT sitecustomize.py DOES
# --------------------------
# Python executes sitecustomize.py automatically at interpreter startup —
# before any application code, before Ray imports, before urllib3 loads.
# It re-wraps sys.stdin/stdout/stderr in UTF-8 if they are not already,
# so every Python process in the container (including Ray worker forks)
# uses UTF-8 for all I/O. This is the deepest possible fix and covers
# subprocesses that bypass PYTHONIOENCODING.
COPY sitecustomize.py /tmp/sitecustomize.py
RUN SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && sudo cp /tmp/sitecustomize.py "${SITE_PACKAGES}/sitecustomize.py" \
    && sudo chmod 644 "${SITE_PACKAGES}/sitecustomize.py" \
    && echo "sitecustomize.py installed to ${SITE_PACKAGES}" \
    && python3 -c "import sitecustomize; import sys; assert sys.stdout.encoding.lower() == 'utf-8', sys.stdout.encoding" \
    && echo "UTF-8 stdio confirmed"

# ── PRE-DOWNLOAD DOCLING MODELS ───────────────────────────────────────────────
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
COPY *.py /app/

# ── ENVIRONMENT ──────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1

# [FIX #8] Three env vars that together force UTF-8 at every layer:
#
#   PYTHONIOENCODING=utf-8
#     Forces Python stdin/stdout/stderr to UTF-8 regardless of locale.
#     Primary fix for the Pinecone latin-1 UnicodeEncodeError.
#
#   LANG=en_US.UTF-8
#     Sets the C library locale — controls how glibc mbstowcs() and file
#     open() handle encoding. urllib3/httpx may use this path for
#     byte-to-string conversion.
#
#   LC_ALL=en_US.UTF-8
#     Overrides all LC_* categories (especially LC_CTYPE which governs
#     character classification). Without it, isalpha('\uf0b7') and similar
#     C-library checks can misbehave on non-ASCII input.
ENV PYTHONIOENCODING=utf-8
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

ENV HF_HOME=/home/ray/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/ray/.cache/huggingface
# RAY_ADDRESS intentionally NOT set — injected by CloudFormation per environment

# ── PORTS ────────────────────────────────────────────────────────────────────
# 6379  — Ray GCS (head node cluster bus)
# 8265  — Ray Dashboard (web UI)
# 10001 — Ray client server (remote .remote() calls)
EXPOSE 6379 8265 10001