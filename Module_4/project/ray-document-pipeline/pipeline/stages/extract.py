"""
===============================================================================
docling_bounded_extractor.py  -  Boundary-Based PDF Extraction Engine  v5.3
===============================================================================

Author  : Prudhvi  |  Thoughtworks
Stage   : 1 of 5  (Extract -> Chunk -> Enrich -> Embed -> Store)

-------------------------------------------------------------------------------
SINGLE RESPONSIBILITY
-------------------------------------------------------------------------------

This module owns exactly three tightly-coupled concerns:

  1. EXTRACT
     Uses Docling's ML layout model to identify and classify every structural
     element in the PDF without regex heuristics:
       - Section headers   (level-aware breadcrumb trail)
       - Paragraphs        (text body)
       - List items        (bullet / enumeration)
       - Tables            (text-first; image fallback for complex layouts)
       - Images / Figures  (PNG at 216 DPI)
       - Mathematical formulas
       - Code blocks
     Noise (PAGE_HEADER, PAGE_FOOTER) discarded by label.

  2. ENRICH  (Async)
     Generates AI descriptions for elements whose raw text embeds poorly in
     vector space. All enrichment calls run concurrently per page via
     asyncio.gather().
       - Tables   -> 7-dimension analytical narrative  (gpt-4o)
       - Images   -> 6-dimension visual analysis       (gpt-4o vision)
       - Formulas -> 3-dimension semantic interpretation (gpt-4o-mini)
       - Code     -> 3-dimension plain-language explanation (gpt-4o-mini)

  3. UPLOAD
     Uploads every asset to S3 immediately after extraction so Stage 2 can
     run on a completely different ECS/Fargate worker.

-------------------------------------------------------------------------------
STAGE 1 -> STAGE 2 CONTRACT
-------------------------------------------------------------------------------

Stage 1 writes ALL decisions as boundary marker attributes.
Stage 2 (comprehensive_chunker.py) reads those attributes — it never
re-generates descriptions or re-measures sizes.

Key attributes on every boundary marker:
  is_large="yes/no"     - Stage 2 routing signal (never re-measured by Stage 2)
  s3_uri="s3://..."     - raw asset pointer, passed through to Pinecone metadata
  ai_description="..."  - pre-generated description, used as VDB content by Stage 2
  breadcrumbs="..."     - section path for Stage 2 boundary detection

What Stage 1 puts in the .md body (inline content):

  Element              Body content
  ─────────────────────────────────────────────────────────────────────────
  Paragraph/header/    Raw text as-is
  list/formula/code
  ─────────────────────────────────────────────────────────────────────────
  Small table          Caption + AI description blockquote + full raw Markdown
                       Small tables stay in VDB as raw text; chunker merges
                       them with surrounding paragraphs
  ─────────────────────────────────────────────────────────────────────────
  Large table          Caption + AI description blockquote + cell dump
                       NO raw Markdown inline - lives in S3 only
                       Reason: chunker reads chunk['content'] to measure size.
                       65k raw table inline means chunker holds 65k per chunk
                       and slows regex parsing. Chunker discards it anyway
                       (uses ai_description for large tables). Writing it
                       inline is pure waste.
  ─────────────────────────────────────────────────────────────────────────
  Image                **Image** label + caption + ![filename](s3_uri)
                       + AI description as Markdown blockquote

-------------------------------------------------------------------------------
CELL DUMP (large tables only)
-------------------------------------------------------------------------------

_build_cell_dump() converts raw Markdown table to flat "Col: val | Col: val"
rows. This gives Stage 2 a compact, searchable representation:
  - Short enough to fit in one VDB chunk (~50 chars per row)
  - Column context present on every row (no split-chunk column-loss)
  - Gives the chunker real content to measure for chunk_size

The full raw Markdown is in S3 (s3_uri attr), fetched at query time for
precise numeric answers via the two-pass retrieval pattern.

-------------------------------------------------------------------------------
QUERY-TIME TWO-PASS RETRIEVAL FOR LARGE TABLES
-------------------------------------------------------------------------------

  Pass 1 (VDB):  description + cell dump -> semantic match
                 (description includes HR, p-values, CIs -> numeric queries find it)
  Pass 2 (S3):   query layer sees type="table_offloaded" + s3_uri
                 -> fetches raw Markdown -> LLM produces precise numeric answer

-------------------------------------------------------------------------------
CHANGELOG
-------------------------------------------------------------------------------

v5.3
  AI descriptions embedded as blockquotes in .md body.
  Large tables: cell dump replaces raw Markdown inline.
  _build_cell_dump() helper added.

v5.1
  Docling converter lazy process-level singleton eliminates cold-start.

v5.0
  Original async production-hardened release.
"""

# ==============================================================================
# STANDARD LIBRARY
# ==============================================================================

import sys
import io
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

OUTPUT_DIR        = "extracted_docs_bounded"
OPENAI_MODEL      = "gpt-4o"
OPENAI_MINI_MODEL = "gpt-4o-mini"
IMAGE_SCALE       = 3.0          # 216 DPI — high enough for GPT-4o vision
OPENAI_TIMEOUT    = 60
MAX_RETRIES       = 3
CODE_DESCRIPTION_MIN_LEN = 200

# Tables whose raw Markdown exceeds this are "large":
#   - Raw Markdown uploaded to S3
#   - Raw Markdown NOT written inline in .md body (cell dump written instead)
#   - Stage 2 reads is_large="yes" attr and routes standalone
#   - Stage 2 uses ai_description attr as VDB content
TABLE_LARGE_THRESHOLD_CHARS = 3000


# ==============================================================================
# NOISE-FILTERING LABELS
# ==============================================================================

_SKIP_LABELS: frozenset = frozenset({
    DocItemLabel.PAGE_HEADER,
    DocItemLabel.PAGE_FOOTER,
})


# ==============================================================================
# AI ENRICHMENT PROMPTS
# ==============================================================================

_TABLE_PROMPT = """\
You are an expert medical/clinical document analyst specialising in
clinical-trial documentation and regulatory submissions.

Analyse the table below and write a DENSE, STRUCTURED description of
EXACTLY 1500-3000 characters.

Cover ALL seven dimensions - omitting any one is a failure:

1. PURPOSE    - What clinical question does this table answer?
                What endpoint, safety signal, or measurement does it present?
2. STRUCTURE  - Name every column header, its unit of measurement, data type
                (continuous, categorical, binary), and its analytical role.
                Note any row groupings, subgroup strata, or hierarchical levels.
3. FINDINGS   - The most important values, trends, and extremes.
                Quote specific numbers, percentages, and time-points.
4. STATISTICS - Report every p-value, confidence interval, odds ratio, hazard
                ratio, relative risk, NNT, or significance flag present.
5. COHORTS    - Identify every patient population, treatment arm, time-point,
                subgroup, and N size represented.
6. CAVEATS    - Note missing data, footnotes, abbreviations, and anything that
                qualifies the interpretation of the findings.
7. KEYWORDS   - List 12-15 precise clinical/statistical terms a physician or
                data scientist would use when searching for this table.

Formatting rules:
  - Label each section exactly as shown above (e.g. "1. PURPOSE - ...").
  - Write in flowing prose within each section; no nested bullets.
  - Do NOT reproduce the raw table - synthesise and interpret.
  - Minimum 1500 characters total; responses below this are incomplete.

{caption_block}
Table (Markdown):
{table_markdown}
"""

_IMAGE_PROMPT = """\
You are an expert medical/clinical document analyst.

Analyse the figure and write a DENSE, STRUCTURED description of
EXACTLY 1000-2000 characters.

Cover ALL six dimensions:

1. FIGURE TYPE  - Identify the chart type precisely:
                  (Kaplan-Meier curve, forest plot, waterfall plot, bar chart,
                   scatter plot, study flowchart, dose-response curve, etc.)
2. CONTENT      - Describe every axis (label, scale, units), every legend
                  entry, every data series, and every visible annotation.
3. KEY MESSAGE  - State the single most important clinical takeaway.
4. DATA VALUES  - Quote specific numbers, percentages, time-points, medians,
                  response thresholds, or hazard ratios visible in the figure.
5. CONTEXT      - Explain how this figure relates to the surrounding document
                  section (efficacy, safety, PK, study design, etc.).
6. KEYWORDS     - List 10-12 precise search terms a clinician would use
                  to find this figure.

Formatting rules:
  - Label each section as shown above.
  - Minimum 1000 characters total.

{caption_block}
"""

_FORMULA_PROMPT = """\
You are an expert medical/scientific document analyst.

Interpret the formula below and write a concise structured description
of 200-500 characters.

Cover all three dimensions in a single flowing paragraph:

1. FORMULA TYPE  - What category of formula is this?
                   (pharmacokinetic, bioequivalence criterion, statistical
                    test, sample-size calculation, chemical equation, etc.)
2. MEANING       - What does each symbol or variable represent?
                   What quantity does the formula calculate or express?
3. CLINICAL USE  - What analytical decision, regulatory requirement, or
                   scientific measurement does this formula directly support?

Rules:
  - Write as ONE flowing paragraph - no numbered list in the output.
  - Do NOT reproduce the raw formula notation.
  - Minimum 200 characters; maximum 500 characters.

Formula:
{formula_text}
"""

_CODE_PROMPT = """\
You are a medical/statistical programming expert.

Explain the code block below in 200-500 characters.

Cover all three dimensions in a single flowing paragraph:

1. LANGUAGE/TYPE - What language or domain-specific tool is this?
                   (R, Python, SAS, NONMEM, SQL, shell, pseudocode, etc.)
2. PURPOSE       - What computation, statistical analysis, data transformation,
                   or modelling task does this code perform?
3. KEY ELEMENTS  - Which functions, libraries, statistical methods, or model
                   specifications are most significant?

Rules:
  - Write as ONE flowing paragraph - no numbered list in the output.
  - Do NOT reproduce any code.
  - Minimum 200 characters; maximum 500 characters.

Code:
{code_text}
"""


# ==============================================================================
# ID MANAGEMENT
# ==============================================================================

_id_counters: Dict[str, int] = defaultdict(int)


def generate_unique_id(page: int, item_type: str) -> str:
    """
    Generate a deterministic, page-scoped ID for a boundary marker.
    Format: p{page}_{type}_{counter}  e.g. p3_table_1, p5_image_1
    Reset between documents by reset_id_counters().
    """
    key = f"p{page}_{item_type}"
    _id_counters[key] += 1
    return f"{key}_{_id_counters[key]}"


def reset_id_counters() -> None:
    """Reset all ID counters. Call at the start of each document."""
    global _id_counters
    _id_counters = defaultdict(int)


# ==============================================================================
# BOUNDARY MARKER UTILITIES
# ==============================================================================

def _escape_attr(value) -> str:
    """
    Encode a value for safe embedding as an HTML comment attribute.
    Collapses newlines to spaces; HTML-escapes double-quotes and angle brackets.
    Stage 2 calls html.unescape() to reverse.
    """
    s = str(value).replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    return html.escape(s)


def _build_attr_string(item_type: str, item_id: str, page: int,
                        attrs: Dict) -> str:
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
    All structural metadata encoded as escaped attributes on the opening marker.
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
    """Upload bytes to S3 and return the canonical s3:// URI."""
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )
    uri = f"s3://{bucket}/{key}"
    logger.info("S3 upload  ok  %s  (%d bytes)", uri, len(body))
    return uri


# ==============================================================================
# CELL DUMP BUILDER
# ==============================================================================

def _build_cell_dump(md_table: str, item_id: str) -> str:
    """
    Build a flat "Col: val | Col: val" string from a Markdown table.

    Each row becomes one line with every non-empty cell prefixed by its
    column name. This gives the VDB a compact, searchable representation
    where column context is always present on every row — immune to the
    header-loss problem if the table were ever split mid-content.

    Used for LARGE TABLES ONLY. The result replaces the raw Markdown inline
    in the .md body. The full Markdown is in S3 (s3_uri attr).

    Why cell dump instead of raw Markdown for large tables:
      - Raw Markdown for a 50-row table = ~15-65k chars
      - Cell dump for the same table = ~2-5k chars
      - Both are searchable; cell dump fits in one VDB chunk
      - Column context on every row prevents query misses when column
        names are not in the embedded chunk

    Args:
        md_table : GFM Markdown table string from pandas / Docling
        item_id  : ID string for log messages only

    Returns:
        Multi-line string of "Col: val | Col: val" rows,
        or empty string if parsing fails (non-fatal).
    """
    try:
        df = pd.read_csv(
            io.StringIO(md_table),
            sep=r"\s*\|\s*",
            engine="python",
            skipinitialspace=True,
        )
        # Drop empty first/last columns produced by leading/trailing pipes
        df = df.loc[:, ~df.columns.str.fullmatch(r"\s*")]
        # Drop GFM separator row (---|---|---)
        df = df[~df.apply(
            lambda row: row.astype(str).str.fullmatch(r"[\-: ]+").all(), axis=1
        )]

        rows_text = []
        for _, row in df.iterrows():
            cell_pairs = " | ".join(
                f"{col.strip()}: {str(val).strip()}"
                for col, val in row.items()
                if str(val).strip() not in ("", "nan", "NaN", "None")
            )
            if cell_pairs:
                rows_text.append(cell_pairs)

        if rows_text:
            logger.debug("Cell dump built  id=%s  rows=%d", item_id, len(rows_text))
            return "\n".join(rows_text)

    except Exception as exc:
        logger.warning(
            "_build_cell_dump: failed for id=%s  error=%s - skipping cell dump",
            item_id, exc,
        )
    return ""


# ==============================================================================
# DOCLING CONVERTER FACTORY + SINGLETON
# ==============================================================================

def create_docling_converter() -> DocumentConverter:
    """
    Build and return a configured Docling DocumentConverter.
    TableFormer ACCURATE for highest-fidelity table structure recognition.
    216 DPI image rendering (3x scale) for GPT-4o Vision legibility.
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


_converter_instance: Optional[DocumentConverter] = None


def get_converter() -> DocumentConverter:
    """
    Return the process-level Docling DocumentConverter singleton.

    Models loaded once per Ray worker process (~25-40s on first call).
    All subsequent documents in the same worker reuse the loaded instance.
    Saves 25-40s per document for batches > 1.
    """
    global _converter_instance
    if _converter_instance is None:
        logger.info(
            "Initializing Docling DocumentConverter "
            "(first document in this Ray worker - loading ML models)..."
        )
        t0 = time.monotonic()
        _converter_instance = create_docling_converter()
        logger.info(
            "Docling converter ready - models loaded in %.1f s",
            time.monotonic() - t0,
        )
    return _converter_instance


def _reset_converter() -> None:
    """Force re-initialization on next get_converter() call. Test use only."""
    global _converter_instance
    _converter_instance = None
    logger.debug("Docling converter singleton reset")


# ==============================================================================
# ASYNC RETRY WRAPPER
# ==============================================================================

async def _call_with_retry(fn, label: str = "OpenAI"):
    """
    Execute an async callable with exponential back-off on RateLimitError.
    Retries up to MAX_RETRIES times: 1s, 2s, 4s back-off.
    """
    for attempt in range(MAX_RETRIES):
        try:
            return await fn()
        except RateLimitError:
            wait = 2 ** attempt
            logger.warning(
                "%s  rate-limited on attempt %d/%d - retrying in %ds",
                label, attempt + 1, MAX_RETRIES, wait,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(
        f"{label}: all {MAX_RETRIES} retry attempts exhausted (rate limit)"
    )


def _enforce_length(text: str, min_chars: int, max_chars: int,
                    label: str = "") -> str:
    """Validate and optionally truncate an AI response."""
    if len(text) < min_chars:
        logger.warning(
            "AI response shorter than requested  label=%s  got=%d  min=%d",
            label, len(text), min_chars,
        )
    if len(text) > max_chars:
        logger.info("AI response truncated  label=%s  from=%d  to=%d",
                    label, len(text), max_chars)
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
    Generate a structured 1500-3000-char analytical narrative for a table.

    The description covers 7 dimensions including key numeric values
    (HR, p-values, CIs) so that numeric queries ("hazard ratio arm B")
    find the right table chunk in the VDB.

    For LARGE tables: this description (embedded as a Markdown blockquote
    in the .md body) is what Stage 2 uses as VDB content. The raw table
    Markdown is in S3, fetched at query time for precise numeric answers.

    For SMALL tables: the description supplements the raw Markdown inline.
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
                        "Always write descriptions of exactly 1500-3000 characters."
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
        logger.info("Table AI  ok  %s  %.1fs", label, time.monotonic() - t0)
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
    Generate a structured 1000-2000-char visual analysis of a figure.
    Result embedded as a Markdown blockquote in the .md body.
    Stage 2 reads ai_description attr and uses it as VDB content.
    """
    caption_block = f"Caption: {caption}\n\n" if caption else ""
    prompt = _IMAGE_PROMPT.format(caption_block=caption_block)

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
        logger.info("Image AI  ok  %s  %.1fs", label, time.monotonic() - t0)
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
    Generate a concise 200-500-char semantic interpretation of a formula.
    Raw formula notation embeds as near-random vectors; description makes
    it semantically searchable.
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
        logger.info("Formula AI  ok  %s  %.1fs", label, time.monotonic() - t0)
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
    Generate a concise 200-500-char plain-language explanation of a code block.
    Only called for blocks exceeding CODE_DESCRIPTION_MIN_LEN characters.
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
        logger.info("Code AI  ok  %s  %.1fs", label, time.monotonic() - t0)
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

    Returns:
        (filename, s3_uri, ai_description, type_label) or None on failure.
    """
    try:
        img_obj = item.get_image(doc)
        if img_obj is None:
            logger.warning(
                "get_image() returned None  page=%d  file=%s", page_num, filename
            )
            return None

        local_path = output_dir / "figures" / filename
        img_obj.save(local_path)
        logger.debug("Saved image locally: %s", local_path)

        s3_uri = ""
        if s3_client and s3_bucket:
            try:
                s3_key = f"{doc_id}/images/{filename}"
                s3_uri = upload_to_s3(
                    s3_client, s3_bucket, s3_key,
                    local_path.read_bytes(), "image/png",
                )
            except Exception as s3_exc:
                logger.error(
                    "S3 image upload failed  file=%s  error=%s", filename, s3_exc
                )

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
    Updates and returns the breadcrumb trail.
    """
    text = item.text.strip()

    if len(breadcrumbs) >= level:
        breadcrumbs = breadcrumbs[:level - 1]
    breadcrumbs.append(text)

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
    """Process a generic text element (paragraph, title, caption, footnote)."""
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
    Process a list item. Dispatched before isinstance(TextItem) because
    ListItem is a TextItem subclass.
    """
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
) -> Tuple[str, str, str, List[str]]:
    """
    Extract a code block and return the bundle for async enrichment.
    Returns (item_id, code_text, language, breadcrumbs_copy).
    """
    text     = item.text.strip()
    language = getattr(item, "code_language", None) or ""
    item_id  = generate_unique_id(page, "code")
    return item_id, text, language, breadcrumbs[:]


def process_formula(
    item: TextItem,
    page: int,
    breadcrumbs: List[str],
) -> Tuple[str, str, List[str]]:
    """
    Extract a formula and return the bundle for async enrichment.
    Returns (item_id, formula_text, breadcrumbs_copy).
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
) -> Tuple[str, List[str], int, int, List[str], List[str]]:
    """
    Process all items on a single page concurrently.

    Synchronous first pass: extract structure, queue async tasks.
    Async second pass:  asyncio.gather() runs all AI calls concurrently.
    Results merged back in original document order.

    Returns:
        (page_markdown_text, updated_breadcrumbs, image_count, table_count,
         table_s3_uris, image_s3_uris)
    """
    sync_outputs: List[Tuple[int, str]]          = []
    async_tasks:  List[Tuple[int, str, any, Dict]] = []

    image_counter = 1
    image_count   = 0
    table_count   = 0
    skip_next     = False

    page_table_s3_uris: List[str] = []
    page_image_s3_uris: List[str] = []

    for idx, entry in enumerate(items):
        if skip_next:
            skip_next = False
            continue

        item  = entry["item"]
        level = entry["level"]
        label = item.label

        # Caption look-ahead: consume CAPTION TextItem immediately following
        # a figure or table so it becomes that element's caption= argument.
        caption: Optional[str] = None
        if idx + 1 < len(items):
            next_item = items[idx + 1]["item"]
            if (isinstance(next_item, TextItem) and
                    next_item.label == DocItemLabel.CAPTION):
                caption   = next_item.text.strip()
                skip_next = True

        # ── 1. Discard page boilerplate ───────────────────────────────────
        if label in _SKIP_LABELS:
            continue

        # ── 2. Code blocks ────────────────────────────────────────────────
        elif label == DocItemLabel.CODE:
            item_id, text, language, bc = process_code(item, page_num, breadcrumbs)
            if len(text) > CODE_DESCRIPTION_MIN_LEN:
                meta = {"item_id": item_id, "text": text,
                        "language": language, "breadcrumbs": bc}
                async_tasks.append((idx, "code", None, meta))
            else:
                output = wrap_with_boundaries(
                    f"```{language}\n{text}\n```",
                    "code", item_id, page_num,
                    language=language or "unknown",
                    breadcrumbs=" > ".join(bc),
                )
                sync_outputs.append((idx, output))

        # ── 3. Mathematical formulas ──────────────────────────────────────
        elif label == DocItemLabel.FORMULA:
            item_id, text, bc = process_formula(item, page_num, breadcrumbs)
            meta = {"item_id": item_id, "text": text, "breadcrumbs": bc}
            async_tasks.append((idx, "formula", None, meta))

        # ── 4. Section headers (MUST precede TextItem check) ──────────────
        elif isinstance(item, SectionHeaderItem):
            output, breadcrumbs = process_header(item, page_num, level, breadcrumbs)
            if output:
                sync_outputs.append((idx, output))

        # ── 5. List items (MUST precede TextItem check) ───────────────────
        elif isinstance(item, ListItem):
            output = process_list(item, page_num, breadcrumbs)
            if output:
                sync_outputs.append((idx, output))

        # ── 6. Generic text ───────────────────────────────────────────────
        elif isinstance(item, TextItem):
            output = process_text(item, page_num, breadcrumbs)
            if output:
                sync_outputs.append((idx, output))

        # ── 7. Figures ────────────────────────────────────────────────────
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

        # ── 8. Tables ─────────────────────────────────────────────────────
        elif isinstance(item, TableItem):
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
                # Text export failed - render as image fallback
                filename = f"fig_p{page_num}_{image_counter}.png"
                meta = {
                    "item": item, "doc": doc, "filename": filename,
                    "breadcrumbs": breadcrumbs[:], "caption": caption,
                    "is_table": True,
                }
                async_tasks.append((idx, "image", None, meta))
                image_counter += 1
                table_count   += 1

    # ── Async second pass: resolve all AI tasks concurrently ──────────────

    async def resolve_task(task_type: str, meta: Dict) -> str:
        """
        Resolve a single async task to its final boundary-marked string.

        TABLE BODY DESIGN:
        ─────────────────
        LARGE TABLE (> TABLE_LARGE_THRESHOLD_CHARS):
          Inline body = caption + AI description blockquote + cell dump
          NO raw Markdown inline — lives in S3 only
          ai_description attr = full description (Stage 2 uses as VDB content)
          is_large attr = "yes"
          s3_uri attr = raw Markdown location

        SMALL TABLE (<= TABLE_LARGE_THRESHOLD_CHARS):
          Inline body = caption + AI description blockquote + full raw Markdown
          Small tables stay in VDB as raw text
          ai_description attr = full description (supplementary for Stage 3)
          is_large attr = "no"
          s3_uri attr = not set (no S3 upload)
        """

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
            is_large = len(meta["md_table"]) > TABLE_LARGE_THRESHOLD_CHARS

            # AI description always generated for both small and large tables.
            # For large tables: this IS the VDB content (Stage 2 reads ai_description attr).
            # For small tables: supplements raw Markdown; both embedded in VDB.
            ai_desc = await describe_table_with_ai(
                meta["md_table"], client,
                caption=meta["caption"], label=meta["item_id"],
            )

            # S3 upload — large tables only.
            # Raw Markdown stored for query-time retrieval (two-pass pattern).
            s3_uri = ""
            if is_large and s3_client and s3_bucket:
                try:
                    s3_key = f"{doc_id}/tables/{meta['item_id']}.md"
                    s3_uri = upload_to_s3(
                        s3_client, s3_bucket, s3_key,
                        meta["md_table"].encode("utf-8"), "text/markdown",
                    )
                    page_table_s3_uris.append(s3_uri)
                    logger.info(
                        "Large table uploaded  id=%s  chars=%d  s3_uri=%s",
                        meta["item_id"], len(meta["md_table"]), s3_uri,
                    )
                except Exception as exc:
                    logger.error(
                        "S3 table upload failed  id=%s  error=%s",
                        meta["item_id"], exc,
                    )

            # ── Build .md body ────────────────────────────────────────────
            parts = []

            if meta["caption"]:
                parts.append(f"*Caption:* {meta['caption']}")

            # AI description as Markdown blockquote — semantic anchor,
            # always written first so it lands in the first chunk
            if ai_desc and not ai_desc.startswith("AI description unavailable"):
                parts.append("> " + ai_desc.replace("\n", "\n> "))
                parts.append("")

            if is_large:
                # LARGE TABLE: cell dump replaces raw Markdown inline.
                # The cell dump is "Col: val | Col: val" per row — compact,
                # column-context-aware, fits in one VDB chunk.
                # Raw Markdown is in S3 — pointed to by s3_uri attr.
                # Stage 2 reads is_large="yes", routes standalone, uses
                # ai_description attr as VDB content (not this body).
                cell_dump = _build_cell_dump(meta["md_table"], meta["item_id"])
                if cell_dump:
                    parts.append("**Table cell index (for search):**")
                    parts.append(cell_dump)
                    parts.append("")
                if s3_uri:
                    parts.append(f"*Full table: {s3_uri}*")

            else:
                # SMALL TABLE: full raw Markdown inline.
                # Stage 2 merges with surrounding paragraphs into a semantic chunk.
                # Both raw Markdown and description are embedded in the VDB.
                parts.append(meta["md_table"])

            inline_content = "\n".join(parts)

            return wrap_with_boundaries(
                inline_content, "table", meta["item_id"], page_num,
                rows=meta["rows"],
                columns=meta["columns"],
                has_caption="yes" if meta["caption"] else "no",
                is_large="yes" if is_large else "no",
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

            if s3_uri:
                page_image_s3_uris.append(s3_uri)

            item_id  = generate_unique_id(page_num, "image_resolved")
            img_link = s3_uri if s3_uri else f"../figures/{filename}"

            # Image body: label + caption + img tag + description blockquote.
            # Stage 2 reads ai_description attr for VDB content.
            # The blockquote in the body is supplementary context.
            parts = [f"**{type_label}**"]
            if meta["caption"]:
                parts.append(f"*Caption:* {meta['caption']}")
            parts.append(f"![{filename}]({img_link})")

            if ai_desc and not ai_desc.startswith("AI description unavailable"):
                parts.append("")
                parts.append("> " + ai_desc.replace("\n", "\n> "))

            return wrap_with_boundaries(
                "\n".join(parts), "image", item_id, page_num,
                image_filename=filename,
                has_caption="yes" if meta["caption"] else "no",
                breadcrumbs=" > ".join(meta["breadcrumbs"]),
                s3_uri=s3_uri or None,
                ai_description=ai_desc,
            )

        return ""

    coroutines    = [resolve_task(tt, m) for (_, tt, _, m) in async_tasks]
    async_results: List[str] = await asyncio.gather(*coroutines)

    # Merge sync and async results in original document order
    ordered: List[Tuple[int, str]] = list(sync_outputs)
    for i, (orig_idx, _, _, _) in enumerate(async_tasks):
        if async_results[i]:
            ordered.append((orig_idx, async_results[i]))

    ordered.sort(key=lambda x: x[0])
    page_text = "\n\n".join(s for _, s in ordered if s)

    return (page_text, breadcrumbs, image_count, table_count,
            page_table_s3_uris, page_image_s3_uris)


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
    Full async pipeline: Extract -> Enrich -> Upload for a single PDF.

    Processing stages:
      [1/4] Docling layout analysis       (synchronous, CPU-bound)
      [2/4] Group items by page           (synchronous, in-memory)
      [3/4] Per-page async processing     (async AI calls + S3 uploads)
      [4/4] Write metadata.json + upload  (I/O)

    Returns metadata dict written to metadata.json.
    """
    t_start = time.monotonic()
    reset_id_counters()

    effective_doc_id = doc_id or pdf_path.stem
    doc_output_dir   = output_base_dir / pdf_path.stem

    (doc_output_dir / "pages").mkdir(parents=True, exist_ok=True)
    (doc_output_dir / "figures").mkdir(parents=True, exist_ok=True)
    (doc_output_dir / "tables").mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Processing: %s", pdf_path.name)
    logger.info("Output:     %s", doc_output_dir)
    logger.info("=" * 60)

    # [1/4] Docling layout analysis
    logger.info("[1/4] Analysing PDF layout with Docling...")
    converter = get_converter()
    doc       = converter.convert(pdf_path).document
    logger.info("[1/4] Layout analysis complete")

    # [2/4] Group items by page
    logger.info("[2/4] Collecting document items...")
    pages_items: Dict[int, List[Dict]] = defaultdict(list)
    for item, level in doc.iterate_items():
        if not item.prov:
            continue
        pages_items[item.prov[0].page_no].append({"item": item, "level": level})

    total_items = sum(len(v) for v in pages_items.values())
    logger.info("[2/4] %d items across %d pages", total_items, len(pages_items))

    # [3/4] Per-page async extraction + enrichment + upload
    logger.info("[3/4] Extracting, enriching, uploading (async)...")
    metadata_pages: List[Dict]    = []
    global_breadcrumbs: List[str] = []
    total_images = 0
    total_tables = 0
    all_table_s3_uris: List[str] = []
    all_image_s3_uris: List[str] = []

    for page_num in sorted(pages_items.keys()):
        logger.info("  Page %d / %d...", page_num, max(pages_items.keys()))

        (page_text, global_breadcrumbs,
         img_count, tbl_count,
         tbl_s3_uris, img_s3_uris) = await process_page(
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

        page_filename = f"page_{page_num}.md"
        local_page    = doc_output_dir / "pages" / page_filename
        local_page.write_text(page_text, encoding="utf-8")

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

        all_table_s3_uris.extend(tbl_s3_uris)
        all_image_s3_uris.extend(img_s3_uris)
        total_images += img_count
        total_tables += tbl_count

        metadata_pages.append({
            "page":          page_num,
            "file":          page_filename,
            "images":        img_count,
            "tables":        tbl_count,
            "table_s3_uris": tbl_s3_uris,
            "image_s3_uris": img_s3_uris,
        })

    elapsed = time.monotonic() - t_start
    logger.info(
        "[3/4] Complete  pages=%d  images=%d  tables=%d  elapsed=%.1fs",
        len(pages_items), total_images, total_tables, elapsed,
    )

    # [4/4] Metadata
    logger.info("[4/4] Writing metadata...")
    metadata = {
        "file":              pdf_path.name,
        "doc_id":            effective_doc_id,
        "processed":         datetime.now().isoformat(),
        "tool":              "docling_bounded_extractor_v5.3",
        "elapsed_seconds":   round(elapsed, 2),
        "pages":             metadata_pages,
        "total_images":      total_images,
        "total_tables":      total_tables,
        "all_table_s3_uris": all_table_s3_uris,
        "all_image_s3_uris": all_image_s3_uris,
    }

    meta_path = doc_output_dir / "metadata.json"
    meta_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if s3_client and s3_bucket:
        try:
            upload_to_s3(
                s3_client, s3_bucket,
                f"{effective_doc_id}/metadata.json",
                json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8"),
                "application/json",
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
    Command-line interface for single PDF or directory batch processing.

    Usage examples:
      python docling_bounded_extractor.py protocol.pdf
      python docling_bounded_extractor.py protocol.pdf --bucket my-bucket --doc-id trial-001
      python docling_bounded_extractor.py ./pdfs/ --output ./extracted --bucket my-bucket
    """
    parser = argparse.ArgumentParser(
        description="Docling Bounded PDF Extractor v5.3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path",     type=Path,
                        help="PDF file or directory containing PDFs")
    parser.add_argument("--output", type=Path, default=Path(OUTPUT_DIR))
    parser.add_argument("--bucket", type=str,  default="")
    parser.add_argument("--doc-id", type=str,  default="")
    parser.add_argument("--region", type=str,  default="us-east-1")
    args = parser.parse_args()

    client    = AsyncOpenAI()
    s3_client = None
    if args.bucket:
        s3_client = boto3.client("s3", region_name=args.region)
        logger.info("S3 target: s3://%s/", args.bucket)

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