"""
===============================================================================
docling_pdf_extractor.py  —  Boundary-Based PDF Extraction Engine  v5
===============================================================================

Author  : Prudhvi  |  Thoughtworks
Version : v5.1  (Async + Production-Hardened)
Stage   : 1 of 5  (Extract → Chunk → Enrich → Embed → Store)

-------------------------------------------------------------------------------
CHANGELOG
-------------------------------------------------------------------------------

v5.1  (current)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  FIX 1 — PERF  Docling converter cold-start eliminated                 │
  │                                                                         │
  │  Root cause:  create_docling_converter() was called inside process_pdf()│
  │  on every document, reloading the RT-DETR layout model (~400 MB, ~15 s) │
  │  and TableFormer ACCURATE (~150 MB, ~10 s) from disk on every Ray task. │
  │                                                                         │
  │  Fix:  Lazy process-level singleton get_converter().  The models are    │
  │  loaded once per Ray worker process and reused for all documents on     │
  │  that worker.  For 50 docs × 4 workers: 4 model loads instead of 50.  │
  │  Saves ~25–40 s of pure initialization overhead per document.           │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  FIX 2 — BUG   process_code() return type annotation corrected         │
  │                                                                         │
  │  Was:   -> Tuple[str, Optional[str]]   (2-tuple)                        │
  │  Is:    -> Tuple[str, str, str, List[str]]  (4-tuple: id/text/lang/bc)  │
  │                                                                         │
  │  The wrong annotation caused mypy/pyright to emit false-positive errors │
  │  on every call-site in process_page() where the 4-tuple is unpacked.   │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  FIX 3 — BUG   tables/ output subdirectory now created at startup      │
  │                                                                         │
  │  pages/ and figures/ were created; tables/ was missing.                │
  │  S3 table uploads worked (write directly to S3, not local disk) but    │
  │  any future local table .md write would fail with FileNotFoundError.   │
  │  Added mkdir alongside pages/ and figures/ for structural consistency. │
  └─────────────────────────────────────────────────────────────────────────┘

v5.0
  Original async production-hardened release.  RT-DETR layout analysis,
  TableFormer ACCURATE table extraction, GPT-4o image/table enrichment,
  GPT-4o-mini formula/code enrichment, boundary-marker wrapping, S3
  upload per element, per-page asyncio.gather() concurrency.

-------------------------------------------------------------------------------
SINGLE RESPONSIBILITY
-------------------------------------------------------------------------------

This module owns exactly three tightly-coupled concerns:

  1. EXTRACT
     ─────────
     Uses Docling's ML layout model to identify and classify every structural
     element in the PDF without regex heuristics:

       • Section headers   (level-aware breadcrumb trail)
       • Paragraphs        (text body)
       • List items        (bullet / enumeration)
       • Tables            (text-first; image fallback for complex layouts)
       • Images / Figures  (PNG at 216 DPI)
       • Mathematical formulas
       • Code blocks

     Noise elements (PAGE_HEADER, PAGE_FOOTER) are discarded by Docling label,
     not by string matching — works on any PDF, any domain, any language.

  2. ENRICH  (Async)
     ──────────────────
     Generates AI descriptions for elements whose raw text embeds poorly
     in vector space.  All four enrichment types run concurrently per page:

       • Tables   →  7-dimension analytical narrative
                     gpt-4o  |  1500–3000 chars  |  always
       • Images   →  6-dimension visual analysis
                     gpt-4o Vision  |  1000–2000 chars  |  always
       • Formulas →  3-dimension semantic interpretation
                     gpt-4o-mini  |  200–500 chars  |  always
                     (raw math symbols embed as near-random vectors)
       • Code     →  3-dimension plain-language explanation
                     gpt-4o-mini  |  200–500 chars
                     (only for blocks > CODE_DESCRIPTION_MIN_LEN chars)

     Every AI call is:
       • Timeout-protected  (OPENAI_TIMEOUT seconds)
       • Rate-limit-aware   (exponential back-off, MAX_RETRIES attempts)
       • Gracefully degrading (failure → stub string, pipeline continues)

  3. UPLOAD
     ────────
     Uploads every asset to S3 immediately after extraction so that Stage 2
     (the chunker) can run on a completely different ECS / Fargate worker:

       • Table Markdown  →  {doc_id}/tables/{id}.md
       • Image PNG       →  {doc_id}/images/{filename}
       • Page .md files  →  {doc_id}/pages/page_N.md
       • metadata.json   →  {doc_id}/metadata.json

     The S3 URI is written into the boundary marker attribute s3_uri="…"
     so Stage 2 reads it directly from the .md file — zero boto3 dependency
     in the chunker.

-------------------------------------------------------------------------------
WHY ASYNC HERE
-------------------------------------------------------------------------------

A 50-page clinical trial protocol may contain:
  • 20 tables  → 20 × gpt-4o calls  (~3 s each)
  • 15 images  → 15 × gpt-4o-vision calls  (~4 s each)
  •  8 formulas → 8 × gpt-4o-mini calls  (~1 s each)

Sequential execution: ~130 s of wall-clock wait.
asyncio.gather() over all items on a page: ~max(individual latencies) ≈ 4–6 s.

The Docling conversion itself is synchronous (CPU-bound, no benefit from
async). Only the OpenAI enrichment calls run concurrently.

-------------------------------------------------------------------------------
DISPATCH ORDER  (critical — do not reorder)
-------------------------------------------------------------------------------

Within each page, items are dispatched in this exact order:

  1. _SKIP_LABELS       PAGE_HEADER, PAGE_FOOTER  → discard
  2. DocItemLabel.CODE  → process_code()
  3. DocItemLabel.FORMULA → process_formula()
  4. SectionHeaderItem  → process_header()   ← MUST be before TextItem
  5. ListItem           → process_list()     ← MUST be before TextItem
  6. TextItem           → process_text()     ← catch-all for paragraphs
  7. PictureItem        → process_image()
  8. TableItem          → process_table()

Rules 4 and 5 are safety-critical: SectionHeaderItem and ListItem are
TextItem subclasses.  Checking isinstance(item, TextItem) first would
silently route them as plain paragraphs, losing header depth and list markers.

Rules 2 and 3 are checked by label BEFORE any isinstance() test because
Docling may represent CODE / FORMULA as plain TextItem with a label rather
than a dedicated subclass.

-------------------------------------------------------------------------------
BOUNDARY CONTRACT
-------------------------------------------------------------------------------

Every extracted element is wrapped in a single-line HTML comment pair:

  <!-- BOUNDARY_START type="table" id="p3_table_1" page="3" rows="8"
       columns="5" has_caption="yes"
       breadcrumbs="Results &gt; Efficacy"
       s3_uri="s3://bucket/doc/tables/p3_table_1.md"
       ai_description="1. PURPOSE &#x2014; ..." -->
  | raw markdown table |
  <!-- BOUNDARY_END type="table" id="p3_table_1" -->

Attribute encoding rules (written here, reversed by html.unescape in Stage 2):
  •  "  →  &quot;   (GPT output contains column names, quoted phrases)
  •  \n →  space    (boundary markers must stay single-line for regex parsing)
  •  \r →  space    (Windows carriage returns)

AI descriptions are stored ONLY as boundary attributes — never embedded in
the raw content body.  This keeps the S3-stored raw content clean and lets
Stage 2 decide independently which representation to use for the VDB.

-------------------------------------------------------------------------------
OUTPUT LAYOUT (local + S3 mirror)
-------------------------------------------------------------------------------

Local (temporary worker storage):
  output/<pdf_stem>/
    ├── pages/
    │     ├── page_1.md
    │     └── page_N.md
    ├── figures/
    │     └── fig_p3_1.png
    └── metadata.json

S3 (permanent):
  s3://<bucket>/<doc_id>/
    ├── pages/page_1.md … page_N.md
    ├── tables/p3_table_1.md …
    ├── images/fig_p3_1.png …
    └── metadata.json

-------------------------------------------------------------------------------
"""

# ==============================================================================
# STANDARD LIBRARY
# ==============================================================================

import sys
import json
import html
import base64
import asyncio
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ==============================================================================
# THIRD-PARTY IMPORTS
# ==============================================================================

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat, DocItemLabel
    from docling.datamodel.document import (
        TableItem,
        PictureItem,
        TextItem,
        SectionHeaderItem,
        ListItem,
    )
    from openai import AsyncOpenAI, RateLimitError
    import boto3
    import pandas as pd
except ImportError as exc:
    # Surface a clear install command rather than an opaque ImportError traceback.
    print(f"\n{'='*70}")
    print("ERROR: Missing required dependency")
    print(f"{'='*70}")
    print(f"  {exc}")
    print("\nInstall all dependencies:")
    print("  pip install docling openai boto3 pandas tabulate")
    print(f"{'='*70}\n")
    sys.exit(1)


# ==============================================================================
# LOGGING
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Output root when running locally / without an explicit --output argument.
OUTPUT_DIR = "extracted_docs_bounded"

# gpt-4o handles tables (text reasoning) and images (vision).
# gpt-4o-mini handles formulas and code — shorter context, cheaper, sufficient.
OPENAI_MODEL      = "gpt-4o"
OPENAI_MINI_MODEL = "gpt-4o-mini"

# Docling renders page images at 72 DPI × IMAGE_SCALE.
# 3.0 → 216 DPI: fine enough for GPT-4o Vision to read axis labels, small
# table text, and formula notation without compression artefacts.
IMAGE_SCALE = 3.0

# Per-call timeout for every OpenAI API request (seconds).
# Clinical PDFs can have large tables that produce long prompts;
# 60 s gives the model enough time without hanging the pipeline indefinitely.
OPENAI_TIMEOUT = 60

# Maximum number of retry attempts on RateLimitError before giving up.
# Back-off: 2^attempt seconds  (1 s, 2 s, 4 s).
MAX_RETRIES = 3

# Code blocks shorter than this threshold are emitted as-is — their raw
# keyword tokens embed adequately in vector space.  Longer blocks (PK models,
# SAS macros, full stat scripts) need a plain-language description because
# users search "mixed-effects model" not "lme4::lmer(response ~ …)".
CODE_DESCRIPTION_MIN_LEN = 200


# ==============================================================================
# NOISE-FILTERING LABELS
# ==============================================================================
#
# Docling's ML layout model assigns DocItemLabel.PAGE_HEADER and PAGE_FOOTER
# to repeating page-level boilerplate: running headers such as
# "Protocol MK-3475 Amendment 5 Confidential", page numbers, footer text.
#
# These are discarded at the dispatch level — no regex, no keyword matching.
# Works on any PDF, any domain, any language; Docling's model did the work.
#
_SKIP_LABELS: frozenset = frozenset({
    DocItemLabel.PAGE_HEADER,
    DocItemLabel.PAGE_FOOTER,
})


# ==============================================================================
# AI ENRICHMENT PROMPTS
# ==============================================================================
#
# Design principles:
#   1. Explicit dimension labels force the model to cover every required aspect.
#      Without them the model produces 2-sentence summaries.
#   2. Minimum character targets are stated in the prompt AND enforced by
#      _enforce_length() after the call — belt-and-suspenders.
#   3. "Do NOT reproduce the raw content" prevents the model from simply
#      copying the input, which would waste tokens and produce useless embeddings.
#   4. AI descriptions are stored as boundary attributes, never in raw content,
#      so Stage 2 can choose independently what to put in the VDB.
#

_TABLE_PROMPT = """\
You are an expert medical/clinical document analyst specialising in
clinical-trial documentation and regulatory submissions.

Analyse the table below and write a DENSE, STRUCTURED description of
EXACTLY 1500–3000 characters.

Cover ALL seven dimensions — omitting any one is a failure:

1. PURPOSE    — What clinical question does this table answer?
                What endpoint, safety signal, or measurement does it present?
2. STRUCTURE  — Name every column header, its unit of measurement, data type
                (continuous, categorical, binary), and its analytical role.
                Note any row groupings, subgroup strata, or hierarchical levels.
3. FINDINGS   — The most important values, trends, and extremes.
                Quote specific numbers, percentages, and time-points.
4. STATISTICS — Report every p-value, confidence interval, odds ratio, hazard
                ratio, relative risk, NNT, or significance flag present.
5. COHORTS    — Identify every patient population, treatment arm, time-point,
                subgroup, and N size represented.
6. CAVEATS    — Note missing data, footnotes, abbreviations, and anything that
                qualifies the interpretation of the findings.
7. KEYWORDS   — List 12–15 precise clinical/statistical terms a physician or
                data scientist would use when searching for this table.

Formatting rules:
  • Label each section exactly as shown above (e.g. "1. PURPOSE — …").
  • Write in flowing prose within each section; no nested bullets.
  • Do NOT reproduce the raw table — synthesise and interpret.
  • Minimum 1500 characters total; responses below this are incomplete.

{caption_block}
Table (Markdown):
{table_markdown}
"""

_IMAGE_PROMPT = """\
You are an expert medical/clinical document analyst.

Analyse the figure and write a DENSE, STRUCTURED description of
EXACTLY 1000–2000 characters.

Cover ALL six dimensions:

1. FIGURE TYPE  — Identify the chart type precisely:
                  (Kaplan-Meier curve, forest plot, waterfall plot, bar chart,
                   scatter plot, study flowchart, dose-response curve, etc.)
2. CONTENT      — Describe every axis (label, scale, units), every legend
                  entry, every data series, and every visible annotation.
3. KEY MESSAGE  — State the single most important clinical takeaway.
4. DATA VALUES  — Quote specific numbers, percentages, time-points, medians,
                  response thresholds, or hazard ratios visible in the figure.
5. CONTEXT      — Explain how this figure relates to the surrounding document
                  section (efficacy, safety, PK, study design, etc.).
6. KEYWORDS     — List 10–12 precise search terms a clinician would use
                  to find this figure.

Formatting rules:
  • Label each section as shown above.
  • Minimum 1000 characters total.

{caption_block}
"""

_FORMULA_PROMPT = """\
You are an expert medical/scientific document analyst.

Interpret the formula below and write a concise structured description
of 200–500 characters.

Cover all three dimensions in a single flowing paragraph:

1. FORMULA TYPE  — What category of formula is this?
                   (pharmacokinetic, bioequivalence criterion, statistical
                    test, sample-size calculation, chemical equation, etc.)
2. MEANING       — What does each symbol or variable represent?
                   What quantity does the formula calculate or express?
3. CLINICAL USE  — What analytical decision, regulatory requirement, or
                   scientific measurement does this formula directly support?

Rules:
  • Write as ONE flowing paragraph — no numbered list in the output.
  • Do NOT reproduce the raw formula notation.
  • Minimum 200 characters; maximum 500 characters.

Formula:
{formula_text}
"""

_CODE_PROMPT = """\
You are a medical/statistical programming expert.

Explain the code block below in 200–500 characters.

Cover all three dimensions in a single flowing paragraph:

1. LANGUAGE/TYPE — What language or domain-specific tool is this?
                   (R, Python, SAS, NONMEM, SQL, shell, pseudocode, etc.)
2. PURPOSE       — What computation, statistical analysis, data transformation,
                   or modelling task does this code perform?
3. KEY ELEMENTS  — Which functions, libraries, statistical methods, or model
                   specifications are most significant?

Rules:
  • Write as ONE flowing paragraph — no numbered list in the output.
  • Do NOT reproduce any code.
  • Minimum 200 characters; maximum 500 characters.

Code:
{code_text}
"""


# ==============================================================================
# ID MANAGEMENT
# ==============================================================================

# Module-level counter dict — one set of counters per process.
# reset_id_counters() is called at the start of every document so IDs
# are unique within a document but may repeat across documents in the
# same process (that is fine — they are scoped by doc_id in S3 keys).
_id_counters: Dict[str, int] = defaultdict(int)


def generate_unique_id(page: int, item_type: str) -> str:
    """
    Generate a deterministic, page-scoped ID for a boundary marker.

    Format:  p{page}_{type}_{counter}
    Example: p3_table_1, p3_table_2, p5_image_1

    Counter is per (page, type) pair so IDs are short and human-readable
    in the .md file.  Reset between documents by reset_id_counters().
    """
    key = f"p{page}_{item_type}"
    _id_counters[key] += 1
    return f"{key}_{_id_counters[key]}"


def reset_id_counters() -> None:
    """
    Reset all ID counters.

    Must be called at the start of each document to prevent IDs from a
    previous document leaking into the current one within the same process.
    """
    global _id_counters
    _id_counters = defaultdict(int)


# ==============================================================================
# BOUNDARY MARKER UTILITIES
# ==============================================================================

def _escape_attr(value) -> str:
    """
    Encode a value for safe embedding as an HTML comment attribute.

    Two transforms applied in order:
      1. Collapse all newline variants (\\r\\n, \\r, \\n) to a single space.
         Boundary markers are parsed line-by-line; a multi-line attribute
         value would split the opening comment tag across lines and break
         the regex parser in Stage 2.
      2. HTML-escape double-quotes: " → &quot;
         GPT-4o output routinely contains quoted clinical terms such as
         "intent-to-treat", column names like "p-value", or abbreviations
         like "CI (95%)".  A raw " inside an attribute value would close
         the attribute early, silently truncating the AI description.

    Stage 2 (comprehensive_chunker.py) calls html.unescape() after
    extracting attribute values to reverse both transforms.
    """
    s = str(value).replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    return html.escape(s)


def _build_attr_string(item_type: str, item_id: str, page: int,
                        attrs: Dict) -> str:
    """
    Assemble the full attribute string for a BOUNDARY_START comment.

    type, id, and page are always written first (in that order) so the
    Stage 2 parser can rely on their position for fast extraction.
    Additional attrs follow in insertion order.
    None-valued attrs are dropped — writing 'None' as a string would
    corrupt downstream parsing.
    """
    parts = [
        f'type="{item_type}"',
        f'id="{item_id}"',
        f'page="{page}"',
    ]
    for k, v in attrs.items():
        if v is not None:
            parts.append(f'{k}="{_escape_attr(v)}"')
    return " ".join(parts)


def wrap_with_boundaries(content: str, item_type: str,
                          item_id: str, page: int, **attrs) -> str:
    """
    Wrap raw content between deterministic HTML-comment boundary markers.

    The opening marker encodes all structural metadata as escaped attributes.
    The closing marker carries only type and id for lightweight parsing.

    Example output:
      <!-- BOUNDARY_START type="paragraph" id="p2_text_1" page="2"
           char_count="312" breadcrumbs="Methods &gt; Study Design" -->
      The study enrolled patients aged 18–75…
      <!-- BOUNDARY_END type="paragraph" id="p2_text_1" -->
    """
    attr_string = _build_attr_string(item_type, item_id, page, attrs)
    start = f"<!-- BOUNDARY_START {attr_string} -->"
    end   = f'<!-- BOUNDARY_END type="{item_type}" id="{item_id}" -->'
    return f"{start}\n{content}\n{end}"


# ==============================================================================
# S3 UPLOAD
# ==============================================================================

def upload_to_s3(s3_client, bucket: str, key: str,
                 body: bytes, content_type: str) -> str:
    """
    Upload a byte payload to S3 and return the canonical s3:// URI.

    Raises on any failure — all call-sites wrap in try/except so a single
    failed upload stores an empty s3_uri in the boundary attr rather than
    crashing the entire document pipeline.

    Args:
        s3_client    : boto3 S3 client
        bucket       : S3 bucket name
        key          : object key (path within the bucket)
        body         : raw bytes to upload
        content_type : MIME type for the Content-Type header

    Returns:
        "s3://{bucket}/{key}"
    """
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )
    uri = f"s3://{bucket}/{key}"
    logger.info("S3 upload  ✓  %s  (%d bytes)", uri, len(body))
    return uri


# ==============================================================================
# DOCLING CONVERTER FACTORY
# ==============================================================================

def create_docling_converter() -> DocumentConverter:
    """
    Build and return a configured Docling DocumentConverter.

    Pipeline settings:
      • TABLE_FORMER ACCURATE mode  — highest-fidelity table structure
        recognition; slower than FAST but essential for clinical tables with
        merged cells, multi-level headers, and footnote rows.
      • generate_picture_images = True  — Docling renders each PictureItem
        to a PIL Image object accessible via item.get_image(doc).
      • generate_table_images = True    — enables image fallback for tables
        whose structure cannot be exported to a DataFrame.
      • images_scale = IMAGE_SCALE     — 3× = 216 DPI; legible for GPT-4o
        Vision without making payload sizes unmanageable.
      • do_ocr = False                 — assumes born-digital PDFs.
        Set True for scanned documents (significantly slower).
    """
    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.images_scale            = IMAGE_SCALE
    pipeline_opts.generate_picture_images = True
    pipeline_opts.generate_table_images   = True
    pipeline_opts.do_ocr                  = False
    pipeline_opts.do_table_structure      = True
    pipeline_opts.table_structure_options.mode = TableFormerMode.ACCURATE

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
        }
    )


# ==============================================================================
# CONVERTER SINGLETON  (lazy — initialized once per worker process)
# ==============================================================================
#
# WHY THIS MATTERS
# ----------------
# DocumentConverter.__init__() downloads and loads Docling's ML models:
#   • RT-DETR layout model       (~400 MB, ~15 s to load from disk)
#   • TableFormer ACCURATE mode  (~150 MB, ~10 s to load from disk)
#   • EasyOCR (if do_ocr=True)   (~200 MB, ~15 s — disabled here)
#
# In a Ray worker process, each @ray.remote task invocation calls process_pdf()
# for a new document.  Without this singleton, every document re-loads all
# models from scratch — adding 25–40 s of pure initialization overhead per
# document regardless of how fast the actual extraction runs.
#
# With the singleton the cost is paid ONCE per worker process (not per
# document).  Ray reuses worker processes across tasks in the same cluster,
# so for a batch of 50 documents using 4 workers:
#
#   Without singleton:  50 × 25 s  = 1 250 s  of model-loading time wasted
#   With singleton:      4 × 25 s  =   100 s  of model-loading time (once per worker)
#
# THREAD SAFETY
# -------------
# Each Ray worker is a single-threaded Python process.  Ray's default task
# executor dispatches one @ray.remote call at a time per worker, so there is
# no concurrent access to _converter_instance within a process.
# The lazy initialization is therefore safe without a lock.
#
# RESET (testing only)
# --------------------
# _reset_converter() forces re-initialization on the next get_converter() call.
# Only needed in test suites that require a fresh converter state in the same
# process.  Never called during normal pipeline operation.

_converter_instance: Optional[DocumentConverter] = None


def get_converter() -> DocumentConverter:
    """
    Return the process-level Docling DocumentConverter singleton.

    Initializes on first call (lazy) and reuses the same instance on all
    subsequent calls within the same Ray worker process.  Eliminates the
    25–40 s model-loading cold start that would otherwise occur on every
    document extraction.

    Usage in process_pdf():
        converter = get_converter()   # fast after first call
        doc       = converter.convert(pdf_path).document

    Returns:
        The singleton DocumentConverter configured with:
          • TableFormer ACCURATE (highest-fidelity table structure recognition)
          • 216 DPI image rendering (3× scale, legible for GPT-4o Vision)
          • do_ocr = False (born-digital PDFs — set True for scanned docs)
    """
    global _converter_instance
    if _converter_instance is None:
        logger.info(
            "Initializing Docling DocumentConverter "
            "(first document in this Ray worker — loading ML models)…"
        )
        t0 = time.monotonic()
        _converter_instance = create_docling_converter()
        logger.info(
            "Docling converter ready — models loaded in %.1f s",
            time.monotonic() - t0,
        )
    return _converter_instance


def _reset_converter() -> None:
    """
    Force the singleton to be re-initialized on the next get_converter() call.

    Only needed in test suites that require a fresh converter state in the
    same process.  Not called during normal pipeline operation.
    """
    global _converter_instance
    _converter_instance = None
    logger.debug("Docling converter singleton reset (next call will re-initialize)")


# ==============================================================================
# ASYNC RETRY WRAPPER
# ==============================================================================

async def _call_with_retry(fn, label: str = "OpenAI"):
    """
    Execute an async callable with exponential back-off on RateLimitError.

    Retries up to MAX_RETRIES times.  On each RateLimitError the coroutine
    sleeps for 2^attempt seconds (1 s, 2 s, 4 s) before retrying.
    Any non-rate-limit exception propagates immediately — callers handle it.

    Args:
        fn    : zero-argument async callable that performs the OpenAI call
        label : human-readable label for log messages (table id, image name…)

    Returns:
        The return value of fn() on success.

    Raises:
        RuntimeError if all retry attempts are exhausted.
        Any non-RateLimitError exception from fn().
    """
    for attempt in range(MAX_RETRIES):
        try:
            return await fn()
        except RateLimitError:
            wait = 2 ** attempt   # 1 s, 2 s, 4 s
            logger.warning(
                "%s  rate-limited on attempt %d/%d — retrying in %ds",
                label, attempt + 1, MAX_RETRIES, wait,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(
        f"{label}: all {MAX_RETRIES} retry attempts exhausted (rate limit)"
    )


def _enforce_length(text: str, min_chars: int, max_chars: int,
                    label: str = "") -> str:
    """
    Validate and optionally truncate an AI response.

    Logs a warning when the response is below the minimum (the model
    produced a cursory summary despite the prompt instruction).
    Truncates hard at max_chars — defensive guard against runaway output.

    Args:
        text      : raw AI response string
        min_chars : expected minimum length from the prompt specification
        max_chars : hard upper bound
        label     : context string for log messages

    Returns:
        The (possibly truncated) text.
    """
    if len(text) < min_chars:
        logger.warning(
            "AI response shorter than requested  label=%s  got=%d  min=%d",
            label, len(text), min_chars,
        )
    if len(text) > max_chars:
        logger.info(
            "AI response truncated  label=%s  from=%d  to=%d",
            label, len(text), max_chars,
        )
        text = text[:max_chars]
    return text


# ==============================================================================
# ASYNC AI ENRICHMENT FUNCTIONS
# ==============================================================================

async def describe_table_with_ai(
    table_markdown: str,
    client: AsyncOpenAI,
    caption: Optional[str] = None,
    label: str = "table",
) -> str:
    """
    Generate a structured 1500–3000-char analytical narrative for a table.

    Uses gpt-4o (text-only — no image needed for Markdown tables).
    The system message reinforces the length requirement independently of
    the user prompt as a second enforcement layer.

    Result is stored as the boundary attribute ai_description="…",
    NEVER embedded in the raw table content.  This keeps the S3-stored
    content clean and lets Stage 2 choose independently which representation
    to place in the VDB (raw table for small tables, ai_description for large).

    Args:
        table_markdown : Markdown-formatted table string from pandas
        client         : AsyncOpenAI client instance
        caption        : optional caption text extracted from the PDF
        label          : ID string used in log and error messages

    Returns:
        Structured description string, or a stub on failure.
    """
    caption_block = f"Caption: {caption}\n\n" if caption else ""
    prompt = _TABLE_PROMPT.format(
        caption_block=caption_block,
        table_markdown=table_markdown,
    )

    async def _call():
        return await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a medical document analyst specialising in "
                        "clinical-trial and regulatory documentation. "
                        "Always write descriptions of exactly 1500–3000 characters."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            timeout=OPENAI_TIMEOUT,
        )

    try:
        t0   = time.monotonic()
        resp = await _call_with_retry(_call, label=label)
        elapsed = time.monotonic() - t0
        logger.info("Table AI  ✓  %s  %.1fs", label, elapsed)
        result = resp.choices[0].message.content.strip()
        return _enforce_length(result, 1200, 3200, label)
    except Exception as exc:
        logger.error("Table AI description failed  %s: %s", label, exc)
        return f"AI description unavailable: {exc}"


async def describe_image_with_ai(
    image_path: Path,
    client: AsyncOpenAI,
    caption: Optional[str] = None,
    label: str = "image",
) -> str:
    """
    Generate a structured 1000–2000-char visual analysis of a figure.

    Reads the PNG from disk, encodes it as base64, and sends it to
    gpt-4o Vision at detail="high".  High detail is required for clinical
    figures: forest plots with small confidence-interval bars, Kaplan-Meier
    curves with multiple overlapping arms, and flowcharts with fine text.

    Result stored as boundary attribute ai_description="…".

    Args:
        image_path : absolute path to the saved PNG file
        client     : AsyncOpenAI client instance
        caption    : optional caption text
        label      : ID string for log messages

    Returns:
        Structured visual description string, or stub on failure.
    """
    caption_block = f"Caption: {caption}\n\n" if caption else ""
    prompt = _IMAGE_PROMPT.format(caption_block=caption_block)

    # Read bytes synchronously — image files are small (< 5 MB at 216 DPI)
    # and this avoids an aiofiles dependency.
    with open(image_path, "rb") as fh:
        b64_data = base64.b64encode(fh.read()).decode("utf-8")

    async def _call():
        return await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            # PNG encoded as a data URI — no external URL needed.
                            "url":    f"data:image/png;base64,{b64_data}",
                            "detail": "high",
                        },
                    },
                ],
            }],
            max_tokens=900,
            timeout=OPENAI_TIMEOUT,
        )

    try:
        t0   = time.monotonic()
        resp = await _call_with_retry(_call, label=label)
        elapsed = time.monotonic() - t0
        logger.info("Image AI  ✓  %s  %.1fs", label, elapsed)
        result = resp.choices[0].message.content.strip()
        return _enforce_length(result, 800, 2100, label)
    except Exception as exc:
        logger.error("Image AI description failed  %s: %s", label, exc)
        return f"AI description unavailable: {exc}"


async def describe_formula_with_ai(
    formula_text: str,
    client: AsyncOpenAI,
    label: str = "formula",
) -> str:
    """
    Generate a concise 200–500-char semantic interpretation of a formula.

    Why formulas always receive descriptions:
      Raw formula notation (LaTeX, Unicode math symbols, NONMEM syntax) produces
      near-random vector embeddings because tokenisers split on symbols.
      A user querying "pharmacokinetic elimination rate constant" will never
      semantically match "ke = ln(2) / t½".  The description translates the
      notation into searchable clinical language while the raw formula is
      preserved in the boundary content for exact-match retrieval.

    Uses gpt-4o-mini — formulas are short, no vision needed, cheaper.

    Args:
        formula_text : raw formula string as extracted by Docling
        client       : AsyncOpenAI client instance
        label        : ID string for log messages

    Returns:
        Plain-language description, or stub on failure.
    """
    prompt = _FORMULA_PROMPT.format(formula_text=formula_text)

    async def _call():
        return await client.chat.completions.create(
            model=OPENAI_MINI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            timeout=OPENAI_TIMEOUT,
        )

    try:
        t0   = time.monotonic()
        resp = await _call_with_retry(_call, label=label)
        elapsed = time.monotonic() - t0
        logger.info("Formula AI  ✓  %s  %.1fs", label, elapsed)
        result = resp.choices[0].message.content.strip()
        return _enforce_length(result, 150, 550, label)
    except Exception as exc:
        logger.error("Formula AI description failed  %s: %s", label, exc)
        return f"AI description unavailable: {exc}"


async def describe_code_with_ai(
    code_text: str,
    client: AsyncOpenAI,
    label: str = "code",
) -> str:
    """
    Generate a concise 200–500-char plain-language explanation of a code block.

    Only called for blocks exceeding CODE_DESCRIPTION_MIN_LEN (200) characters.
    Short snippets (1–3 lines) embed adequately on their raw keyword tokens.
    Long blocks such as full NONMEM control streams, multi-step SAS macros,
    or PK/PD model definitions need a natural-language bridge because users
    search "non-linear mixed effects PK model" not "$THETA (0.1)".

    Uses gpt-4o-mini — no vision, text-only, cheaper.

    Args:
        code_text : raw code string extracted by Docling
        client    : AsyncOpenAI client instance
        label     : ID string for log messages

    Returns:
        Plain-language explanation, or stub on failure.
    """
    prompt = _CODE_PROMPT.format(code_text=code_text)

    async def _call():
        return await client.chat.completions.create(
            model=OPENAI_MINI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            timeout=OPENAI_TIMEOUT,
        )

    try:
        t0   = time.monotonic()
        resp = await _call_with_retry(_call, label=label)
        elapsed = time.monotonic() - t0
        logger.info("Code AI  ✓  %s  %.1fs", label, elapsed)
        result = resp.choices[0].message.content.strip()
        return _enforce_length(result, 150, 550, label)
    except Exception as exc:
        logger.error("Code AI description failed  %s: %s", label, exc)
        return f"AI description unavailable: {exc}"


# ==============================================================================
# IMAGE / TABLE-AS-IMAGE EXTRACTION
# ==============================================================================

async def _extract_and_save_image(
    item,
    doc,
    page_num: int,
    output_dir: Path,
    filename: str,
    client: AsyncOpenAI,
    s3_client,
    s3_bucket: str,
    doc_id: str,
    caption: Optional[str],
    is_table: bool,
) -> Optional[Tuple[str, str, str, str]]:
    """
    Render a Docling item to PNG, save locally, upload to S3, describe with AI.

    This function is the single shared rendering path used by both
    process_image() and process_table() (image fallback).

    Flow:
      1. item.get_image(doc)   → PIL Image object from Docling
      2. Save as PNG at 216 DPI to figures/{filename}
      3. Upload PNG to  s3://{bucket}/{doc_id}/images/{filename}
      4. Call describe_image_with_ai() for the 6-dimension visual analysis

    PNG is used (not JPEG) because:
      • Lossless — no compression artefacts on fine text, thin lines,
        or low-contrast labels (common in clinical figures).
      • GPT-4o Vision accuracy is measurably better on PNG for documents
        with small axis labels and overlapping KM curve annotations.

    Args:
        item       : Docling PictureItem or TableItem
        doc        : Docling Document object (needed for rendering)
        page_num   : current page number (for logging / S3 key)
        output_dir : local root for this document's output
        filename   : pre-computed filename (e.g. "fig_p3_1.png")
        client     : AsyncOpenAI client
        s3_client  : boto3 S3 client (may be None for local-only runs)
        s3_bucket  : S3 bucket name
        doc_id     : document identifier used as S3 key prefix
        caption    : caption text consumed from the adjacent CAPTION item
        is_table   : True when this is a table rendered as an image (fallback)

    Returns:
        (filename, s3_uri, ai_description, type_label)  or  None on failure.
    """
    try:
        img_obj = item.get_image(doc)
        if img_obj is None:
            logger.warning(
                "get_image() returned None  page=%d  file=%s", page_num, filename
            )
            return None

        # ── Save PNG locally ───────────────────────────────────────────────────
        local_path = output_dir / "figures" / filename
        img_obj.save(local_path)  # Docling image objects save as PNG by default
        logger.debug("Saved image locally: %s", local_path)

        # ── Upload PNG to S3 ───────────────────────────────────────────────────
        # s3_uri is empty string if S3 is not configured.
        # Stored as boundary attr; Stage 2 passes it through to chunk metadata.
        s3_uri = ""
        if s3_client and s3_bucket:
            try:
                s3_key = f"{doc_id}/images/{filename}"
                s3_uri = upload_to_s3(
                    s3_client, s3_bucket, s3_key,
                    local_path.read_bytes(), "image/png",
                )
            except Exception as s3_exc:
                # Non-fatal: the image is still locally available for AI description.
                # The boundary attr will have an empty s3_uri; Stage 2 handles this.
                logger.error(
                    "S3 image upload failed  file=%s  error=%s", filename, s3_exc
                )

        # ── Generate AI description ────────────────────────────────────────────
        ai_desc    = await describe_image_with_ai(local_path, client, caption,
                                                   label=filename)
        type_label = "Table/Chart" if is_table else "Image"
        return filename, s3_uri, ai_desc, type_label

    except Exception as exc:
        logger.error(
            "Image extraction failed  page=%d  file=%s  error=%s",
            page_num, filename, exc,
        )
        return None


# ==============================================================================
# ITEM PROCESSORS  (one per Docling element type)
# ==============================================================================

def process_header(
    item: SectionHeaderItem,
    page: int,
    level: int,
    breadcrumbs: List[str],
) -> Tuple[str, List[str]]:
    """
    Process a section header and emit a Markdown heading with boundary markers.

    Breadcrumb trail update:
      The breadcrumb list represents the current nesting path.
      Before appending the new heading text, trim the list to the parent depth:

        level=1  →  breadcrumbs becomes [text]
        level=2  →  breadcrumbs becomes [prev_level1, text]
        level=3  →  breadcrumbs becomes [prev_1, prev_2, text]

      This means navigating from "Methods > Design" to a new level-1 heading
      "Results" correctly resets the trail to ["Results"] rather than
      producing "Methods > Design > Results".

    Heading depth mapping:
      Docling level 1 → ## (h2)  —  # (h1) is reserved for the document title
      Docling level 2 → ###
      Docling level N → {'#' * (N+1)}

    Args:
        item        : SectionHeaderItem from Docling
        page        : current page number
        level       : heading depth from doc.iterate_items()
        breadcrumbs : mutable breadcrumb trail from the outer loop

    Returns:
        (boundary-wrapped heading string, updated breadcrumbs list)
    """
    text = item.text.strip()

    # Trim trail to parent depth, then append current heading.
    if len(breadcrumbs) >= level:
        breadcrumbs = breadcrumbs[:level - 1]
    breadcrumbs.append(text)

    # Heading markdown: level 1 → "## Heading", level 2 → "### Heading"
    heading_md = f"{'#' * (level + 1)} {text}"
    item_id    = generate_unique_id(page, "header")

    output = wrap_with_boundaries(
        heading_md, "header", item_id, page,
        level=level,
        breadcrumbs=" > ".join(breadcrumbs),
    )
    return output, breadcrumbs


def process_text(
    item: TextItem,
    page: int,
    breadcrumbs: List[str],
) -> str:
    """
    Process a generic text element (paragraph, title, caption, footnote).

    PAGE_HEADER and PAGE_FOOTER items are silently discarded here as a
    second-line defence, even though the dispatch loop already skips them
    by label.  This guards against Docling reclassifying a label in a
    future release without breaking the pipeline.

    Metadata stored in boundary attrs:
      • char_count  — used by Stage 2 for target-size accumulation
      • word_count  — diagnostic; not used by chunker logic
      • breadcrumbs — critical for Stage 2 section-boundary detection

    Args:
        item        : TextItem from Docling
        page        : current page number
        breadcrumbs : current breadcrumb trail

    Returns:
        Boundary-wrapped paragraph string, or empty string to skip.
    """
    # Belt-and-suspenders noise filter (primary filter is in the dispatch loop)
    if item.label in _SKIP_LABELS:
        return ""

    text = item.text.strip()
    if not text:
        return ""

    item_id = generate_unique_id(page, "text")
    return wrap_with_boundaries(
        text, "paragraph", item_id, page,
        char_count=len(text),
        word_count=len(text.split()),
        breadcrumbs=" > ".join(breadcrumbs),
    )


def process_list(
    item: ListItem,
    page: int,
    breadcrumbs: List[str],
) -> str:
    """
    Process a list item and preserve its original marker.

    ListItem is a TextItem subclass — it MUST be dispatched before the
    generic TextItem branch.  Routing via isinstance(item, TextItem) first
    would produce a paragraph boundary with the marker character embedded
    in the text, losing the structured list-item type.

    The enumeration marker (bullet "•", "-", or numeric "1.") comes from
    Docling's layout model, not from text parsing.

    Args:
        item        : ListItem from Docling
        page        : current page number
        breadcrumbs : current breadcrumb trail

    Returns:
        Boundary-wrapped list-item string.
    """
    # Docling exposes the list marker via item.enumeration when available.
    marker  = getattr(item, "enumeration", None) or "-"
    text    = item.text.strip()
    item_id = generate_unique_id(page, "list")

    return wrap_with_boundaries(
        f"{marker} {text}", "list", item_id, page,
        breadcrumbs=" > ".join(breadcrumbs),
    )


def process_code(
    item: TextItem,
    page: int,
    breadcrumbs: List[str],
    openai_client_sync,  # Kept as a placeholder; async call deferred to gather
) -> Tuple[str, str, str, List[str]]:
    """
    Extract a code block and return the data bundle needed for async enrichment.

    Returns a 4-tuple rather than a completed boundary string because the AI
    description call must be deferred — it is collected into the page-level
    asyncio.gather() for concurrent execution alongside all other AI calls on
    the page.  Awaiting it inline here would serialize the AI calls and
    eliminate the concurrency benefit.

    Return value unpacked in process_page() as:
        item_id, text, language, bc = process_code(item, page, breadcrumbs, None)

    Note on language detection:
      Docling exposes item.code_language when it can identify the language
      from context (e.g. from a preceding code-fence label or MIME type).
      We use this directly rather than attempting heuristic detection —
      no regex on keywords, no file extension guessing.

    Args:
        item              : TextItem with label DocItemLabel.CODE
        page              : current page number
        breadcrumbs       : current breadcrumb trail
        openai_client_sync: unused; kept for API symmetry with other processors

    Returns:
        Tuple of (item_id, code_text, language, breadcrumbs_copy).
        The caller uses these to assemble the boundary string after the
        asyncio.gather() returns the AI description.
    """
    text     = item.text.strip()
    language = getattr(item, "code_language", None) or ""
    item_id  = generate_unique_id(page, "code")

    # The boundary is assembled here WITHOUT ai_description.
    # The caller will re-assemble with the completed AI description.
    # We return (item_id, text, language, breadcrumbs) for the caller.
    # ── Simplified: process_code returns a complete bundle to the caller ───
    return item_id, text, language, breadcrumbs[:]


def process_formula(
    item: TextItem,
    page: int,
    breadcrumbs: List[str],
) -> Tuple[str, str, List[str]]:
    """
    Extract a mathematical formula and return data needed for async enrichment.

    Why formulas ALWAYS get an AI description:
      Raw formula notation (LaTeX, Unicode, NONMEM syntax) tokenises into
      symbol fragments that produce near-random vector embeddings.
      The AI description is the primary VDB-searchable representation;
      the raw formula is preserved in boundary content for exact retrieval.

    Returns:
        (item_id, formula_text, breadcrumbs_copy)
        The caller awaits the enrichment coroutine and assembles the boundary.
    """
    text    = item.text.strip()
    item_id = generate_unique_id(page, "formula")
    return item_id, text, breadcrumbs[:]


# ==============================================================================
# ASYNC PAGE PROCESSOR
# ==============================================================================

async def process_page(
    page_num: int,
    items: List[Dict],
    doc,
    output_dir: Path,
    client: AsyncOpenAI,
    s3_client,
    s3_bucket: str,
    doc_id: str,
    breadcrumbs: List[str],
) -> Tuple[str, List[str], int, int]:
    """
    Process all items on a single page concurrently.

    Concurrency strategy:
      The Docling extraction step (headers, paragraphs, list items) is
      synchronous and fast — these run inline.
      AI enrichment calls (tables, images, formulas, code) are collected
      as coroutines first, then awaited together with asyncio.gather().
      This means all AI calls for a page execute concurrently, reducing
      wall-clock time from O(n×latency) to O(max_latency).

    Caption consumption:
      A TextItem with label DocItemLabel.CAPTION immediately following a
      PictureItem or TableItem is consumed by that element and not emitted
      as a standalone paragraph.  The look-ahead is done at the top of the
      item loop.

    Args:
        page_num    : page number (1-indexed, from Docling)
        items       : list of {"item": Docling item, "level": int} dicts
        doc         : Docling Document (needed for image rendering)
        output_dir  : local root directory for this document
        client      : AsyncOpenAI client
        s3_client   : boto3 S3 client (or None)
        s3_bucket   : S3 bucket name
        doc_id      : document identifier for S3 key construction
        breadcrumbs : breadcrumb trail carried in from previous pages (mutated)

    Returns:
        (page_markdown_text, updated_breadcrumbs, image_count, table_count)
    """
    # ── Synchronous first pass: extract structure, queue async tasks ───────────
    #
    # We separate the sync extraction from the async enrichment so that all
    # AI calls on the page can be gathered in one asyncio.gather() call.
    #
    # sync_outputs : list of (position_index, markdown_string)
    #                for elements that need no AI call
    # async_tasks  : list of (position_index, type, coroutine, metadata)
    #                for elements that require an async AI call
    #
    sync_outputs: List[Tuple[int, str]] = []
    async_tasks:  List[Tuple[int, str, any, Dict]] = []

    image_counter = 1
    image_count   = 0
    table_count   = 0
    skip_next     = False

    for idx, entry in enumerate(items):
        if skip_next:
            skip_next = False
            continue

        item  = entry["item"]
        level = entry["level"]
        label = item.label

        # ── Caption look-ahead ────────────────────────────────────────────────
        # A CAPTION TextItem immediately after a figure or table is consumed
        # by that element's processor so it becomes the caption= argument.
        # skip_next=True prevents it from also emitting as a paragraph.
        caption: Optional[str] = None
        if idx + 1 < len(items):
            next_item = items[idx + 1]["item"]
            if (isinstance(next_item, TextItem) and
                    next_item.label == DocItemLabel.CAPTION):
                caption   = next_item.text.strip()
                skip_next = True

        # ── 1. Discard page boilerplate ───────────────────────────────────────
        # PAGE_HEADER and PAGE_FOOTER are structural noise — running headers,
        # page numbers, confidentiality footers.  Discarded by label.
        if label in _SKIP_LABELS:
            continue

        # ── 2. Code blocks ────────────────────────────────────────────────────
        # Checked by label BEFORE isinstance(TextItem) because Docling may
        # represent code as a plain TextItem with label=CODE.
        elif label == DocItemLabel.CODE:
            item_id, text, language, bc = process_code(
                item, page_num, breadcrumbs, None
            )
            # Emit code boundary regardless of length.
            # AI description is added only if text exceeds threshold.
            if len(text) > CODE_DESCRIPTION_MIN_LEN:
                # Queue async AI description call.
                meta = {"item_id": item_id, "text": text,
                        "language": language, "breadcrumbs": bc}
                async_tasks.append((idx, "code", None, meta))
            else:
                # Short code block — emit immediately without description.
                output = wrap_with_boundaries(
                    f"```{language}\n{text}\n```",
                    "code", item_id, page_num,
                    language=language or "unknown",
                    breadcrumbs=" > ".join(bc),
                )
                sync_outputs.append((idx, output))

        # ── 3. Mathematical formulas ──────────────────────────────────────────
        elif label == DocItemLabel.FORMULA:
            item_id, text, bc = process_formula(item, page_num, breadcrumbs)
            meta = {"item_id": item_id, "text": text, "breadcrumbs": bc}
            async_tasks.append((idx, "formula", None, meta))

        # ── 4. Section headers ────────────────────────────────────────────────
        # MUST precede isinstance(TextItem) — SectionHeaderItem is a subclass.
        elif isinstance(item, SectionHeaderItem):
            output, breadcrumbs = process_header(item, page_num, level, breadcrumbs)
            if output:
                sync_outputs.append((idx, output))

        # ── 5. List items ─────────────────────────────────────────────────────
        # MUST precede isinstance(TextItem) — ListItem is a subclass.
        elif isinstance(item, ListItem):
            output = process_list(item, page_num, breadcrumbs)
            if output:
                sync_outputs.append((idx, output))

        # ── 6. Generic text (paragraphs, titles, footnotes) ───────────────────
        elif isinstance(item, TextItem):
            output = process_text(item, page_num, breadcrumbs)
            if output:
                sync_outputs.append((idx, output))

        # ── 7. Figures ────────────────────────────────────────────────────────
        elif isinstance(item, PictureItem):
            filename = f"fig_p{page_num}_{image_counter}.png"
            meta = {
                "item": item, "doc": doc, "filename": filename,
                "breadcrumbs": breadcrumbs[:], "caption": caption,
                "is_table": False,
            }
            async_tasks.append((idx, "image", None, meta))
            image_counter += 1
            image_count   += 1

        # ── 8. Tables ─────────────────────────────────────────────────────────
        elif isinstance(item, TableItem):
            # Attempt text export first; fall back to image rendering.
            try:
                df = item.export_to_dataframe()
                if df.empty or len(df) == 0 or len(df.columns) == 0:
                    raise ValueError("Empty dataframe")
                md_table = df.to_markdown(index=False)
                if len(md_table) <= 50:
                    raise ValueError("Trivially short markdown")

                item_id = generate_unique_id(page_num, "table")
                meta = {
                    "item_id": item_id, "md_table": md_table,
                    "rows": len(df), "columns": len(df.columns),
                    "breadcrumbs": breadcrumbs[:], "caption": caption,
                    "type": "table_text",
                }
                async_tasks.append((idx, "table_text", None, meta))
                table_count += 1
            except Exception:
                # Text export failed — render as image.
                filename = f"fig_p{page_num}_{image_counter}.png"
                meta = {
                    "item": item, "doc": doc, "filename": filename,
                    "breadcrumbs": breadcrumbs[:], "caption": caption,
                    "is_table": True,
                }
                async_tasks.append((idx, "image", None, meta))
                image_counter += 1
                table_count   += 1

    # ── Async second pass: run all AI calls for this page concurrently ─────────
    #
    # Build one coroutine per queued task and gather them.
    # Results come back in the same order as the input list.

    async def resolve_task(task_type: str, meta: Dict) -> str:
        """Resolve a single async task to its final boundary-marked string."""

        if task_type == "code":
            ai_desc = await describe_code_with_ai(
                meta["text"], client, label=meta["item_id"]
            )
            return wrap_with_boundaries(
                f"```{meta['language']}\n{meta['text']}\n```",
                "code", meta["item_id"], page_num,
                language=meta["language"] or "unknown",
                breadcrumbs=" > ".join(meta["breadcrumbs"]),
                ai_description=ai_desc,
            )

        elif task_type == "formula":
            ai_desc = await describe_formula_with_ai(
                meta["text"], client, label=meta["item_id"]
            )
            return wrap_with_boundaries(
                meta["text"], "formula", meta["item_id"], page_num,
                breadcrumbs=" > ".join(meta["breadcrumbs"]),
                ai_description=ai_desc,
            )

        elif task_type == "table_text":
            # Upload raw Markdown to S3 first (independent of AI call).
            s3_uri = ""
            if s3_client and s3_bucket:
                try:
                    s3_key = f"{doc_id}/tables/{meta['item_id']}.md"
                    s3_uri = upload_to_s3(
                        s3_client, s3_bucket, s3_key,
                        meta["md_table"].encode("utf-8"), "text/markdown",
                    )
                except Exception as exc:
                    logger.error(
                        "S3 table upload failed  id=%s  error=%s",
                        meta["item_id"], exc,
                    )

            ai_desc = await describe_table_with_ai(
                meta["md_table"], client,
                caption=meta["caption"], label=meta["item_id"],
            )

            parts = []
            if meta["caption"]:
                parts.append(f"*Caption:* {meta['caption']}")
            parts.append(meta["md_table"])

            return wrap_with_boundaries(
                "\n".join(parts), "table", meta["item_id"], page_num,
                rows=meta["rows"],
                columns=meta["columns"],
                has_caption="yes" if meta["caption"] else "no",
                breadcrumbs=" > ".join(meta["breadcrumbs"]),
                s3_uri=s3_uri or None,
                ai_description=ai_desc,
            )

        elif task_type == "image":
            result = await _extract_and_save_image(
                meta["item"], meta["doc"], page_num, output_dir,
                meta["filename"], client, s3_client, s3_bucket, doc_id,
                meta["caption"], meta["is_table"],
            )
            if result is None:
                return ""
            filename, s3_uri, ai_desc, type_label = result
            # Use a stable item_id (image_counter was already incremented above)
            item_id = generate_unique_id(page_num, "image_resolved")

            parts = [f"**{type_label}**"]
            if meta["caption"]:
                parts.append(f"*Caption:* {meta['caption']}")
            parts.append(f"![{filename}](../figures/{filename})")

            return wrap_with_boundaries(
                "\n".join(parts), "image", item_id, page_num,
                image_filename=filename,
                has_caption="yes" if meta["caption"] else "no",
                breadcrumbs=" > ".join(meta["breadcrumbs"]),
                s3_uri=s3_uri or None,
                ai_description=ai_desc,
            )

        return ""  # Unknown task type — emit nothing

    # Run all async tasks for the page in parallel.
    coroutines   = [resolve_task(tt, m) for (_, tt, _, m) in async_tasks]
    async_results: List[str] = await asyncio.gather(*coroutines)

    # ── Merge sync and async results in original document order ───────────────
    #
    # We reconstruct the page output in the order items appeared in the PDF.
    # sync_outputs has (original_idx, string) pairs.
    # async_tasks  has (original_idx, type, coro, meta) aligned with async_results.

    ordered: List[Tuple[int, str]] = list(sync_outputs)
    for i, (orig_idx, _, _, _) in enumerate(async_tasks):
        if async_results[i]:
            ordered.append((orig_idx, async_results[i]))

    # Sort by original item index to restore reading order.
    ordered.sort(key=lambda x: x[0])
    page_text = "\n\n".join(s for _, s in ordered if s)

    return page_text, breadcrumbs, image_count, table_count


# ==============================================================================
# MAIN PDF PIPELINE
# ==============================================================================

async def process_pdf(
    pdf_path: Path,
    output_base_dir: Path,
    client: AsyncOpenAI,
    s3_client=None,
    s3_bucket: str = "",
    doc_id: str = "",
) -> Dict:
    """
    Full async pipeline: Extract → Enrich → Upload for a single PDF.

    Processing stages:
      [1/4]  Docling layout analysis         (synchronous, CPU-bound)
      [2/4]  Group items by page             (synchronous, in-memory)
      [3/4]  Per-page async processing loop  (async AI calls per page)
      [4/4]  Write metadata.json + S3 upload (I/O)

    S3 uploads happen inline during stage 3 (table Markdown, image PNGs,
    per-page .md files) so each asset is durable before the next page starts.
    metadata.json is uploaded last in stage 4 as a completion marker — its
    presence in S3 signals to Stage 2 that extraction is finished.

    Args:
        pdf_path        : path to the PDF file
        output_base_dir : local directory to write extracted output under
        client          : AsyncOpenAI client
        s3_client       : boto3 S3 client (None for local-only runs)
        s3_bucket       : S3 bucket name (empty string for local-only)
        doc_id          : document identifier used as the S3 key prefix.
                          Defaults to pdf_path.stem when not provided.

    Returns:
        metadata dict written to metadata.json
    """
    t_start = time.monotonic()
    reset_id_counters()

    effective_doc_id = doc_id or pdf_path.stem
    doc_output_dir   = output_base_dir / pdf_path.stem

    # Create local output directories.
    # tables/ mirrors the S3 layout ({doc_id}/tables/) and ensures any future
    # local table-write code path works without FileNotFoundError.
    # pages/ and figures/ are used by the per-page processing loop.
    (doc_output_dir / "pages").mkdir(parents=True, exist_ok=True)
    (doc_output_dir / "figures").mkdir(parents=True, exist_ok=True)
    (doc_output_dir / "tables").mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Processing: %s", pdf_path.name)
    logger.info("Output:     %s", doc_output_dir)
    logger.info("=" * 60)

    # ── [1/4] Docling layout analysis ─────────────────────────────────────────
    # get_converter() returns the process-level singleton.  On first call in
    # this Ray worker process it loads the RT-DETR and TableFormer models
    # (25–40 s).  On all subsequent documents in the same worker the already-
    # loaded instance is returned immediately at near-zero cost.
    # See the CONVERTER SINGLETON section above for the full cost analysis.
    logger.info("[1/4] Analysing PDF layout with Docling…")
    converter = get_converter()
    doc       = converter.convert(pdf_path).document
    logger.info("[1/4] Layout analysis complete")

    # ── [2/4] Group items by page ──────────────────────────────────────────────
    # doc.iterate_items() yields (item, level) pairs.
    # level is the heading depth for SectionHeaderItem; ignored for other types.
    # We group into a dict keyed by page number for ordered page processing.
    logger.info("[2/4] Collecting document items…")
    pages_items: Dict[int, List[Dict]] = defaultdict(list)
    for item, level in doc.iterate_items():
        if not item.prov:
            # Items without provenance have no page association — skip.
            continue
        pages_items[item.prov[0].page_no].append({"item": item, "level": level})

    total_items = sum(len(v) for v in pages_items.values())
    logger.info("[2/4] %d items across %d pages", total_items, len(pages_items))

    # ── [3/4] Per-page async extraction + enrichment + upload ─────────────────
    logger.info("[3/4] Extracting, enriching, uploading (async)…")
    metadata_pages: List[Dict]    = []
    global_breadcrumbs: List[str] = []  # Carried across page boundaries
    total_images = 0
    total_tables = 0

    for page_num in sorted(pages_items.keys()):
        logger.info("  Page %d / %d…", page_num, max(pages_items.keys()))

        page_text, global_breadcrumbs, img_count, tbl_count = await process_page(
            page_num=page_num,
            items=pages_items[page_num],
            doc=doc,
            output_dir=doc_output_dir,
            client=client,
            s3_client=s3_client,
            s3_bucket=s3_bucket,
            doc_id=effective_doc_id,
            breadcrumbs=global_breadcrumbs,
        )

        # Write page .md to local disk.
        page_filename = f"page_{page_num}.md"
        local_page    = doc_output_dir / "pages" / page_filename
        local_page.write_text(page_text, encoding="utf-8")

        # Upload page .md to S3.
        if s3_client and s3_bucket:
            try:
                upload_to_s3(
                    s3_client, s3_bucket,
                    f"{effective_doc_id}/pages/{page_filename}",
                    page_text.encode("utf-8"), "text/markdown",
                )
            except Exception as exc:
                logger.error(
                    "S3 page upload failed  file=%s  error=%s", page_filename, exc
                )

        metadata_pages.append({
            "page":   page_num,
            "file":   page_filename,
            "images": img_count,
            "tables": tbl_count,
        })
        total_images += img_count
        total_tables += tbl_count

    elapsed = time.monotonic() - t_start
    logger.info(
        "[3/4] Complete  pages=%d  images=%d  tables=%d  elapsed=%.1fs",
        len(pages_items), total_images, total_tables, elapsed,
    )

    # ── [4/4] Metadata ─────────────────────────────────────────────────────────
    logger.info("[4/4] Writing metadata…")
    metadata = {
        "file":              pdf_path.name,
        "doc_id":            effective_doc_id,
        "processed":         datetime.now().isoformat(),
        "tool":              "docling_bounded_extractor_v5_async",
        "elapsed_seconds":   round(elapsed, 2),
        "pages":             metadata_pages,
        "total_images":      total_images,
        "total_tables":      total_tables,
    }

    meta_path = doc_output_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    if s3_client and s3_bucket:
        try:
            upload_to_s3(
                s3_client, s3_bucket,
                f"{effective_doc_id}/metadata.json",
                json.dumps(metadata, indent=2).encode("utf-8"), "application/json",
            )
            logger.info(
                "metadata.json uploaded to s3://%s/%s/metadata.json",
                s3_bucket, effective_doc_id,
            )
        except Exception as exc:
            logger.error("S3 metadata upload failed: %s", exc)

    logger.info("=" * 60)
    logger.info("EXTRACTION COMPLETE  %s", pdf_path.name)
    logger.info("  Pages:  %d", len(metadata_pages))
    logger.info("  Images: %d", total_images)
    logger.info("  Tables: %d", total_tables)
    logger.info("  Time:   %.1f s", elapsed)
    logger.info("=" * 60)

    return metadata


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

def main() -> None:
    """
    Command-line interface for running the extractor on one PDF or a directory.

    Usage examples:
      # Single PDF, local output only:
      python docling_pdf_extractor.py protocol.pdf

      # Single PDF with S3 upload:
      python docling_pdf_extractor.py protocol.pdf \\
          --bucket my-rag-bucket --doc-id trial-001

      # Entire directory of PDFs:
      python docling_pdf_extractor.py ./pdfs/ \\
          --output ./extracted --bucket my-rag-bucket

    The --doc-id flag controls the S3 key prefix.  If omitted, the PDF
    filename stem is used.  For batch processing, each PDF gets its own
    stem-based prefix automatically.
    """
    parser = argparse.ArgumentParser(
        description="Docling Boundary PDF Extractor v5 (Async)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s protocol.pdf\n"
            "  %(prog)s protocol.pdf --bucket my-bucket --doc-id trial-001\n"
            "  %(prog)s ./pdfs/ --output ./out --bucket my-bucket"
        ),
    )
    parser.add_argument("path",      type=Path,
                        help="PDF file or directory containing PDFs")
    parser.add_argument("--output",  type=Path, default=Path(OUTPUT_DIR),
                        help="Local output root directory")
    parser.add_argument("--bucket",  type=str,  default="",
                        help="S3 bucket name (omit for local-only)")
    parser.add_argument("--doc-id",  type=str,  default="",
                        help="S3 key prefix / document ID")
    parser.add_argument("--region",  type=str,  default="us-east-1",
                        help="AWS region for S3 client")
    args = parser.parse_args()

    # Initialise OpenAI async client.
    # Reads OPENAI_API_KEY from environment automatically.
    client = AsyncOpenAI()

    # Initialise S3 client only when a bucket is specified.
    s3_client = None
    if args.bucket:
        s3_client = boto3.client("s3", region_name=args.region)
        logger.info("S3 target: s3://%s/", args.bucket)

    # Resolve PDF file list.
    if args.path.is_file():
        pdf_files = [args.path]
    elif args.path.is_dir():
        pdf_files = sorted(args.path.glob("*.pdf"))
    else:
        logger.error("Path not found: %s", args.path)
        sys.exit(1)

    if not pdf_files:
        logger.error("No PDF files found at: %s", args.path)
        sys.exit(1)

    logger.info("Found %d PDF file(s) to process", len(pdf_files))

    ok_count   = 0
    fail_count = 0

    for pdf in pdf_files:
        try:
            asyncio.run(
                process_pdf(
                    pdf_path=pdf,
                    output_base_dir=args.output,
                    client=client,
                    s3_client=s3_client,
                    s3_bucket=args.bucket,
                    doc_id=args.doc_id or pdf.stem,
                )
            )
            ok_count += 1
        except Exception as exc:
            logger.error("FAILED  %s: %s", pdf.name, exc)
            fail_count += 1

    if len(pdf_files) > 1:
        logger.info(
            "Batch complete  success=%d  failed=%d  total=%d",
            ok_count, fail_count, len(pdf_files),
        )


if __name__ == "__main__":
    main()