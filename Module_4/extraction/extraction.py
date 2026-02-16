"""
Docling PDF Extractor with Boundary Markers
--------------------------------------------
Functional programming version for easy understanding.

See TECHNICAL_GUIDE.md for complete documentation.

WHAT THIS SCRIPT DOES
----------------------
Converts one or more PDF files into structured Markdown documents with
HTML-style boundary markers around every extracted element (headers, paragraphs,
tables, images, code blocks, lists). Each page is saved as a separate .md file.

PIPELINE OVERVIEW (per PDF)
----------------------------
  1. Docling parses the PDF layout — text blocks, tables, figures, etc.
  2. Items are grouped by page number.
  3. Each item is processed by a dedicated handler function:
       - Headers    → Markdown headings + breadcrumb trail
       - Paragraphs → plain text wrapped in boundaries
       - Lists      → bullet/numbered items
       - Code       → fenced code blocks with language detection
       - Tables     → Markdown table (via pandas) + AI description
                      Falls back to image extraction if text export fails
       - Images     → saved as PNG + GPT-4 Vision description
  4. Every element is wrapped in <!-- BOUNDARY_START ... --> / <!-- BOUNDARY_END --> tags
     so downstream consumers (chunkers, RAG pipelines) can locate and slice
     any element precisely without re-parsing the Markdown.
  5. Page-level .md files and a metadata.json are written to the output directory.

OUTPUT STRUCTURE
----------------
  extracted_docs_bounded/
  └── <pdf_stem>/
      ├── metadata.json       ← page index, counts, processing timestamp
      ├── pages/
      │   ├── page_1.md
      │   ├── page_2.md
      │   └── ...
      └── figures/
          ├── fig_p1_1.png
          └── ...

BOUNDARY MARKER FORMAT
-----------------------
  <!-- BOUNDARY_START type="paragraph" id="p3_text_2" page="3" char_count="412" ... -->
  The actual paragraph text goes here.
  <!-- BOUNDARY_END type="paragraph" id="p3_text_2" -->

USAGE
-----
  # Single PDF
  python docling_pdf_extractor.py report.pdf

  # All PDFs in a directory
  python docling_pdf_extractor.py ./reports/

  # Custom output directory
  python docling_pdf_extractor.py ./reports/ --output ./my_output

DEPENDENCIES
------------
  pip install docling openai pandas tabulate
  export OPENAI_API_KEY=sk-...
"""

import os
import sys
import json
import base64
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# ---------------------------------------------------------------------------
# Dependency guard — fail loudly at startup with a clear install message
# rather than throwing an AttributeError deep inside the pipeline
# ---------------------------------------------------------------------------
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import (
        TableItem, PictureItem, TextItem, SectionHeaderItem, ListItem
    )
    from openai import OpenAI
    import pandas as pd
except ImportError as e:
    print(f"\nMissing library: {e}")
    print("Install: pip install docling openai pandas")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Global configuration constants
# ---------------------------------------------------------------------------
OUTPUT_DIR = "extracted_docs_bounded"   # default output root if --output not passed
OPENAI_MODEL = "gpt-4o"                 # vision-capable model needed for image analysis
IMAGE_SCALE = 3.0                       # render images at 3× → 216 DPI for legible charts


# =============================================================================
# BOUNDARY MARKERS
# =============================================================================
# Boundary markers are HTML comments that wrap every extracted element.
# They carry structured metadata (type, id, page number, extra attributes)
# directly inside the Markdown file so that:
#   - RAG chunkers can split on clean semantic boundaries
#   - Downstream pipelines can query "give me all tables on page 5"
#   - The original document structure is fully recoverable from the .md files
#
# Example:
#   <!-- BOUNDARY_START type="table" id="p5_table_1" page="5" rows="8" columns="4" -->
#   | Col A | Col B |
#   | ----- | ----- |
#   | 1     | 2     |
#   <!-- BOUNDARY_END type="table" id="p5_table_1" -->
# =============================================================================

def create_boundary_start(item_type: str, item_id: str, page: int, **attrs) -> str:
    """
    Build an opening boundary comment tag.

    Args:
        item_type : element category e.g. "paragraph", "table", "image"
        item_id   : unique ID string for this element e.g. "p3_text_2"
        page      : 1-based page number from the PDF
        **attrs   : any extra key=value pairs to embed (rows, columns, language, etc.)

    Returns:
        HTML comment string e.g.:
        <!-- BOUNDARY_START type="table" id="p5_table_1" page="5" rows="8" -->
    """
    attr_str = f'type="{item_type}" id="{item_id}" page="{page}"'
    for key, value in attrs.items():
        attr_str += f' {key}="{value}"'
    return f"<!-- BOUNDARY_START {attr_str} -->"


def create_boundary_end(item_type: str, item_id: str) -> str:
    """
    Build a closing boundary comment tag.

    Having a matching END tag (not just the START) lets parsers verify
    completeness and handle truncated outputs gracefully.

    Returns:
        e.g. <!-- BOUNDARY_END type="table" id="p5_table_1" -->
    """
    return f'<!-- BOUNDARY_END type="{item_type}" id="{item_id}" -->'


def wrap_with_boundaries(content: str, item_type: str, item_id: str,
                         page: int, **attrs) -> str:
    """
    Convenience wrapper — sandwich content between START and END markers.

    Filters out None-valued attrs before rendering so the tag stays clean
    (e.g. caption=None won't appear as caption="None" in the output).

    Args:
        content   : the Markdown string to wrap
        item_type : element category
        item_id   : unique element ID
        page      : page number
        **attrs   : optional metadata attributes; None values are dropped

    Returns:
        Multi-line string: START tag + content + END tag
    """
    # Drop attrs that are None — they carry no information and clutter the tag
    filtered_attrs = {k: v for k, v in attrs.items() if v is not None}
    start = create_boundary_start(item_type, item_id, page, **filtered_attrs)
    end = create_boundary_end(item_type, item_id)
    return f"{start}\n{content}\n{end}"


# =============================================================================
# UNIQUE ID GENERATION
# =============================================================================
# Each element gets a deterministic, human-readable ID in the form:
#   p{page}_{type}_{counter}   e.g.  p3_text_2  (second text block on page 3)
#
# Using a per-page-per-type counter (rather than a global UUID) keeps IDs
# short, sortable, and meaningful when reading the raw Markdown.
#
# The counter dict is module-level so it persists across all processor calls
# during one page's processing, but reset_id_counters() is called at the
# start of each new PDF to avoid IDs bleeding across documents.
# =============================================================================

# Module-level counter: key = "p{page}_{type}", value = current count
_id_counters = defaultdict(int)


def generate_unique_id(page: int, item_type: str) -> str:
    """
    Generate a unique, human-readable element ID for the current document.

    Pattern: p{page}_{type}_{counter}
    Examples:
        p1_header_1  — first header on page 1
        p3_text_2    — second text block on page 3
        p7_image_1   — first image on page 7

    Counter increments per (page, type) combination so each page's elements
    are independently numbered — easy to cross-reference against the source PDF.
    """
    key = f"p{page}_{item_type}"
    _id_counters[key] += 1
    return f"{key}_{_id_counters[key]}"


def reset_id_counters():
    """
    Reset all counters to zero.

    Must be called at the start of each PDF to prevent IDs from a previous
    document leaking into the next (e.g. if processing a directory of PDFs).
    """
    global _id_counters
    _id_counters = defaultdict(int)


# =============================================================================
# DOCLING SETUP
# =============================================================================

def create_docling_converter():
    """
    Construct and return a Docling DocumentConverter configured for high-quality
    PDF extraction.

    Key configuration decisions:
      - images_scale=3.0      : renders at 216 DPI so chart text is legible for
                                 GPT-4 Vision analysis
      - generate_picture_images=True / generate_table_images=True
                               : saves PNG files for images AND tables; tables
                                 fall back to image if text export fails
      - do_ocr=False          : skips OCR — assumes the PDF has embedded text
                                 (set to True for scanned PDFs)
      - do_table_structure=True: enables TableFormer, Docling's ML table parser
      - TableFormerMode.ACCURATE: slower but significantly more accurate than FAST;
                                  worth the cost for financial/scientific tables
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = IMAGE_SCALE
    pipeline_options.generate_picture_images = True    # save figure PNGs
    pipeline_options.generate_table_images = True      # save table PNGs (fallback)
    pipeline_options.do_ocr = False                    # assumes text-based PDF
    pipeline_options.do_table_structure = True         # enable ML table parsing
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE  # best quality

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


# =============================================================================
# AI DESCRIPTIONS
# =============================================================================
# GPT-4o is used for two AI analysis tasks:
#   1. Table description — the table is sent as Markdown text
#   2. Image description — the image is base64-encoded and sent as a data URL
#
# Both use low max_tokens (150 / 200) to keep costs down while still getting
# a useful analytical summary. Failures are caught and returned as placeholder
# strings so the pipeline always produces output even if the AI call fails.
# =============================================================================

def describe_table_with_ai(table_text: str, openai_client, caption: str = None) -> str:
    """
    Ask GPT-4o to describe a table's purpose, structure, and key takeaways.

    Sends the table as Markdown text (no image needed — text is cheaper and
    faster). The optional caption is included if available to give the model
    additional context about what the table represents.

    Args:
        table_text    : Markdown-formatted table string (from pandas .to_markdown())
        openai_client : initialised OpenAI client
        caption       : optional caption string found adjacent to the table in the PDF

    Returns:
        AI-generated description string, or error message on failure.
    """
    try:
        prompt = "Analyze this table. Describe its purpose, structure, and key information concisely."
        if caption:
            # Including the caption helps the model understand the table's context
            # e.g. "Exhibit 3: Revenue by Region FY2024"
            prompt += f"\n\nCaption: {caption}"
        prompt += f"\n\nTable:\n{table_text}"

        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150   # short descriptions keep cost manageable at scale
        )
        return response.choices[0].message.content
    except Exception as e:
        # Non-fatal — return placeholder so the table is still written to output
        return f"AI description failed: {str(e)}"


def describe_image_with_ai(image_path: Path, openai_client, caption: str = None) -> str:
    """
    Ask GPT-4o Vision to analyse a chart or figure image.

    The image is base64-encoded and sent as a data URL inside the message
    content — this avoids needing to host the image publicly.

    Why base64 instead of a file upload?
    Data URLs are self-contained in the API request — no extra upload step,
    no expiring signed URLs, works the same in local dev and production.

    Args:
        image_path    : Path to the saved PNG file on disk
        openai_client : initialised OpenAI client
        caption       : optional caption string for added context

    Returns:
        AI-generated analysis string, or error message on failure.
    """
    try:
        # Read the image file and encode it to base64 for the API
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')

        # Ask for classification (Chart/Diagram/Data Table) AND analytical insight
        # so the description is useful for both search and downstream reasoning
        prompt = "Analyze this visual. Is it a Chart, Diagram, or Data Table? "
        prompt += "Describe the axes, trends, and key insights concisely."
        if caption:
            prompt += f"\n\nCaption/Context: {caption}"

        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    # data URL format: data:{mime_type};base64,{encoded_bytes}
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }],
            max_tokens=200   # slightly more than table descriptions for visual analysis
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI description failed: {str(e)}"


# =============================================================================
# IMAGE PROCESSING
# =============================================================================

def extract_and_save_image(item, doc, page_num: int, output_dir: Path,
                            image_counter: int, openai_client,
                            caption: str = None, is_table: bool = False
                           ) -> Optional[Tuple[str, str, str, str]]:
    """
    Extract a Docling image/table item to a PNG file and get its AI description.

    This is a shared utility used by BOTH process_image() and process_table()
    (when the table text export fails). Centralising extraction here avoids
    duplicating the save + AI-call logic in two places.

    Args:
        item          : Docling PictureItem or TableItem
        doc           : the parent Docling document (needed by get_image())
        page_num      : page number for the filename
        output_dir    : document-level output directory (figures/ lives inside)
        image_counter : current image counter for this page (used in filename)
        openai_client : initialised OpenAI client
        caption       : optional caption text for richer AI context
        is_table      : True → label the element "Table/Chart"; False → "Image"

    Returns:
        Tuple of (filename, relative_filepath, ai_description, type_label)
        or None if the image could not be extracted (non-fatal).
    """
    try:
        img_obj = item.get_image(doc)
        if not img_obj:
            return None  # Docling couldn't render this item — skip gracefully

        # Filename convention: fig_p{page}_{counter}.png
        # e.g. fig_p3_2.png = second figure on page 3
        filename = f"fig_p{page_num}_{image_counter}.png"
        filepath = output_dir / "figures" / filename
        img_obj.save(filepath)

        # Get AI description using the saved file
        ai_desc = describe_image_with_ai(filepath, openai_client, caption)
        type_label = "Table/Chart" if is_table else "Image"

        # Return relative path so the Markdown image links work from the pages/ subdir
        return (filename, str(filepath.relative_to(output_dir)), ai_desc, type_label)
    except Exception as e:
        print(f"   WARNING: Image extraction failed: {str(e)}")
        return None  # non-fatal — caller handles None return


# =============================================================================
# ITEM PROCESSORS
# =============================================================================
# Each processor handles one Docling item type and returns a boundary-wrapped
# Markdown string. They all follow the same contract:
#   - Accept the Docling item + page/context info
#   - Call generate_unique_id() to get a stable element ID
#   - Return a wrapped string (or empty string / None to signal "skip")
#
# Processors are intentionally pure functions (no side effects except the
# shared _id_counters) so they are easy to test and reason about independently.
# =============================================================================

def process_header(item: SectionHeaderItem, page: int, level: int,
                   breadcrumbs: List[str]) -> Tuple[str, List[str]]:
    """
    Convert a section header into a Markdown heading and update the breadcrumb trail.

    BREADCRUMB LOGIC
    ----------------
    Breadcrumbs track the current position in the document hierarchy so that
    every subsequent element (paragraphs, tables, images) knows which section
    it belongs to. This is critical for RAG — a chunk that says "Revenue grew 12%"
    is far more useful when its metadata says "Results > Revenue > Q4 Performance".

    Truncation rule: if a level-2 header is encountered, any breadcrumbs at
    level 2 or deeper are discarded and replaced with the new header. This
    mirrors how a table of contents works — a new section at level N closes
    all subsections below it.

    Args:
        item        : Docling SectionHeaderItem
        page        : current page number
        level       : heading depth (1 = top-level chapter, 2 = section, etc.)
        breadcrumbs : mutable list representing the current document path

    Returns:
        Tuple of (wrapped Markdown string, updated breadcrumbs list)
    """
    text = item.text.strip()

    # Truncate breadcrumbs to the parent level before appending the new header
    # e.g. entering a level-2 section removes all existing level-2+ entries
    if len(breadcrumbs) >= level:
        breadcrumbs = breadcrumbs[:level - 1]
    breadcrumbs.append(text)

    item_id = generate_unique_id(page, "header")
    # +1 to level because level 1 = ## (not #) — # is reserved for the page heading
    content = f"{'#' * (level + 1)} {text}"

    output = wrap_with_boundaries(
        content, "header", item_id, page,
        level=level,
        breadcrumbs=" > ".join(breadcrumbs)  # e.g. "Results > Revenue > Q4"
    )
    return output, breadcrumbs


def process_text(item: TextItem, page: int, breadcrumbs: List[str]) -> str:
    """
    Wrap a regular text paragraph in boundary markers with word/char counts.

    The char_count and word_count metadata in the boundary tag are useful for:
      - Chunking strategies that target specific token ranges
      - Filtering out noise (very short fragments)

    Single-character items (e.g. lone punctuation artifacts from OCR) are
    skipped — they add no value and clutter the output.

    Args:
        item        : Docling TextItem
        page        : current page number
        breadcrumbs : current document path for metadata

    Returns:
        Boundary-wrapped Markdown string, or "" if the text is too short to keep.
    """
    text = item.text.strip()

    # Skip single characters — usually OCR noise or stray punctuation marks
    if len(text) <= 1:
        return ""

    item_id = generate_unique_id(page, "text")

    return wrap_with_boundaries(
        text, "paragraph", item_id, page,
        char_count=len(text),
        word_count=len(text.split()),
        breadcrumbs=" > ".join(breadcrumbs)
    )


def process_list(item: ListItem, page: int, breadcrumbs: List[str]) -> str:
    """
    Format a list item with its bullet marker and wrap in boundary markers.

    Docling exposes the list marker via item.enumeration — this could be a
    bullet character ("-", "•") or a number ("1.", "2.") for ordered lists.
    Falling back to "-" ensures the output is always valid Markdown.

    Args:
        item        : Docling ListItem
        page        : current page number
        breadcrumbs : current document path

    Returns:
        Boundary-wrapped Markdown list item string.
    """
    # getattr with default handles items where enumeration is not set
    marker = getattr(item, 'enumeration', '-')
    text = item.text.strip()
    content = f"{marker} {text}"
    item_id = generate_unique_id(page, "list")

    return wrap_with_boundaries(
        content, "list", item_id, page,
        breadcrumbs=" > ".join(breadcrumbs)
    )


def process_special_text(item: TextItem, page: int, breadcrumbs: List[str]) -> Optional[str]:
    """
    Detect code blocks within a TextItem and wrap them in fenced code blocks.

    WHY ONLY CODE (NOT FORMULAS)?
    Formula detection was disabled because it produced too many false positives —
    many ordinary sentences triggered the heuristic (e.g. sentences with
    parentheses and numbers). Code blocks have much more reliable surface signals
    (indentation, keywords like 'def', 'import', curly-brace patterns).

    If formula support is needed in the future, use explicit LaTeX delimiters
    ($..$ or $$..$) in the source PDF rather than heuristic detection.

    LANGUAGE DETECTION
    A lightweight keyword scan guesses Python or JavaScript. The language
    tag is used in the fenced code block (```python) and also stored in the
    boundary metadata for downstream syntax highlighting or filtering.

    Args:
        item        : Docling TextItem (may or may not be code)
        page        : current page number
        breadcrumbs : current document path

    Returns:
        Boundary-wrapped fenced code block string if code is detected, else None.
        Returning None signals process_pdf() to fall through to process_text().
    """
    text = item.text.strip()

    # Minimum length check — very short strings can't reliably be code
    if len(text) < 3:
        return None

    # Heuristic code detection: indentation, fences, or language-specific keywords
    is_code = (
        text.startswith('    ') or text.startswith('\t') or   # indented block
        '```' in text or                                        # already has a fence
        text.count('def ') > 0 or                              # Python function def
        text.count('class ') > 0 or                            # Python/JS class
        text.count('import ') > 0 or                           # Python import
        text.count('function ') > 0 or                         # JS function
        ('{' in text and '}' in text and ';' in text)          # C-style block
    )

    if is_code:
        # Lightweight language detection via keyword presence
        language = ''
        if 'python' in text.lower() or 'def ' in text or 'import ' in text:
            language = 'python'
        elif 'function' in text or 'const ' in text or 'let ' in text:
            language = 'javascript'

        # Wrap in a Markdown fenced code block
        content = f"```{language}\n{text}\n```"
        item_id = generate_unique_id(page, "code")
        return wrap_with_boundaries(
            content, "code", item_id, page,
            language=language if language else "unknown",
            breadcrumbs=" > ".join(breadcrumbs)
        )

    # Formula detection intentionally disabled — too many false positives.
    # For future formula support: look for explicit LaTeX delimiters ($..$, $$..$)
    # rather than heuristics.

    return None  # signals caller to treat this as a regular paragraph


def process_image(item: PictureItem, doc, page: int, output_dir: Path,
                  image_counter: int, openai_client, breadcrumbs: List[str],
                  next_item=None) -> Tuple[str, int]:
    """
    Extract a figure/picture item, save it, get an AI description, and return
    boundary-wrapped Markdown with an embedded image link.

    CAPTION DETECTION
    The item immediately following a figure in the Docling item stream is
    checked for a 'caption' label. Docling assigns this label to text blocks
    that it identifies as figure captions during layout analysis. If found,
    the caption is included in the boundary metadata AND passed to the AI
    for richer context.

    The image counter is incremented and returned so the caller can pass the
    updated value to the next image/table processor on the same page.

    Args:
        item          : Docling PictureItem
        doc           : parent Docling document
        page          : current page number
        output_dir    : document-level output directory
        image_counter : current sequential counter for figures on this page
        openai_client : initialised OpenAI client
        breadcrumbs   : current document path
        next_item     : the next item in the page stream (for caption detection)

    Returns:
        Tuple of (boundary-wrapped Markdown string, updated image_counter).
        Returns ("", image_counter) if extraction fails.
    """
    # Check if the very next item in the stream is a caption
    # Docling's 'caption' label is more reliable than text-pattern heuristics
    caption = None
    if next_item and isinstance(next_item, TextItem):
        label = next_item.label
        text = next_item.text.strip()
        if label == 'caption':
            caption = text

    # Attempt to extract and save the image
    img_result = extract_and_save_image(
        item, doc, page, output_dir, image_counter,
        openai_client, caption=caption, is_table=False
    )

    if not img_result:
        # Extraction failed — return empty string, don't increment counter
        return "", image_counter

    filename, filepath, ai_desc, type_label = img_result
    item_id = generate_unique_id(page, "image")

    # Build the Markdown content block:
    #   **Image**
    #   *Caption:* ...   (if present)
    #   ![filename](../figures/filename.png)
    #   *AI Analysis:* ...
    content_parts = [f"**{type_label}**"]
    if caption:
        content_parts.append(f"*Caption:* {caption}")
    content_parts.append(f"![{filename}](../{filepath})")   # relative link from pages/
    content_parts.append(f"*AI Analysis:* {ai_desc}")
    content = "\n".join(content_parts)

    output = wrap_with_boundaries(
        content, "image", item_id, page,
        filename=filename,
        has_caption="yes" if caption else "no",
        breadcrumbs=" > ".join(breadcrumbs)
    )

    # Increment counter — next image/table on this page gets a different filename
    return output, image_counter + 1


def process_table(item: TableItem, doc, page: int, output_dir: Path,
                  image_counter: int, openai_client, breadcrumbs: List[str],
                  next_item=None) -> Tuple[str, int]:
    """
    Process a table item using a text-first, image-fallback strategy.

    TWO-STAGE EXTRACTION STRATEGY
    ------------------------------
    Stage 1 — Text (preferred):
      Docling's TableFormer ML model exports the table as a pandas DataFrame.
      If the DataFrame is non-empty, it is converted to a Markdown table via
      pandas .to_markdown() and sent to GPT-4o as text for analysis.
      Text extraction is: cheaper (no image), lossless (no rendering artefacts),
      and produces Markdown that is directly searchable and copy-pasteable.

    Stage 2 — Image (fallback):
      If text extraction fails (empty DataFrame, rendering error, malformed table)
      the table is rendered to a PNG via Docling and sent to GPT-4o Vision.
      This handles complex merged-cell tables or image-based tables in scanned PDFs.

    CAPTION DETECTION
    For tables, caption detection uses text-pattern heuristics (starts with
    "Exhibit", "Table", "Source:", etc.) rather than Docling's label, because
    table captions in financial PDFs often appear ABOVE the table and Docling
    doesn't always label them as 'caption'.

    Args:
        item          : Docling TableItem
        doc           : parent Docling document
        page          : current page number
        output_dir    : document-level output directory
        image_counter : current sequential counter for figures on this page
        openai_client : initialised OpenAI client
        breadcrumbs   : current document path
        next_item     : next item in page stream (for caption detection)

    Returns:
        Tuple of (boundary-wrapped Markdown string, updated image_counter).
        Counter only increments in the image-fallback path.
    """
    # Caption detection for tables uses text-pattern heuristics
    # (Docling label-based detection is less reliable for table captions)
    caption = None
    if next_item and isinstance(next_item, TextItem):
        text = next_item.text.strip()
        is_caption = (
            text.startswith(('Exhibit', 'Figure', 'Table', 'Chart', 'Source:')) or
            'Source:' in text or
            (len(text) < 200 and ':' in text)   # short colon-containing line
        )
        if is_caption:
            caption = text

    # ------------------------------------------------------------------
    # Stage 1: Try exporting the table as text (fast, cheap, lossless)
    # ------------------------------------------------------------------
    text_table_valid = False
    df = None
    md_table = None

    try:
        df = item.export_to_dataframe()
        if not df.empty and len(df) > 0 and len(df.columns) > 0:
            md_table = df.to_markdown(index=False)
            # Sanity check: very short "tables" (< 50 chars) are likely noise
            text_table_valid = len(md_table) > 50
    except:
        # export_to_dataframe can raise on malformed tables — catch all and fallback
        text_table_valid = False

    if text_table_valid and md_table:
        item_id = generate_unique_id(page, "table")
        # Send as text — cheaper than Vision and works well for structured data
        table_desc = describe_table_with_ai(md_table, openai_client, caption)

        content_parts = []
        if caption:
            content_parts.append(f"*Caption:* {caption}")
        content_parts.append(md_table)
        content_parts.append(f"\n*AI Analysis:* {table_desc}")
        content = "\n".join(content_parts)

        output = wrap_with_boundaries(
            content, "table", item_id, page,
            rows=len(df),
            columns=len(df.columns),
            has_caption="yes" if caption else "no",
            breadcrumbs=" > ".join(breadcrumbs)
        )
        # Counter NOT incremented — no image file was created
        return output, image_counter

    # ------------------------------------------------------------------
    # Stage 2: Text failed — fall back to image extraction
    # ------------------------------------------------------------------
    # is_table=True labels the element "Table/Chart" in the AI prompt and output
    img_result = extract_and_save_image(
        item, doc, page, output_dir, image_counter,
        openai_client, caption=caption, is_table=True
    )

    if img_result:
        filename, filepath, ai_desc, type_label = img_result
        item_id = generate_unique_id(page, "image")   # labelled "image" since it's a PNG

        content_parts = [f"**{type_label}**"]
        if caption:
            content_parts.append(f"*Caption:* {caption}")
        content_parts.append(f"![{filename}](../{filepath})")
        content_parts.append(f"*AI Analysis:* {ai_desc}")
        content = "\n".join(content_parts)

        output = wrap_with_boundaries(
            content, "image", item_id, page,
            filename=filename,
            has_caption="yes" if caption else "no",
            breadcrumbs=" > ".join(breadcrumbs)
        )
        # Counter IS incremented — a PNG file was written to disk
        return output, image_counter + 1

    # Both stages failed — return empty string, leave counter unchanged
    return "", image_counter


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_pdf(pdf_path: Path, output_base_dir: Path, openai_client) -> Dict:
    """
    End-to-end processor for a single PDF file.

    PROCESSING PIPELINE
    -------------------
      Step 1 — Docling converts the PDF, detecting layout (text, tables, figures).
      Step 2 — Items are grouped by page into pages_items dict for sequential access.
      Step 3 — Each page is processed:
                 - Items are dispatched to the appropriate processor function
                 - Caption-consuming items (images, tables) mark the next item
                   for skip so it doesn't appear twice
                 - Page output is joined and written as a Markdown file
      Step 4 — A metadata.json index is written for the whole document.

    OUTPUT DIRECTORIES (created here)
      <output_base_dir>/<pdf_stem>/pages/     ← one .md file per page
      <output_base_dir>/<pdf_stem>/figures/   ← extracted PNG images

    Args:
        pdf_path        : absolute path to the PDF file
        output_base_dir : root output directory (e.g. ./extracted_docs_bounded)
        openai_client   : initialised OpenAI client

    Returns:
        metadata dict (also written to metadata.json in the output directory).
    """
    print(f"\n{'='*70}")
    print(f"Processing: {pdf_path.name}")
    print(f"{'='*70}")

    # Reset ID counters so this document's elements start at _1 regardless of
    # what was processed before in a batch run
    reset_id_counters()

    # Create output subdirectory structure for this document
    doc_output_dir = output_base_dir / pdf_path.stem
    (doc_output_dir / "pages").mkdir(parents=True, exist_ok=True)
    (doc_output_dir / "figures").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Docling PDF conversion
    # ------------------------------------------------------------------
    print("   [1/4] Analyzing PDF layout...")
    converter = create_docling_converter()
    conv_result = converter.convert(pdf_path)
    doc = conv_result.document
    print("      SUCCESS: Layout analysis complete")

    # ------------------------------------------------------------------
    # Step 2: Group items by page
    # ------------------------------------------------------------------
    # doc.iterate_items() yields (item, level) tuples in document order.
    # Items without prov (provenance/location data) are skipped — they have
    # no page assignment and can't be placed in the output.
    print("   [2/4] Collecting document items...")
    pages_items = defaultdict(list)

    for item, level in doc.iterate_items():
        if not item.prov:
            continue  # skip items with no page location information
        page_num = item.prov[0].page_no
        pages_items[page_num].append({"item": item, "level": level})

    print(f"      SUCCESS: Collected {sum(len(items) for items in pages_items.values())} items "
          f"across {len(pages_items)} pages")

    # ------------------------------------------------------------------
    # Step 3: Process each page
    # ------------------------------------------------------------------
    print("   [3/4] Processing items with boundaries...")

    metadata_pages = []       # list of per-page summary dicts for metadata.json
    global_breadcrumbs = []   # persists across pages — section context carries over
    total_images = 0
    total_tables = 0

    for page_num in sorted(pages_items.keys()):
        items = pages_items[page_num]
        page_outputs = []        # collects all Markdown strings for this page
        page_image_count = 0
        page_table_count = 0
        image_counter = 1        # resets per page: fig_p3_1, fig_p3_2, ...
        skip_indices = set()     # indices of items consumed as captions

        # Carry breadcrumb context from the previous page as an HTML comment
        # so readers know which section they're in even without prior pages
        if global_breadcrumbs:
            page_outputs.append(f"<!-- Context: {' > '.join(global_breadcrumbs)} -->")
        page_outputs.append(f"\n# Page {page_num}\n")

        for idx, entry in enumerate(items):
            # Skip items already consumed as captions for a preceding image/table
            if idx in skip_indices:
                continue

            item = entry["item"]
            level = entry["level"]
            # Look ahead one item — needed for caption detection in image/table processors
            next_item = items[idx + 1]["item"] if idx + 1 < len(items) else None

            # Dispatch to the appropriate processor based on Docling item type
            if isinstance(item, SectionHeaderItem):
                output, global_breadcrumbs = process_header(item, page_num, level, global_breadcrumbs)
                page_outputs.append(output)

            elif isinstance(item, TextItem):
                # Try special handling first (code block detection).
                # If not special, fall through to regular paragraph processing.
                special_output = process_special_text(item, page_num, global_breadcrumbs)
                if special_output:
                    page_outputs.append(special_output)
                else:
                    output = process_text(item, page_num, global_breadcrumbs)
                    if output:   # empty string = item was too short, skip
                        page_outputs.append(output)

            elif isinstance(item, ListItem):
                output = process_list(item, page_num, global_breadcrumbs)
                page_outputs.append(output)

            elif isinstance(item, PictureItem):
                output, image_counter = process_image(
                    item, doc, page_num, doc_output_dir,
                    image_counter, openai_client, global_breadcrumbs, next_item
                )
                if output:
                    page_outputs.append(output)
                    page_image_count += 1
                    # If the next item was used as a caption, mark it for skipping
                    # so it doesn't also appear as a standalone paragraph
                    if next_item and isinstance(next_item, TextItem):
                        text = next_item.text.strip()
                        if (text.startswith(('Exhibit', 'Figure', 'Table', 'Chart', 'Fig', 'Source:')) or
                            'Source:' in text or (len(text) < 200 and ':' in text)):
                            skip_indices.add(idx + 1)

            elif isinstance(item, TableItem):
                output, image_counter = process_table(
                    item, doc, page_num, doc_output_dir,
                    image_counter, openai_client, global_breadcrumbs, next_item
                )
                if output:
                    page_outputs.append(output)
                    page_table_count += 1
                    # Same caption-skip logic as images
                    if next_item and isinstance(next_item, TextItem):
                        text = next_item.text.strip()
                        if (text.startswith(('Exhibit', 'Figure', 'Table', 'Chart', 'Source:')) or
                            'Source:' in text or (len(text) < 200 and ':' in text)):
                            skip_indices.add(idx + 1)

        # Join all output blocks with blank lines and write the page .md file
        page_text = "\n\n".join(page_outputs)
        page_filename = f"page_{page_num}.md"
        with open(doc_output_dir / "pages" / page_filename, "w", encoding="utf-8") as f:
            f.write(page_text)

        # Record per-page summary for the metadata index
        metadata_pages.append({
            "page": page_num,
            "file": page_filename,
            "breadcrumbs": list(global_breadcrumbs),  # snapshot at end of page
            "images": page_image_count,
            "tables": page_table_count
        })

        total_images += page_image_count
        total_tables += page_table_count

    print(f"      SUCCESS: Processed {len(pages_items)} pages")
    print(f"         Images: {total_images}")
    print(f"         Tables: {total_tables}")

    # ------------------------------------------------------------------
    # Step 4: Save metadata index
    # ------------------------------------------------------------------
    # metadata.json acts as a manifest for the extracted document:
    #   - Lists all page files for easy iteration by downstream consumers
    #   - Records processing timestamp for cache invalidation
    #   - Stores element counts for quick quality checks
    print("   [4/4] Saving metadata...")
    metadata = {
        "file": pdf_path.name,
        "processed": datetime.now().isoformat(),
        "tool": "Docling Simple Bounded",
        "pages": metadata_pages,
        "total_images": total_images,
        "total_tables": total_tables
    }

    with open(doc_output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"      SUCCESS: Metadata saved")
    print(f"\n{'='*70}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*70}")
    print(f"Output: {doc_output_dir}")
    print(f"Pages: {len(metadata_pages)}")
    print(f"Images: {total_images}")
    print(f"Tables: {total_tables}")
    print(f"{'='*70}\n")

    return metadata


def process_batch(input_path: Path, output_base_dir: Path):
    """
    Entry point for processing a single PDF or a directory of PDFs.

    BATCH BEHAVIOUR
    ---------------
    - A single PDF path processes just that file.
    - A directory path discovers all *.pdf files (non-recursive) and processes
      them sequentially. Failed files are logged but don't abort the batch —
      the pipeline continues so a single corrupt PDF doesn't block the rest.

    A summary table is printed at the end showing successful and failed files,
    useful for monitoring in CI pipelines or scheduled jobs.

    Args:
        input_path      : Path to a single .pdf file or a directory
        output_base_dir : Root directory where all output subdirs are created
    """
    if not input_path.exists():
        print(f"\nERROR: Path not found: {input_path}")
        return

    if input_path.is_file():
        if input_path.suffix.lower() != '.pdf':
            print(f"\nERROR: Not a PDF file: {input_path}")
            return
        pdf_files = [input_path]
    else:
        # Glob all PDFs in the directory (non-recursive — subdirectories ignored)
        pdf_files = list(input_path.glob("*.pdf"))
        if not pdf_files:
            print(f"\nERROR: No PDF files found in: {input_path}")
            return

    # Initialise OpenAI once and share the client across all PDF jobs
    # (avoids repeated authentication overhead in batch mode)
    try:
        openai_client = OpenAI()
    except Exception as e:
        print(f"\nERROR: OpenAI client initialization failed: {str(e)}")
        print("NOTE: Set OPENAI_API_KEY environment variable")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"BATCH PROCESSING: {len(pdf_files)} PDF(s)")
    print(f"{'='*70}")

    successful = []
    failed = []

    for idx, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{idx}/{len(pdf_files)}] {pdf_path.name}")
        try:
            process_pdf(pdf_path, output_base_dir, openai_client)
            successful.append(pdf_path.name)
        except Exception as e:
            # Catch per-PDF errors so one bad file doesn't abort the whole batch
            print(f"\nERROR - FAILED: {str(e)}")
            failed.append(pdf_path.name)

    # Final summary — easy to parse for monitoring / alerting
    print(f"\n{'='*70}")
    print(f"BATCH SUMMARY")
    print(f"{'='*70}")
    print(f"Successful: {len(successful)}/{len(pdf_files)}")
    print(f"Failed: {len(failed)}/{len(pdf_files)}")

    if successful:
        print("\nSuccessfully processed:")
        for name in successful:
            print(f"   [OK] {name}")

    if failed:
        print("\nFailed to process:")
        for name in failed:
            print(f"   [FAIL] {name}")

    print(f"{'='*70}\n")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """
    Parse CLI arguments and kick off batch processing.

    Wraps process_batch() in a top-level try/except so that:
      - KeyboardInterrupt (Ctrl+C) exits cleanly without a traceback
      - Unexpected fatal errors print a clean message and exit with code 1
        (non-zero exit code signals failure to calling scripts / CI systems)
    """
    parser = argparse.ArgumentParser(
        description="Docling PDF Extractor with Boundary Markers"
    )
    parser.add_argument(
        "path", type=Path,
        help="Path to a single PDF file, or a directory containing PDFs"
    )
    parser.add_argument(
        "--output", type=Path, default=Path(OUTPUT_DIR),
        help=f"Root output directory (default: {OUTPUT_DIR})"
    )

    args = parser.parse_args()

    try:
        process_batch(args.path, args.output)
    except KeyboardInterrupt:
        print("\n\nWARNING: Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()