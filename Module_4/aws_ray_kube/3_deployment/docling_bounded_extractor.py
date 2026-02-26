"""
Docling PDF Extractor with Boundary Markers
--------------------------------------------
Functional programming version for easy understanding.

================================================================================
                    INTELLIGENT PDF EXTRACTION FOR RAG
================================================================================

This script is the FIRST STAGE of our document processing pipeline.
It converts PDFs into structured, searchable Markdown with AI-powered analysis.

Think of it as a "PDF to structured text" converter that:
✓ Preserves document structure (headers, paragraphs, tables, images)
✓ Adds AI descriptions (GPT-4o analyzes charts and tables)
✓ Wraps everything in boundary markers (for precise chunking later)
✓ Outputs clean Markdown files (one per page)

WHY THIS MATTERS FOR RAG
-------------------------
RAG (Retrieval Augmented Generation) needs:
1. Clean text chunks → We provide semantic boundaries
2. Rich metadata → We add AI descriptions and document structure
3. Preserve context → We track breadcrumbs (which section are we in?)
4. Handle complexity → We extract tables and images, not just text

Example: A PDF about clinical trials becomes:
- pages/page_1.md   ← Text with headers and context
- pages/page_2.md   ← Tables with AI analysis
- pages/page_3.md   ← Images with AI descriptions
- metadata.json     ← Index of everything

================================================================================
                              PIPELINE OVERVIEW
================================================================================

Per PDF, we execute 4 main steps:

Step 1: DOCLING PARSING
   - Docling (IBM) analyzes PDF layout
   - Detects: text blocks, tables, figures, headers, lists
   - Uses machine learning (TableFormer) for complex tables

Step 2: PAGE GROUPING
   - Items are grouped by page number
   - Creates document structure for sequential processing

Step 3: ELEMENT PROCESSING
   Each element type gets specialized handling:

   Headers    → Markdown headings (##, ###) + breadcrumb trail
   Paragraphs → Plain text with word/char counts
   Lists      → Bullet/numbered items
   Code       → Fenced code blocks with language detection
   Tables     → Two strategies:
                1. Text export (fast, cheap, preferred)
                2. Image export (fallback for complex tables)
   Images     → PNG file + GPT-4 Vision description

Step 4: BOUNDARY WRAPPING
   Every element is wrapped in HTML comments:

   <!-- BOUNDARY_START type="table" id="p5_table_1" page="5" -->
   | Revenue | 2024   |
   |---------|--------|
   | Q1      | $125M  |
   <!-- BOUNDARY_END type="table" id="p5_table_1" -->

   Why boundaries?
   - RAG chunker can extract exact elements
   - No need to re-parse Markdown
   - Preserves document structure perfectly

================================================================================
                            OUTPUT STRUCTURE
================================================================================

For a PDF named "clinical_trial.pdf", we create:

extracted_docs_bounded/
└── clinical_trial/
    ├── metadata.json           ← Index: pages, counts, processing time
    ├── pages/
    │   ├── page_1.md          ← Page 1 text with boundaries
    │   ├── page_2.md          ← Page 2 text with boundaries
    │   ├── page_3.md          ← Page 3 text with boundaries
    │   └── ...
    └── figures/
        ├── fig_p1_1.png       ← First image from page 1
        ├── fig_p2_1.png       ← First image from page 2
        └── ...

Metadata.json Example:
{
  "file": "clinical_trial.pdf",
  "processed": "2024-02-22T14:30:25",
  "pages": [
    {
      "page": 1,
      "file": "page_1.md",
      "breadcrumbs": ["Introduction", "Background"],
      "images": 2,
      "tables": 1
    }
  ],
  "total_images": 15,
  "total_tables": 8
}

================================================================================
                          BOUNDARY MARKER FORMAT
================================================================================

Boundaries are HTML comments (invisible when rendered) that carry metadata:

<!-- BOUNDARY_START type="paragraph" id="p3_text_2" page="3"
     char_count="412" word_count="68" breadcrumbs="Results > Revenue" -->
The company reported strong revenue growth in Q4 2024, with total
revenue reaching $125 million, representing a 23% increase over Q3.
<!-- BOUNDARY_END type="paragraph" id="p3_text_2" -->

Why this format?
✓ HTML comments don't interfere with Markdown rendering
✓ Structured metadata is easily parseable (regex or XML parser)
✓ Human-readable (can debug by reading the .md files)
✓ Self-documenting (every element labeled)

================================================================================
                                 USAGE
================================================================================

Single PDF:
  python docling_pdf_extractor.py clinical_trial.pdf

Directory of PDFs:
  python docling_pdf_extractor.py ./clinical_trials/

Custom output directory:
  python docling_pdf_extractor.py ./pdfs/ --output ./my_output

Requirements:
  pip install docling openai pandas tabulate
  export OPENAI_API_KEY=sk-...

================================================================================
                            DEPENDENCIES
================================================================================

Core Libraries:
- docling      : IBM's PDF extraction library (better than PyPDF2)
- openai       : GPT-4o for image/table analysis
- pandas       : Table manipulation and Markdown export
- tabulate     : Table formatting (used by pandas)

Why Docling?
✓ ML-based layout analysis (better than rule-based)
✓ Table structure preservation (not just text extraction)
✓ Image extraction with rendering
✓ Open source (no vendor lock-in)

Alternatives We Considered:
✗ PyPDF2      : Text-only, poor table handling
✗ pdfplumber  : Better than PyPDF2 but still rule-based
✗ Tesseract   : OCR for scanned PDFs (overkill for text PDFs)
✓ Docling     : Best balance of quality and ease of use

Author: Prudhvi | Thoughtworks
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
# DEPENDENCY GUARD
# ---------------------------------------------------------------------------
# Fail EARLY with a clear message if dependencies are missing.
#
# Why check imports explicitly?
# - Better error messages than "AttributeError" deep in the code
# - Tells user exactly what to install
# - Fails at startup (not after processing starts)
#
# This pattern is called "fail fast" - detect problems immediately!
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
    # Print helpful error message with installation command
    print(f"\n{'='*70}")
    print("ERROR: Missing Required Library")
    print(f"{'='*70}")
    print(f"Details: {e}")
    print("\nPlease install dependencies:")
    print("  pip install docling openai pandas tabulate")
    print("\nThen set your OpenAI API key:")
    print("  export OPENAI_API_KEY=sk-...")
    print(f"{'='*70}\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# GLOBAL CONFIGURATION CONSTANTS
# ---------------------------------------------------------------------------
# These settings control how the extraction pipeline behaves.
# They're module-level constants (ALL_CAPS) to signal "don't change at runtime"
# ---------------------------------------------------------------------------

# Default output directory if --output flag not provided
OUTPUT_DIR = "extracted_docs_bounded"

# Which OpenAI model to use for AI descriptions
# gpt-4o is required because it has Vision capability (can analyze images)
# gpt-3.5-turbo wouldn't work - no vision support
OPENAI_MODEL = "gpt-4o"

# Image rendering scale factor
# PDF images are rendered at 72 DPI by default (low quality)
# Scale × 3 = 216 DPI (high enough for GPT-4 to read chart text)
# Higher values = better quality but larger files and slower processing
IMAGE_SCALE = 3.0


# =============================================================================
# BOUNDARY MARKERS
# =============================================================================
#
# Boundary markers are the SECRET SAUCE of this extraction system!
#
# They solve a critical problem in RAG pipelines:
# "How do we know where each semantic unit (paragraph, table, image) begins
#  and ends in the Markdown output?"
#
# Without boundaries:
#   ## Introduction
#   The company reported strong results.
#   | Revenue | 2024 |
#   | Q1 | $125M |
#   The next paragraph starts here.
#
#   Problem: Where does the table end? Where does the paragraph start?
#   A chunker would have to parse Markdown to figure it out!
#
# With boundaries:
#   ## Introduction
#   <!-- BOUNDARY_START type="paragraph" id="p1_text_1" page="1" -->
#   The company reported strong results.
#   <!-- BOUNDARY_END type="paragraph" id="p1_text_1" -->
#
#   <!-- BOUNDARY_START type="table" id="p1_table_1" page="1" rows="4" -->
#   | Revenue | 2024 |
#   | Q1 | $125M |
#   <!-- BOUNDARY_END type="table" id="p1_table_1" -->
#
#   <!-- BOUNDARY_START type="paragraph" id="p1_text_2" page="1" -->
#   The next paragraph starts here.
#   <!-- BOUNDARY_END type="paragraph" id="p1_text_2" -->
#
#   Solution: Chunker uses simple regex to extract any element!
#   Pattern: <!-- BOUNDARY_START.*? --> ... <!-- BOUNDARY_END -->
#
# Benefits:
# ✓ Precise extraction (no guessing where elements end)
# ✓ Fast processing (regex vs full Markdown parser)
# ✓ Rich metadata (element type, page, breadcrumbs all in the marker)
# ✓ Debugging friendly (human-readable in raw .md files)
#
# =============================================================================

def create_boundary_start(item_type: str, item_id: str, page: int, **attrs) -> str:
    """
    Build an opening boundary comment tag.

    This creates an HTML comment that marks the START of a semantic element.
    HTML comments are invisible when Markdown is rendered, but parseable!

    Format:
    <!-- BOUNDARY_START type="table" id="p5_table_1" page="5" rows="8" columns="4" -->

    Args:
        item_type: Element category
            Examples: "paragraph", "table", "image", "header", "code"
        item_id: Unique identifier for this element
            Format: p{page}_{type}_{counter}
            Example: "p3_text_2" = second text block on page 3
        page: 1-based page number from the PDF
        **attrs: Additional key=value pairs to embed in the tag
            Examples:
            - rows=8, columns=4 (for tables)
            - language="python" (for code blocks)
            - char_count=412, word_count=68 (for text)
            - breadcrumbs="Results > Revenue" (for context)

    Returns:
        HTML comment string ready to insert in Markdown

    Example Output:
    <!-- BOUNDARY_START type="paragraph" id="p3_text_2" page="3"
         char_count="412" word_count="68" breadcrumbs="Results > Revenue" -->

    Why HTML comments?
    - Invisible in rendered Markdown (doesn't clutter display)
    - Easy to parse (simple regex or XML parser)
    - Self-documenting (readable in raw .md files)
    - Compatible with all Markdown renderers
    """
    # Build attribute string: type="paragraph" id="p3_text_2" page="3"
    attr_str = f'type="{item_type}" id="{item_id}" page="{page}"'

    # Add any extra attributes passed via **attrs
    # Example: rows=8, columns=4, language="python"
    for key, value in attrs.items():
        attr_str += f' {key}="{value}"'

    # Wrap in HTML comment syntax
    return f"<!-- BOUNDARY_START {attr_str} -->"


def create_boundary_end(item_type: str, item_id: str) -> str:
    """
    Build a closing boundary comment tag.

    The END tag mirrors the START tag, allowing parsers to:
    - Verify complete extraction (matched pair)
    - Handle truncated files (detect missing END)
    - Validate structure (ensure nesting is correct)

    Format:
    <!-- BOUNDARY_END type="table" id="p5_table_1" -->

    Args:
        item_type: Same type as the START tag
        item_id: Same ID as the START tag

    Returns:
        HTML comment string

    Why include type and id in END tag?
    - Self-documenting (clear what's closing)
    - Validation (ensure START/END match)
    - Error detection (spot mismatched pairs)

    Example Usage:
    <!-- BOUNDARY_START type="table" id="p5_table_1" page="5" -->
    | Col A | Col B |
    | ----- | ----- |
    | 1     | 2     |
    <!-- BOUNDARY_END type="table" id="p5_table_1" -->
    """
    return f'<!-- BOUNDARY_END type="{item_type}" id="{item_id}" -->'


def wrap_with_boundaries(content: str, item_type: str, item_id: str,
                         page: int, **attrs) -> str:
    """
    Convenience wrapper - sandwich content between START and END markers.

    This is the main function used by all element processors!
    It combines create_boundary_start() and create_boundary_end() with
    the actual content to produce a complete boundary-wrapped block.

    Args:
        content: The Markdown string to wrap
            Example: "The company reported strong revenue growth."
        item_type: Element category ("paragraph", "table", etc.)
        item_id: Unique element ID (generated by generate_unique_id())
        page: Page number
        **attrs: Optional metadata attributes

    Returns:
        Multi-line string: START tag + content + END tag

    Special Handling:
    - Filters out None-valued attrs (keeps tags clean)
    - Adds newlines for readability

    Example:
    wrap_with_boundaries(
        content="Revenue grew 23% in Q4.",
        item_type="paragraph",
        item_id="p3_text_2",
        page=3,
        char_count=25,
        word_count=6,
        breadcrumbs="Results > Revenue"
    )

    Returns:
    <!-- BOUNDARY_START type="paragraph" id="p3_text_2" page="3"
         char_count="25" word_count="6" breadcrumbs="Results > Revenue" -->
    Revenue grew 23% in Q4.
    <!-- BOUNDARY_END type="paragraph" id="p3_text_2" -->

    Why filter None values?
    attrs might contain optional fields like caption=None or language=None
    We don't want these appearing as caption="None" in the output!
    Example:
    - Good: has_caption="yes"
    - Bad:  has_caption="None" (misleading!)
    - Solution: Drop None-valued attrs entirely
    """
    # Filter out attributes with None values
    # Example: {caption: "Figure 1", language: None} → {caption: "Figure 1"}
    filtered_attrs = {k: v for k, v in attrs.items() if v is not None}

    # Create opening tag
    start = create_boundary_start(item_type, item_id, page, **filtered_attrs)

    # Create closing tag
    end = create_boundary_end(item_type, item_id)

    # Combine: START + newline + content + newline + END
    return f"{start}\n{content}\n{end}"


# =============================================================================
# UNIQUE ID GENERATION
# =============================================================================
#
# Every element in the extracted document needs a unique ID.
#
# WHY UNIQUE IDS?
# ---------------
# 1. Reference elements precisely
#    "Show me p3_table_2" → exact table, no ambiguity
#
# 2. Track processing
#    "Stage 2 failed on p5_image_3" → know exactly which element
#
# 3. Enable chunking
#    "Create chunk from p3_text_2 through p3_text_5"
#
# 4. Debugging
#    "The weird output is in p7_text_4" → easy to find in source PDF
#
# ID FORMAT
# ---------
# Pattern: p{page}_{type}_{counter}
#
# Examples:
# - p1_header_1  : First header on page 1
# - p3_text_2    : Second text block on page 3
# - p5_table_1   : First table on page 5
# - p7_image_3   : Third image on page 7
#
# Why this format?
# ✓ Human-readable (not random UUIDs)
# ✓ Sortable (alphabetical order = document order)
# ✓ Meaningful (includes page and type info)
# ✓ Short (easy to reference in logs)
#
# Counter Strategy:
# - Separate counter per (page, type) combination
# - page 1 text: p1_text_1, p1_text_2, p1_text_3
# - page 1 tables: p1_table_1, p1_table_2
# - page 2 text: p2_text_1, p2_text_2  (counter resets per page!)
#
# This makes IDs match the visual structure of the PDF!
#
# =============================================================================

# Module-level counter dictionary
# Key format: "p{page}_{type}"
# Value: current counter for that (page, type) pair
#
# Example state after processing page 3:
# {
#   "p3_header": 2,  # 2 headers on page 3
#   "p3_text": 5,    # 5 text blocks on page 3
#   "p3_table": 1,   # 1 table on page 3
#   "p3_image": 3    # 3 images on page 3
# }
_id_counters = defaultdict(int)


def generate_unique_id(page: int, item_type: str) -> str:
    """
    Generate a unique, human-readable element ID for the current document.

    This function is called by EVERY element processor!
    Each call increments the counter for that (page, type) pair.

    Args:
        page: Page number (1-based)
        item_type: Element type
            Examples: "header", "text", "table", "image", "code", "list"

    Returns:
        Unique ID string
        Format: p{page}_{type}_{counter}
        Example: "p3_text_2"

    How It Works:
    1. Build counter key: f"p{page}_{item_type}"
       Example: "p3_text"

    2. Increment counter for that key
       First call: _id_counters["p3_text"] = 1
       Second call: _id_counters["p3_text"] = 2
       Third call: _id_counters["p3_text"] = 3

    3. Return formatted ID
       "p3_text_1", "p3_text_2", "p3_text_3"

    Example Sequence (processing page 3):
    generate_unique_id(3, "header") → "p3_header_1"
    generate_unique_id(3, "text")   → "p3_text_1"
    generate_unique_id(3, "text")   → "p3_text_2"
    generate_unique_id(3, "table")  → "p3_table_1"
    generate_unique_id(3, "text")   → "p3_text_3"

    Why defaultdict(int)?
    - First access to any key returns 0 (default for int)
    - No need to check "if key in dict" before incrementing
    - Clean, concise code

    Thread Safety Note:
    This function is NOT thread-safe (uses shared global state).
    That's OK because we process PDFs sequentially, not in parallel.
    If we ever parallelize, we'd need per-document counter dicts.
    """
    # Build counter key: "p{page}_{type}"
    key = f"p{page}_{item_type}"

    # Increment counter for this (page, type) pair
    # defaultdict(int) means first access returns 0, then we increment to 1
    _id_counters[key] += 1

    # Return formatted ID: "p3_text_2"
    return f"{key}_{_id_counters[key]}"


def reset_id_counters():
    """
    Reset all ID counters to zero.

    CRITICAL: Must be called at the start of each PDF!

    Why?
    When processing multiple PDFs in batch mode, counters persist across
    documents unless explicitly reset. This would cause IDs from document 2
    to start at weird numbers (wherever document 1 left off).

    Example Without Reset:
    Document 1: p1_text_1, p1_text_2, p1_text_3
    Document 2: p1_text_4, p1_text_5, p1_text_6  ← BAD! Should start at 1

    Example With Reset:
    Document 1: p1_text_1, p1_text_2, p1_text_3
    reset_id_counters()  ← Called here
    Document 2: p1_text_1, p1_text_2, p1_text_3  ← GOOD! Starts fresh

    When to call:
    - At the start of process_pdf() (beginning of each PDF)
    - NOT between pages (counters should persist across pages)
    - NOT between elements (counters should increment within a page)

    What it does:
    - Clears the _id_counters dictionary
    - Recreates it as empty defaultdict(int)
    - Next call to generate_unique_id() starts from 1 again
    """
    global _id_counters
    _id_counters = defaultdict(int)


# =============================================================================
# DOCLING SETUP
# =============================================================================
#
# Docling is IBM's PDF extraction library - the ENGINE of our pipeline!
#
# Why Docling vs alternatives?
# ===========================
#
# PyPDF2:
# ✗ Text extraction only
# ✗ Poor table handling
# ✗ No layout analysis
# ✗ Can't extract images
#
# pdfplumber:
# ✓ Better than PyPDF2
# ✗ Rule-based (not ML)
# ✗ Table extraction often fails
# ~ Image extraction limited
#
# Docling:
# ✓ ML-based layout analysis (understands document structure)
# ✓ TableFormer for accurate table extraction
# ✓ Image extraction with high-quality rendering
# ✓ Open source (no vendor lock-in)
# ✓ Actively maintained by IBM Research
#
# Key Docling Features:
# ---------------------
# 1. Layout Analysis: Detects headers, paragraphs, tables, images
# 2. Table Structure: ML model preserves row/column relationships
# 3. Image Rendering: Exports figures as high-quality PNG files
# 4. Provenance Tracking: Knows which page each element came from
#
# =============================================================================

def create_docling_converter():
    """
    Construct and return a Docling DocumentConverter configured for
    high-quality PDF extraction.

    This function sets up ALL the configuration for how Docling will
    process PDFs. Each setting is carefully chosen for best results!

    Returns:
        Configured DocumentConverter instance ready to process PDFs

    Configuration Decisions:
    =======================

    1. images_scale = 3.0 (216 DPI)
       Why?
       - Default: 72 DPI (too low for GPT-4 to read chart text)
       - Our setting: 216 DPI (3× higher, GPT-4 can read text clearly)
       - Tradeoff: Larger files but better AI analysis

    2. generate_picture_images = True
       Why?
       - Saves figures as PNG files for AI analysis
       - Required for GPT-4 Vision to describe images
       - Without this: Would lose all visual content!

    3. generate_table_images = True
       Why?
       - Fallback for complex tables that can't be text-exported
       - Merged cells, nested tables → need image
       - Provides backup if TableFormer fails

    4. do_ocr = False
       Why?
       - Assumes PDF has embedded text (most modern PDFs do)
       - OCR is slow and error-prone
       - For scanned PDFs: Set to True

    5. do_table_structure = True
       Why?
       - Enables TableFormer ML model (the secret sauce!)
       - Without this: Tables become jumbled text
       - With this: Tables preserve row/column structure

    6. TableFormerMode.ACCURATE
       Why?
       - Two modes: FAST vs ACCURATE
       - FAST: ~2× faster but lower quality
       - ACCURATE: Slower but significantly better for complex tables
       - For RAG: Accuracy > speed (we process once, query many times)

    Example Configuration Comparison:

    Low Quality (PyPDF2 equivalent):
    - images_scale = 1.0
    - do_table_structure = False
    - Result: Garbled tables, low-res images

    Our Configuration:
    - images_scale = 3.0
    - TableFormerMode.ACCURATE
    - Result: Clean tables, readable images for AI

    Resource Usage:
    - CPU: Moderate (TableFormer uses ML)
    - Memory: ~1-2GB per PDF (depends on size)
    - Time: ~30-60 seconds per PDF
    """
    # ========================================================================
    # CREATE PIPELINE OPTIONS
    # ========================================================================
    # PdfPipelineOptions controls HOW Docling processes PDFs
    # Think of it as the "settings menu" for PDF extraction
    # ========================================================================
    pipeline_options = PdfPipelineOptions()

    # ------------------------------------------------------------------------
    # IMAGE RENDERING QUALITY
    # ------------------------------------------------------------------------
    # Scale factor for rendering images from PDF
    #
    # Math:
    # - PDF default: 72 DPI
    # - Our setting: 72 × 3.0 = 216 DPI
    # - 216 DPI is high enough for GPT-4 to read chart labels
    #
    # Why not higher?
    # - 300 DPI (4.2×) → huge files, negligible quality gain for AI
    # - 216 DPI is sweet spot: readable + reasonable file size
    # ------------------------------------------------------------------------
    pipeline_options.images_scale = IMAGE_SCALE

    # ------------------------------------------------------------------------
    # IMAGE GENERATION FLAGS
    # ------------------------------------------------------------------------
    # Tell Docling to actually save image files (not just detect them)
    #
    # generate_picture_images = True:
    #   Saves figures/charts as PNG files
    #   Required for GPT-4 Vision analysis
    #
    # generate_table_images = True:
    #   Saves tables as PNG files (fallback)
    #   Used when text export fails (complex merged cells, etc.)
    # ------------------------------------------------------------------------
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_table_images = True

    # ------------------------------------------------------------------------
    # OCR SETTINGS
    # ------------------------------------------------------------------------
    # do_ocr = False means:
    #   "Assume the PDF has embedded text (most PDFs do)"
    #   "Don't waste time running OCR"
    #
    # When to set do_ocr = True:
    # - Scanned documents (image of paper)
    # - Photos of documents
    # - PDFs created from screenshots
    #
    # Why False for our use case:
    # - Clinical trial PDFs are computer-generated (have text)
    # - OCR is slow (~5× slower than text extraction)
    # - OCR can introduce errors (misread characters)
    # ------------------------------------------------------------------------
    pipeline_options.do_ocr = False

    # ------------------------------------------------------------------------
    # TABLE EXTRACTION SETTINGS
    # ------------------------------------------------------------------------
    # do_table_structure = True:
    #   Enable TableFormer (Docling's ML table parser)
    #   This is the KEY FEATURE that makes Docling great!
    #
    # TableFormer is a machine learning model trained to:
    # - Detect table boundaries
    # - Identify rows and columns
    # - Handle merged cells
    # - Preserve table structure
    #
    # Without this:
    # | Name | Age | City |
    # |------|-----|------|
    # | Alice| 30  | NYC  |
    # | Bob  | 25  | LA   |
    #
    # Becomes: "Name Age City Alice 30 NYC Bob 25 LA" (useless!)
    #
    # With this:
    # Clean pandas DataFrame with proper rows/columns! ✓
    # ------------------------------------------------------------------------
    pipeline_options.do_table_structure = True

    # TableFormer Quality Mode:
    # - FAST: Quick processing, decent quality
    # - ACCURATE: Slower but much better quality
    #
    # For RAG pipelines:
    # - We process documents ONCE
    # - We query them MANY times
    # - Quality > speed (better to wait 2× longer for 10× better results)
    #
    # ACCURATE mode handles:
    # - Complex merged cells
    # - Multi-row headers
    # - Nested tables
    # - Irregular table layouts
    # ------------------------------------------------------------------------
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

    # ========================================================================
    # CREATE DOCUMENT CONVERTER
    # ========================================================================
    # DocumentConverter is the main Docling class that processes PDFs
    # We configure it with our carefully chosen options above
    # ========================================================================
    return DocumentConverter(
        format_options={
            # Apply our pipeline options to PDF inputs
            # (Docling also supports other formats like DOCX, but we only use PDF)
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


# =============================================================================
# AI DESCRIPTIONS
# =============================================================================
#
# GPT-4o is used for TWO AI analysis tasks in our pipeline:
#
# 1. TABLE DESCRIPTION
#    Input:  Markdown table text
#    Output: Analysis of purpose, structure, key insights
#    Why:    Tables are data-dense, AI extracts meaning
#    Cost:   Cheap (text-only, ~150 tokens)
#
# 2. IMAGE DESCRIPTION
#    Input:  PNG image (base64-encoded)
#    Output: Visual analysis (chart type, trends, insights)
#    Why:    Charts are visual, need Vision model
#    Cost:   More expensive (image tokens + text)
#
# Why AI Descriptions?
# ===================
# RAG works by semantic search - finding relevant chunks.
# Without AI:
#   Query: "revenue growth trends"
#   Table: | Q1 | Q2 | Q3 | Q4 |
#          | $100M | $110M | $125M | $140M |
#   Match: NO (query words not in table!)
#
# With AI:
#   AI Description: "Quarterly revenue showing strong growth trend,
#                     from $100M in Q1 to $140M in Q4, 40% increase"
#   Match: YES! (semantic match with "revenue growth trends")
#
# Cost Optimization:
# =================
# We keep costs low by:
# - max_tokens=150 for tables (short descriptions)
# - max_tokens=200 for images (slightly longer for visual analysis)
# - Text-first strategy for tables (cheaper than vision)
#
# Error Handling:
# ==============
# AI calls can fail (rate limits, network errors, API issues)
# We NEVER let AI failures break the pipeline!
# - Catch all exceptions
# - Return placeholder description
# - Pipeline continues, document still gets extracted
#
# =============================================================================

def describe_table_with_ai(table_text: str, openai_client, caption: str = None) -> str:
    """
    Ask GPT-4o to describe a table's purpose, structure, and key takeaways.

    This function sends the table as MARKDOWN TEXT (not an image!)
    Why text vs image?
    ✓ Cheaper (text tokens < image tokens)
    ✓ Faster (no image rendering needed)
    ✓ Lossless (exact cell values preserved)
    ✓ Better for structured data (AI sees actual numbers)

    Args:
        table_text: Markdown-formatted table string
            Example:
            | Revenue | Q1    | Q2    | Q3    | Q4    |
            |---------|-------|-------|-------|-------|
            | 2024    | $100M | $110M | $125M | $140M |

        openai_client: Initialized OpenAI client instance

        caption: Optional caption text for context
            Example: "Exhibit 3: Quarterly Revenue FY2024"
            Including caption helps AI understand what table represents

    Returns:
        AI-generated description string, or error message on failure

    Example Output:
    "This table shows quarterly revenue progression for 2024,
     demonstrating consistent growth from $100M in Q1 to $140M in Q4,
     representing a 40% increase over the year."

    Prompt Engineering:
    ==================
    Our prompt asks for:
    1. Purpose: What is this table showing?
    2. Structure: How is the data organized?
    3. Key information: What are the important takeaways?

    Why concise?
    - Keeps token costs down (max_tokens=150)
    - Fits nicely in RAG chunk metadata
    - Highlights most important insights

    Cost Calculation:
    ================
    GPT-4o pricing (as of 2024):
    - Input: $2.50 per 1M tokens
    - Output: $10 per 1M tokens

    Typical table:
    - Input: ~200 tokens (prompt + table)
    - Output: ~100 tokens (description)
    - Cost: (200 × $2.50 + 100 × $10) / 1M = $0.0015

    100 tables = $0.15 (cheap!)
    """
    try:
        # ====================================================================
        # BUILD PROMPT
        # ====================================================================
        # Clear, specific instructions get better results
        # We ask for: purpose, structure, key information (all in one)
        # ====================================================================
        prompt = "Analyze this table. Describe its purpose, structure, and key information concisely."

        # ====================================================================
        # ADD CAPTION IF AVAILABLE
        # ====================================================================
        # Captions provide valuable context!
        # Example: "Exhibit 3: Revenue by Region FY2024"
        # This helps AI understand that table shows regional breakdown
        # ====================================================================
        if caption:
            prompt += f"\n\nCaption: {caption}"

        # Add the actual table text
        prompt += f"\n\nTable:\n{table_text}"

        # ====================================================================
        # CALL OPENAI API
        # ====================================================================
        # chat.completions.create is the main API call
        # We use gpt-4o (has best reasoning for analysis)
        # ====================================================================
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150   # Keep descriptions short to control costs
        )

        # Extract text from response
        return response.choices[0].message.content

    except Exception as e:
        # ====================================================================
        # ERROR HANDLING
        # ====================================================================
        # AI call failed! Don't crash the pipeline.
        #
        # Common failures:
        # - Rate limit exceeded (429 error)
        # - API key invalid (401 error)
        # - Network timeout
        # - Service temporarily down
        #
        # We return an error placeholder so:
        # - Table still gets extracted
        # - User knows AI failed
        # - Pipeline continues
        # ====================================================================
        return f"AI description failed: {str(e)}"


def describe_image_with_ai(image_path: Path, openai_client, caption: str = None) -> str:
    """
    Ask GPT-4o Vision to analyze a chart or figure image.

    This function uses GPT-4 VISION capability to understand visual content.
    The image is base64-encoded and sent as a data URL.

    Why base64 data URL instead of file upload?
    ✓ Self-contained (everything in one API call)
    ✓ No separate upload step
    ✓ No expiring signed URLs
    ✓ Works same in local dev and production
    ✓ Simpler error handling

    Args:
        image_path: Path to the saved PNG file on disk
            Example: /tmp/extracted/figures/fig_p3_2.png

        openai_client: Initialized OpenAI client instance

        caption: Optional caption text for additional context
            Example: "Figure 2: Monthly Sales Trend 2024"

    Returns:
        AI-generated visual analysis string, or error message on failure

    Example Output:
    "Line chart showing monthly sales from Jan-Dec 2024. Y-axis represents
     revenue in millions, X-axis shows months. Clear upward trend visible,
     with significant spike in Q4 (Nov-Dec). Sales grew from ~$10M to ~$25M."

    Prompt Engineering:
    ==================
    Our prompt asks for:
    1. Classification: What TYPE of visual? (Chart/Diagram/Data Table)
    2. Structure: What are the axes? What's being measured?
    3. Insights: What are the key trends or takeaways?

    Why this structure?
    - Type: Helps downstream filtering ("show me all bar charts")
    - Structure: Provides context for search
    - Insights: Captures semantic meaning for RAG

    Base64 Encoding:
    ===============
    We need to convert the image file to base64 because:
    - API expects data URL format: data:image/png;base64,{encoded_data}
    - Can't send binary data directly in JSON
    - Base64 is text-safe (works in JSON/HTTP)

    Process:
    1. Read image file as binary
    2. Encode bytes to base64 string
    3. Wrap in data URL format
    4. Send to API

    Cost Calculation:
    ================
    GPT-4o Vision pricing:
    - Images charged by token count (varies by size)
    - 216 DPI PNG ~= 1500 image tokens
    - Plus ~100 text tokens (prompt + response)
    - Total: ~1600 tokens per image
    - Cost: ~$0.004 per image

    100 images = $0.40 (reasonable!)
    """
    try:
        # ====================================================================
        # READ AND ENCODE IMAGE
        # ====================================================================
        # Convert image file to base64 string for API
        #
        # Steps:
        # 1. Open file in binary mode
        # 2. Read all bytes
        # 3. base64.b64encode() converts bytes to base64 bytes
        # 4. .decode('utf-8') converts base64 bytes to string
        # ====================================================================
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')

        # ====================================================================
        # BUILD PROMPT
        # ====================================================================
        # Ask for comprehensive visual analysis
        # - Classification (what type of visual?)
        # - Structure (axes, labels, components)
        # - Insights (trends, patterns, takeaways)
        # ====================================================================
        prompt = "Analyze this visual. Is it a Chart, Diagram, or Data Table? "
        prompt += "Describe the axes, trends, and key insights concisely."

        # Add caption if available (provides context)
        if caption:
            prompt += f"\n\nCaption/Context: {caption}"

        # ====================================================================
        # CALL OPENAI VISION API
        # ====================================================================
        # The message content is a LIST containing:
        # 1. Text part (the prompt)
        # 2. Image part (the data URL)
        #
        # This multi-modal format lets GPT-4 see both text and image!
        # ====================================================================
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,  # gpt-4o (has vision capability)
            messages=[{
                "role": "user",
                "content": [
                    # TEXT PART
                    {"type": "text", "text": prompt},

                    # IMAGE PART
                    # data URL format: data:{mime_type};base64,{encoded_bytes}
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64}"
                    }}
                ]
            }],
            max_tokens=200   # Slightly more than tables (visual analysis needs more detail)
        )

        return response.choices[0].message.content

    except Exception as e:
        # ====================================================================
        # ERROR HANDLING
        # ====================================================================
        # Vision API failures are handled gracefully
        # Common issues:
        # - Image too large (>20MB limit)
        # - Invalid base64 encoding
        # - Rate limit exceeded
        # - Unsupported image format (WEBP, TIFF)
        #
        # We return error placeholder but keep processing
        # ====================================================================
        return f"AI description failed: {str(e)}"


# =============================================================================
# IMAGE PROCESSING
# =============================================================================
#
# This section handles extracting images from PDFs and getting AI descriptions.
#
# Why Separate from process_image() and process_table()?
# ======================================================
#
# The same image extraction logic is used in TWO places:
# 1. process_image() - for figures/charts
# 2. process_table() - for tables that failed text export
#
# By centralizing extraction here, we:
# ✓ Avoid code duplication
# ✓ Ensure consistent behavior
# ✓ Make testing easier (test once, works in both paths)
# ✓ Simplify maintenance (fix bugs in one place)
#
# =============================================================================

def extract_and_save_image(item, doc, page_num: int, output_dir: Path,
                            image_counter: int, openai_client,
                            caption: str = None, is_table: bool = False
                           ) -> Optional[Tuple[str, str, str, str]]:
    """
    Extract a Docling image/table item to a PNG file and get its AI description.

    This is a SHARED UTILITY used by both:
    - process_image() : For regular figures/charts
    - process_table() : For tables that failed text export (fallback)

    Flow:
    1. Get image object from Docling item
    2. Save as PNG file
    3. Call AI to describe the image
    4. Return filename, path, description, type

    Args:
        item: Docling PictureItem or TableItem
            The source item to extract image from

        doc: Parent Docling document
            Needed by item.get_image() to access the PDF data

        page_num: Page number for filename generation

        output_dir: Document-level output directory
            Example: /tmp/extracted/clinical_trial/
            We'll save to: {output_dir}/figures/fig_p{page}_{counter}.png

        image_counter: Current sequential counter for this page
            Used in filename: fig_p3_2.png (second figure on page 3)

        openai_client: Initialized OpenAI client for AI description

        caption: Optional caption text for richer AI context
            Example: "Figure 2: Monthly Sales Trend"

        is_table: True if this is a table (not a regular image)
            Affects:
            - Type label: "Table/Chart" vs "Image"
            - AI prompt context

    Returns:
        Tuple of (filename, relative_filepath, ai_description, type_label)
        Example: ("fig_p3_2.png", "figures/fig_p3_2.png",
                  "Line chart showing...", "Image")

        Returns None if extraction fails (non-fatal)

    Why Return Tuple?
    ================
    We need multiple pieces of information from extraction:
    - filename: For logging and Markdown image links
    - relative_filepath: For correct links from pages/ subdirectory
    - ai_description: For metadata and search
    - type_label: "Image" vs "Table/Chart" (for classification)

    Filename Convention:
    ===================
    Format: fig_p{page}_{counter}.png

    Examples:
    - fig_p1_1.png : First figure on page 1
    - fig_p3_2.png : Second figure on page 3
    - fig_p5_3.png : Third figure on page 5

    Why this format?
    ✓ Sortable (alphabetical = document order)
    ✓ Page-specific (easy to locate in source PDF)
    ✓ Sequential (unique within each page)

    Error Handling:
    ==============
    Extraction can fail if:
    - Docling can't render the image (corrupted PDF element)
    - Image is encrypted or DRM-protected
    - Disk space full
    - Permission error writing file

    We return None on failure (non-fatal):
    - Caller handles None gracefully
    - Document still gets extracted (minus this image)
    - Error is logged but doesn't crash pipeline
    """
    try:
        # ====================================================================
        # STEP 1: GET IMAGE OBJECT FROM DOCLING
        # ====================================================================
        # item.get_image(doc) renders the PDF element to a PIL Image object
        # Returns None if rendering fails (corrupted, encrypted, etc.)
        # ====================================================================
        img_obj = item.get_image(doc)

        if not img_obj:
            # Rendering failed - return None to signal "skip this image"
            return None

        # ====================================================================
        # STEP 2: GENERATE FILENAME
        # ====================================================================
        # Filename format: fig_p{page}_{counter}.png
        # Example: fig_p3_2.png (second figure on page 3)
        #
        # Why include page in filename?
        # - Easy to correlate with source PDF
        # - Debugging: "The bad image is fig_p5_3" → check page 5
        # ====================================================================
        filename = f"fig_p{page_num}_{image_counter}.png"

        # Build full path: {output_dir}/figures/{filename}
        filepath = output_dir / "figures" / filename

        # ====================================================================
        # STEP 3: SAVE IMAGE TO DISK
        # ====================================================================
        # img_obj is a PIL Image object with a .save() method
        # This writes the PNG file to disk
        # ====================================================================
        img_obj.save(filepath)

        # ====================================================================
        # STEP 4: GET AI DESCRIPTION
        # ====================================================================
        # Send the saved PNG to GPT-4 Vision for analysis
        # Caption is included for additional context
        # ====================================================================
        ai_desc = describe_image_with_ai(filepath, openai_client, caption)

        # ====================================================================
        # STEP 5: DETERMINE TYPE LABEL
        # ====================================================================
        # Label the element based on what it is:
        # - Regular image: "Image"
        # - Table image: "Table/Chart" (more specific)
        # ====================================================================
        type_label = "Table/Chart" if is_table else "Image"

        # ====================================================================
        # STEP 6: BUILD RELATIVE PATH
        # ====================================================================
        # Markdown files are in pages/ subdirectory
        # Images are in figures/ subdirectory
        # We need relative path from pages/ to figures/:
        #
        # From:      output_dir/pages/page_1.md
        # To:        output_dir/figures/fig_p1_1.png
        # Relative:  ../figures/fig_p1_1.png
        #
        # This ensures image links work when viewing the Markdown!
        # ====================================================================
        relative_path = str(filepath.relative_to(output_dir))

        # Return all the information as a tuple
        return (filename, relative_path, ai_desc, type_label)

    except Exception as e:
        # ====================================================================
        # ERROR HANDLING
        # ====================================================================
        # Non-fatal error - log and return None
        # Caller will handle None by skipping this image
        # Document processing continues
        # ====================================================================
        print(f"   WARNING: Image extraction failed: {str(e)}")
        return None


# =============================================================================
# ITEM PROCESSORS
# =============================================================================
#
# This section contains specialized processor functions for each Docling item type.
#
# The Processor Pattern:
# ======================
#
# Each processor is a PURE FUNCTION that:
# 1. Accepts a Docling item + context (page, breadcrumbs, etc.)
# 2. Generates a unique ID for the element
# 3. Formats the element as Markdown
# 4. Wraps it in boundary markers
# 5. Returns the boundary-wrapped string
#
# Processors we have:
# - process_header()       : Section headers (##, ###, etc.)
# - process_text()         : Regular paragraphs
# - process_list()         : Bullet/numbered lists
# - process_special_text() : Code blocks (detected via heuristics)
# - process_image()        : Figures/charts
# - process_table()        : Data tables (text-first, image-fallback)
#
# Why Pure Functions?
# ==================
# Pure functions are:
# ✓ Easy to test (no side effects except _id_counters)
# ✓ Easy to understand (input → output, no hidden state)
# ✓ Easy to debug (can test each processor independently)
# ✓ Easy to modify (change one without breaking others)
#
# All processors follow the same contract:
# - Accept item + page + context
# - Return boundary-wrapped Markdown string
# - Return empty string or None to signal "skip"
#
# =============================================================================

def process_header(item: SectionHeaderItem, page: int, level: int,
                   breadcrumbs: List[str]) -> Tuple[str, List[str]]:
    """
    Convert a section header into a Markdown heading and update breadcrumb trail.

    BREADCRUMB TRAIL - THE SECRET SAUCE FOR CONTEXT!
    ================================================

    Breadcrumbs track WHERE WE ARE in the document hierarchy.
    This is CRITICAL for RAG because it provides context!

    Example Document Structure:

    # Financial Results              ← Level 1
      ## Revenue                      ← Level 2
        ### Q4 Performance            ← Level 3
          Revenue grew 12%            ← Paragraph

    Breadcrumb Trail:
    ["Financial Results", "Revenue", "Q4 Performance"]

    Now when we chunk "Revenue grew 12%", we know it's in:
    Financial Results > Revenue > Q4 Performance

    Without breadcrumbs:
    Query: "Q4 revenue performance"
    Chunk: "Revenue grew 12%"
    Match: WEAK (missing context!)

    With breadcrumbs:
    Query: "Q4 revenue performance"
    Chunk: "Revenue grew 12%"
    Metadata: "Financial Results > Revenue > Q4 Performance"
    Match: STRONG! ✓

    How Breadcrumbs Work:
    ====================

    1. Start with empty list: []

    2. See Level-1 header "Results":
       Breadcrumbs = ["Results"]

    3. See Level-2 header "Revenue":
       Breadcrumbs = ["Results", "Revenue"]

    4. See Level-2 header "Expenses" (same level as Revenue):
       Truncate to level-1, then append:
       Breadcrumbs = ["Results", "Expenses"]

    5. See Level-3 header "Q4":
       Breadcrumbs = ["Results", "Expenses", "Q4"]

    This mirrors how a Table of Contents works!

    Args:
        item: Docling SectionHeaderItem
            Contains: .text (header text), .level (depth in hierarchy)

        page: Current page number

        level: Heading depth
            1 = top-level chapter
            2 = section
            3 = subsection
            etc.

        breadcrumbs: Current document path (MUTABLE list!)
            Example: ["Results", "Revenue"]
            This list is MODIFIED in place!

    Returns:
        Tuple of (wrapped_markdown, updated_breadcrumbs)

        Example:
        ("<!-- BOUNDARY_START ... -->
## Revenue
<!-- BOUNDARY_END ... -->",
         ["Results", "Revenue"])

    Markdown Heading Levels:
    =======================

    We use # for page title, so section headers start at ##:

    Page:    # Page 3
    Level 1: ## Introduction
    Level 2: ### Background
    Level 3: #### Methodology

    Formula: '#' * (level + 1)
    - level=1 → ## (two hashes)
    - level=2 → ### (three hashes)
    - level=3 → #### (four hashes)
    """
    # ========================================================================
    # EXTRACT HEADER TEXT
    # ========================================================================
    text = item.text.strip()

    # ========================================================================
    # UPDATE BREADCRUMB TRAIL
    # ========================================================================
    # Truncate breadcrumbs to parent level before adding new header
    #
    # Example:
    # Current: ["Results", "Revenue", "Q4"]  (level 3)
    # New header: "Expenses" (level 2)
    #
    # Step 1: Truncate to level 1 (parent of level 2)
    #         breadcrumbs[:level-1] = breadcrumbs[:1] = ["Results"]
    #
    # Step 2: Append new header
    #         breadcrumbs = ["Results", "Expenses"]
    #
    # This ensures breadcrumbs always reflect current hierarchy!
    # ========================================================================
    if len(breadcrumbs) >= level:
        breadcrumbs = breadcrumbs[:level - 1]
    breadcrumbs.append(text)

    # ========================================================================
    # GENERATE UNIQUE ID
    # ========================================================================
    item_id = generate_unique_id(page, "header")

    # ========================================================================
    # FORMAT AS MARKDOWN HEADING
    # ========================================================================
    # +1 to level because:
    # - Level 0 would be # (page title)
    # - Level 1 should be ## (top section)
    # - Level 2 should be ### (subsection)
    #
    # Example: level=2 → '###' (3 hashes)
    # ========================================================================
    content = f"{'#' * (level + 1)} {text}"

    # ========================================================================
    # WRAP WITH BOUNDARIES
    # ========================================================================
    # Include level and breadcrumbs in metadata
    # These help downstream processing understand document structure
    # ========================================================================
    output = wrap_with_boundaries(
        content, "header", item_id, page,
        level=level,
        breadcrumbs=" > ".join(breadcrumbs)  # "Results > Revenue > Q4"
    )

    return output, breadcrumbs


def process_text(item: TextItem, page: int, breadcrumbs: List[str]) -> str:
    """
    Wrap a regular text paragraph in boundary markers with metadata.

    This is the MOST COMMON processor - handles normal paragraphs!

    What it does:
    1. Extract text from Docling TextItem
    2. Filter out noise (single-character fragments)
    3. Count words and characters
    4. Wrap in boundaries with metadata

    Args:
        item: Docling TextItem
            Contains: .text (paragraph text)

        page: Current page number

        breadcrumbs: Current document path
            Example: ["Results", "Revenue", "Q4"]
            Provides context for this paragraph

    Returns:
        Boundary-wrapped Markdown string, or "" if text is too short

    Metadata Included:
    =================

    char_count: Total characters
        Why? Helps chunking strategies target specific sizes
        Example: "Only include paragraphs with >200 chars"

    word_count: Total words
        Why? Another chunking dimension
        Example: "Chunks should be ~300 words"

    breadcrumbs: Current section path
        Why? Provides semantic context for search
        Example: Paragraph about "revenue" in "Q4 > Revenue" section

    Filtering Strategy:
    ==================

    We skip very short text (≤1 character) because:
    - OCR artifacts: Stray punctuation, dots, dashes
    - Layout noise: Page numbers, decorative elements
    - No semantic value: Can't be meaningfully searched

    Examples of filtered content:
    - "." (single period)
    - "-" (decorative dash)
    - "•" (bullet point without text)

    These would clutter the output without adding value!

    Example Output:
    ==============

    <!-- BOUNDARY_START type="paragraph" id="p3_text_2" page="3"
         char_count="156" word_count="28"
         breadcrumbs="Results > Revenue > Q4" -->
    The company reported strong revenue growth in Q4 2024, with total
    revenue reaching $125 million, representing a 23% increase over Q3
    and exceeding analyst expectations.
    <!-- BOUNDARY_END type="paragraph" id="p3_text_2" -->
    """
    # ========================================================================
    # EXTRACT AND CLEAN TEXT
    # ========================================================================
    text = item.text.strip()

    # ========================================================================
    # FILTER OUT NOISE
    # ========================================================================
    # Skip single characters - usually OCR artifacts or layout noise
    # Example: ".", "-", "•", "1" (page number)
    #
    # Why ≤1 instead of ==1?
    # - Also catches empty strings (len("")==0)
    # - Defensive programming (handles edge cases)
    # ========================================================================
    if len(text) <= 1:
        return ""  # Signal caller to skip this item

    # ========================================================================
    # GENERATE UNIQUE ID
    # ========================================================================
    item_id = generate_unique_id(page, "text")

    # ========================================================================
    # WRAP WITH BOUNDARIES + METADATA
    # ========================================================================
    return wrap_with_boundaries(
        text, "paragraph", item_id, page,
        char_count=len(text),           # Total characters
        word_count=len(text.split()),   # Simple word count (split on whitespace)
        breadcrumbs=" > ".join(breadcrumbs)  # Section path
    )


def process_list(item: ListItem, page: int, breadcrumbs: List[str]) -> str:
    """
    Format a list item with its bullet marker and wrap in boundaries.

    Lists in PDFs can be:
    - Unordered (bullets): •, -, *, ○
    - Ordered (numbers): 1., 2., 3., etc.
    - Custom markers: →, ✓, a), i., etc.

    Docling exposes the marker via item.enumeration attribute.
    We preserve whatever marker the PDF used!

    Args:
        item: Docling ListItem
            Contains: .text (list item text), .enumeration (bullet marker)

        page: Current page number

        breadcrumbs: Current document path

    Returns:
        Boundary-wrapped Markdown list item

    Example PDFs and Their Markers:
    ==============================

    PDF Content:
    • First item
    • Second item

    Docling ListItem:
    - item.enumeration = "•"
    - item.text = "First item"

    Our Output:
    • First item

    ---

    PDF Content:
    1. First item
    2. Second item

    Docling ListItem:
    - item.enumeration = "1."
    - item.text = "First item"

    Our Output:
    1. First item

    Fallback Strategy:
    =================

    If item.enumeration is not set (some PDFs don't have markers),
    we default to "-" (standard Markdown bullet).

    getattr(item, 'enumeration', '-') means:
    - If item has enumeration attribute → use it
    - If not → use '-' as default

    This ensures output is always valid Markdown!

    Why Preserve Original Markers?
    =============================

    Different marker types have semantic meaning:
    - Bullets (•) : Related items
    - Numbers (1.) : Sequential steps
    - Checkboxes (☐) : Tasks/requirements

    Preserving markers maintains the author's intent!

    Example Output:
    ==============

    <!-- BOUNDARY_START type="list" id="p5_list_3" page="5"
         breadcrumbs="Methodology > Data Collection" -->
    • Survey participants were recruited from three sources
    <!-- BOUNDARY_END type="list" id="p5_list_3" -->
    """
    # ========================================================================
    # EXTRACT MARKER AND TEXT
    # ========================================================================
    # getattr with default handles items where enumeration is not set
    # Fallback to "-" ensures we always have a valid marker
    # ========================================================================
    marker = getattr(item, 'enumeration', '-')
    text = item.text.strip()

    # ========================================================================
    # FORMAT AS MARKDOWN LIST ITEM
    # ========================================================================
    # Combine marker and text with a space
    # Example: "• First item" or "1. First item"
    # ========================================================================
    content = f"{marker} {text}"

    # ========================================================================
    # GENERATE ID AND WRAP
    # ========================================================================
    item_id = generate_unique_id(page, "list")

    return wrap_with_boundaries(
        content, "list", item_id, page,
        breadcrumbs=" > ".join(breadcrumbs)
    )


def process_special_text(item: TextItem, page: int, breadcrumbs: List[str]) -> Optional[str]:
    """
    Detect code blocks within a TextItem and wrap them in fenced code blocks.

    HEURISTIC CODE DETECTION
    ========================

    We use pattern matching to detect code without needing explicit markers.

    Code Signals:
    - Indentation (starts with spaces or tabs)
    - Already has fences (```)
    - Python keywords (def, class, import)
    - JavaScript keywords (function, const, let)
    - C-style syntax ({ } ;)

    Example Text Items:

    NOT CODE:
    "The function of this analysis is to determine..."
    → Has word "function" but not a code pattern

    IS CODE:
    "def calculate_revenue(q1, q2, q3, q4):
         return q1 + q2 + q3 + q4"
    → Has "def", indentation, Python syntax

    Language Detection:
    ==================

    Lightweight keyword-based detection:

    Python indicators:
    - "python" in text (explicit)
    - "def " or "import " or "class " (Python syntax)

    JavaScript indicators:
    - "function" or "const " or "let " (JS syntax)

    Unknown:
    - Code detected but language unclear

    Why Not Formulas?
    ================

    Formula detection was DISABLED because of too many false positives!

    False Positive Example:
    "The study (n=100) showed significant results (p<0.05)"
    → Has parentheses and numbers
    → Heuristic thinks it's a formula!
    → But it's just regular text

    For future formula support:
    - Use explicit LaTeX delimiters ($...$, $$...$$)
    - Don't rely on heuristics

    Args:
        item: Docling TextItem (might be code, might be regular text)
        page: Current page number
        breadcrumbs: Current document path

    Returns:
        Boundary-wrapped fenced code block if code detected
        None if not code (signals caller to use process_text() instead)

    Example Output:
    ==============

    <!-- BOUNDARY_START type="code" id="p8_code_1" page="8"
         language="python" breadcrumbs="Appendix > Code Samples" -->
    ```python
    def calculate_roi(revenue, cost):
        return (revenue - cost) / cost * 100
    ```
    <!-- BOUNDARY_END type="code" id="p8_code_1" -->

    Return Value Pattern:
    ====================

    - Returns string → Code detected, use this output
    - Returns None → Not code, fall back to process_text()

    This pattern lets us try special handling first,
    then fall through to regular text if not special!
    """
    text = item.text.strip()

    # ========================================================================
    # MINIMUM LENGTH CHECK
    # ========================================================================
    # Very short strings can't reliably be code
    # Example: "x" or "{}" might match patterns but aren't code blocks
    # ========================================================================
    if len(text) < 3:
        return None

    # ========================================================================
    # HEURISTIC CODE DETECTION
    # ========================================================================
    # Check for multiple code indicators
    # More matches = higher confidence it's code
    # ========================================================================
    is_code = (
        # Indentation patterns
        text.startswith('    ') or        # 4-space indent
        text.startswith('\t') or          # Tab indent

        # Already has code fences
        '```' in text or

        # Python-specific patterns
        text.count('def ') > 0 or         # Function definition
        text.count('class ') > 0 or       # Class definition
        text.count('import ') > 0 or      # Import statement

        # JavaScript-specific patterns
        text.count('function ') > 0 or    # Function declaration

        # C-style block structure
        ('{' in text and '}' in text and ';' in text)
    )

    if is_code:
        # ====================================================================
        # LANGUAGE DETECTION
        # ====================================================================
        # Simple keyword matching for common languages
        # Empty string if language can't be determined
        # ====================================================================
        language = ''

        # Python detection
        if ('python' in text.lower() or    # Explicit mention
            'def ' in text or              # Function def
            'import ' in text):            # Import statement
            language = 'python'

        # JavaScript detection
        elif ('function' in text or        # Function keyword
              'const ' in text or          # const declaration
              'let ' in text):             # let declaration
            language = 'javascript'

        # ====================================================================
        # FORMAT AS FENCED CODE BLOCK
        # ====================================================================
        # Markdown fenced code block syntax:
        # ```language
        # code here
        # ```
        # ====================================================================
        content = f"```{language}\n{text}\n```"

        # Generate ID and wrap
        item_id = generate_unique_id(page, "code")

        return wrap_with_boundaries(
            content, "code", item_id, page,
            language=language if language else "unknown",
            breadcrumbs=" > ".join(breadcrumbs)
        )

    # ========================================================================
    # NOT CODE - FORMULA DETECTION INTENTIONALLY DISABLED
    # ========================================================================
    # Formula detection was removed due to false positives
    #
    # If you need formula support in the future:
    # - Look for explicit LaTeX delimiters: $...$, $$...$$
    # - Don't use heuristics (parentheses, numbers, etc.)
    # - LaTeX detection is much more reliable than patterns
    # ========================================================================

    # Not code → return None to signal "use regular text processing"
    return None


def process_image(item: PictureItem, doc, page: int, output_dir: Path,
                  image_counter: int, openai_client, breadcrumbs: List[str],
                  next_item=None) -> Tuple[str, int]:
    """
    Extract a figure/picture, save it, get AI description, return wrapped Markdown.

    CAPTION DETECTION
    ================

    Docling can detect when text is a caption for a figure!
    The item.label attribute will be 'caption' for caption text.

    Example PDF Layout:
    [IMAGE]
    Figure 2: Monthly Sales Trend 2024

    Docling Item Stream:
    1. PictureItem (the image)
    2. TextItem with label='caption' (the caption text)

    We look ahead to next_item to check if it's a caption.
    If yes, we:
    - Include it in the boundary metadata
    - Pass it to AI for richer context
    - Mark it for skipping (so it doesn't appear twice)

    Args:
        item: Docling PictureItem to process
        doc: Parent Docling document
        page: Current page number
        output_dir: Document-level output directory
        image_counter: Current counter for figures on this page
        openai_client: Initialized OpenAI client
        breadcrumbs: Current document path
        next_item: Next item in the page stream (for caption detection)

    Returns:
        Tuple of (boundary_wrapped_markdown, updated_image_counter)

        Returns ("", image_counter) if extraction fails

    IMAGE COUNTER TRACKING
    =====================

    The counter ensures unique filenames within each page:
    - Page 3, first image:  fig_p3_1.png  (counter=1)
    - Page 3, second image: fig_p3_2.png  (counter=2)
    - Page 3, table image:  fig_p3_3.png  (counter=3)
    - Page 4, first image:  fig_p4_1.png  (counter resets!)

    We increment and return the counter so the caller can
    pass the updated value to the next image/table on this page.

    Why Not Use generate_unique_id() Counter?
    =========================================

    Different purposes:
    - generate_unique_id(): For element IDs in boundaries
    - image_counter: For filenames on disk

    Image filenames are shared between images AND tables
    (both go in figures/), so they need a unified counter.

    Element IDs are per-type, so we track them separately.

    Example Output:
    ==============

    <!-- BOUNDARY_START type="image" id="p3_image_2" page="3"
         filename="fig_p3_2.png" has_caption="yes"
         breadcrumbs="Results > Charts" -->
    **Image**
    *Caption:* Figure 2: Monthly Sales Trend 2024
    ![fig_p3_2.png](../figures/fig_p3_2.png)
    *AI Analysis:* Line chart showing monthly sales from January to
    December 2024. Y-axis represents revenue in millions, X-axis shows
    months. Clear upward trend visible with significant spike in Q4.
    <!-- BOUNDARY_END type="image" id="p3_image_2" -->
    """
    # ========================================================================
    # CAPTION DETECTION
    # ========================================================================
    # Check if the NEXT item in the stream is this image's caption
    # Docling assigns label='caption' to caption text blocks
    # ========================================================================
    caption = None
    if next_item and isinstance(next_item, TextItem):
        label = next_item.label
        text = next_item.text.strip()

        # Docling's caption detection is reliable!
        if label == 'caption':
            caption = text

    # ========================================================================
    # EXTRACT AND SAVE IMAGE
    # ========================================================================
    # Delegate to shared extraction function
    # This handles: rendering, saving, AI description
    # ========================================================================
    img_result = extract_and_save_image(
        item, doc, page, output_dir, image_counter,
        openai_client, caption=caption, is_table=False
    )

    if not img_result:
        # Extraction failed → return empty string, don't increment counter
        return "", image_counter

    # Unpack extraction results
    filename, filepath, ai_desc, type_label = img_result

    # ========================================================================
    # GENERATE UNIQUE ID
    # ========================================================================
    item_id = generate_unique_id(page, "image")

    # ========================================================================
    # BUILD MARKDOWN CONTENT
    # ========================================================================
    # Structure:
    # **Image**                    ← Type label
    # *Caption:* ...               ← Caption (if present)
    # ![filename](path)            ← Image link
    # *AI Analysis:* ...           ← AI description
    #
    # Why this structure?
    # - Clear visual hierarchy
    # - Caption provides context
    # - AI analysis adds semantic meaning
    # - All searchable text in one place
    # ========================================================================
    content_parts = [f"**{type_label}**"]

    # Add caption if detected
    if caption:
        content_parts.append(f"*Caption:* {caption}")

    # Add image link
    # ../ goes up from pages/ to document root, then into figures/
    content_parts.append(f"![{filename}](../{filepath})")

    # Add AI analysis
    content_parts.append(f"*AI Analysis:* {ai_desc}")

    # Join with newlines
    content = "\n".join(content_parts)

    # ========================================================================
    # WRAP WITH BOUNDARIES
    # ========================================================================
    output = wrap_with_boundaries(
        content, "image", item_id, page,
        filename=filename,
        has_caption="yes" if caption else "no",
        breadcrumbs=" > ".join(breadcrumbs)
    )

    # ========================================================================
    # RETURN WITH UPDATED COUNTER
    # ========================================================================
    # Increment counter → next image on this page gets different filename
    return output, image_counter + 1


def process_table(item: TableItem, doc, page: int, output_dir: Path,
                  image_counter: int, openai_client, breadcrumbs: List[str],
                  next_item=None) -> Tuple[str, int]:
    """
    Process a table using text-first, image-fallback strategy.

    TWO-STAGE EXTRACTION STRATEGY
    =============================

    Our table processing is SMART - we try the best method first,
    then fall back if needed!

    STAGE 1 - TEXT EXPORT (Preferred):
    ----------------------------------
    ✓ Fast (no image rendering)
    ✓ Cheap (text tokens << image tokens)
    ✓ Lossless (exact cell values preserved)
    ✓ Searchable (text can be grepped, indexed)
    ✓ Copy-pasteable (users can copy table data)

    How it works:
    1. Docling's TableFormer extracts table as pandas DataFrame
    2. DataFrame.to_markdown() converts to Markdown table
    3. Send Markdown text to GPT-4o for analysis
    4. Done! Clean, cheap, fast.

    When it works:
    - Simple tables (regular rows/columns)
    - Most financial tables
    - Data tables with clear structure

    STAGE 2 - IMAGE EXPORT (Fallback):
    ----------------------------------
    Used when text export fails or produces garbage

    Why it might fail:
    - Complex merged cells
    - Nested tables
    - Image-based tables (scanned PDFs)
    - Malformed table structure

    How it works:
    1. Render table as PNG image
    2. Send image to GPT-4 Vision
    3. Done! Works for any table.

    Tradeoffs:
    - Slower (image rendering + Vision API)
    - More expensive (image tokens)
    - Lossy (OCR-like, may miss small text)
    - Not searchable by content

    But it works when text fails! Better than nothing.

    CAPTION DETECTION FOR TABLES
    ============================

    Table captions use PATTERN MATCHING (not Docling label)
    because table captions often appear ABOVE the table
    and Docling doesn't always label them correctly.

    Caption Patterns:
    - Starts with: Exhibit, Figure, Table, Chart, Source:
    - Contains: "Source:" anywhere
    - Short with colon: Length <200 and has ':'

    Examples:
    ✓ "Exhibit 3: Quarterly Revenue FY2024"
    ✓ "Table 1: Market Share by Region"
    ✓ "Source: Company filings, analyst estimates"
    ✓ "Revenue breakdown:" (short + colon)
    ✗ "This is a long paragraph without colon markers"

    Args:
        item: Docling TableItem to process
        doc: Parent Docling document
        page: Current page number
        output_dir: Document-level output directory
        image_counter: Current counter for figures on this page
        openai_client: Initialized OpenAI client
        breadcrumbs: Current document path
        next_item: Next item in stream (for caption detection)

    Returns:
        Tuple of (boundary_wrapped_markdown, updated_image_counter)

        Counter only increments if image fallback was used
        (text export doesn't create image files)

    Example Output (Text Export):
    ============================

    <!-- BOUNDARY_START type="table" id="p5_table_1" page="5"
         rows="4" columns="3" has_caption="yes"
         breadcrumbs="Results > Revenue" -->
    *Caption:* Table 1: Quarterly Revenue FY2024
    | Quarter | Revenue | Growth |
    |---------|---------|--------|
    | Q1      | $100M   | -      |
    | Q2      | $110M   | 10%    |
    | Q3      | $125M   | 14%    |
    | Q4      | $140M   | 12%    |

    *AI Analysis:* Table shows quarterly revenue progression with
    consistent growth throughout 2024, from $100M to $140M representing
    40% annual growth.
    <!-- BOUNDARY_END type="table" id="p5_table_1" -->

    Example Output (Image Fallback):
    ===============================

    <!-- BOUNDARY_START type="image" id="p5_image_1" page="5"
         filename="fig_p5_1.png" has_caption="yes"
         breadcrumbs="Results > Revenue" -->
    **Table/Chart**
    *Caption:* Table 1: Complex Merged Cell Revenue Table
    ![fig_p5_1.png](../figures/fig_p5_1.png)
    *AI Analysis:* Complex table with merged cells showing revenue
    breakdown by region and product line. Multiple nested categories
    make text extraction difficult.
    <!-- BOUNDARY_END type="image" id="p5_image_1" -->
    """
    # ========================================================================
    # CAPTION DETECTION FOR TABLES
    # ========================================================================
    # Use pattern matching (not Docling label) for table captions
    # because table captions often appear above tables and aren't
    # always labeled correctly by Docling
    # ========================================================================
    caption = None
    if next_item and isinstance(next_item, TextItem):
        text = next_item.text.strip()

        # Heuristic caption patterns
        is_caption = (
            # Starts with common caption keywords
            text.startswith(('Exhibit', 'Figure', 'Table', 'Chart', 'Source:')) or

            # Contains source attribution
            'Source:' in text or

            # Short line with colon (often a table title)
            (len(text) < 200 and ':' in text)
        )

        if is_caption:
            caption = text

    # ========================================================================
    # STAGE 1: TRY TEXT EXPORT (Preferred Method)
    # ========================================================================
    # Attempt to export table as pandas DataFrame and convert to Markdown
    # This is MUCH preferred over image export when it works!
    # ========================================================================

    text_table_valid = False  # Flag: Did text export succeed?
    df = None                 # pandas DataFrame (if successful)
    md_table = None          # Markdown table string (if successful)

    try:
        # --------------------------------------------------------------------
        # EXPORT TO DATAFRAME
        # --------------------------------------------------------------------
        # Docling's TableFormer ML model extracts table structure
        # Returns pandas DataFrame with rows/columns preserved
        # --------------------------------------------------------------------
        df = item.export_to_dataframe()

        # --------------------------------------------------------------------
        # VALIDATE DATAFRAME
        # --------------------------------------------------------------------
        # Check that DataFrame is usable:
        # - Not empty (has rows)
        # - Has columns
        # - Has enough content to be meaningful
        # --------------------------------------------------------------------
        if not df.empty and len(df) > 0 and len(df.columns) > 0:
            # ----------------------------------------------------------------
            # CONVERT TO MARKDOWN
            # ----------------------------------------------------------------
            # pandas .to_markdown() creates a clean Markdown table
            # index=False means don't include DataFrame row index
            # ----------------------------------------------------------------
            md_table = df.to_markdown(index=False)

            # ----------------------------------------------------------------
            # SANITY CHECK
            # ----------------------------------------------------------------
            # Very short "tables" (<50 chars) are often extraction noise
            # Example: Single-cell tables, header-only tables
            # Better to fall back to image for these
            # ----------------------------------------------------------------
            text_table_valid = len(md_table) > 50

    except Exception:
        # export_to_dataframe() can raise on malformed tables
        # Catch all exceptions and fall back to image
        text_table_valid = False

    # ========================================================================
    # TEXT EXPORT SUCCESS PATH
    # ========================================================================
    if text_table_valid and md_table:
        # ====================================================================
        # GENERATE UNIQUE ID
        # ====================================================================
        item_id = generate_unique_id(page, "table")

        # ====================================================================
        # GET AI DESCRIPTION (Text-based)
        # ====================================================================
        # Send Markdown table as TEXT to GPT-4o
        # This is cheaper than Vision and works well for structured data
        # ====================================================================
        table_desc = describe_table_with_ai(md_table, openai_client, caption)

        # ====================================================================
        # BUILD MARKDOWN CONTENT
        # ====================================================================
        # Structure:
        # *Caption:* ...    ← Caption (if present)
        # | Header | Data | ← Markdown table
        # |--------|------|
        # | Row1   | Data |
        # *AI Analysis:* ... ← AI description
        # ====================================================================
        content_parts = []

        # Add caption if detected
        if caption:
            content_parts.append(f"*Caption:* {caption}")

        # Add the Markdown table
        content_parts.append(md_table)

        # Add AI analysis
        content_parts.append(f"\n*AI Analysis:* {table_desc}")

        # Join with newlines
        content = "\n".join(content_parts)

        # ====================================================================
        # WRAP WITH BOUNDARIES
        # ====================================================================
        # Include table dimensions in metadata
        # rows/columns help with filtering and quality checks
        # ====================================================================
        output = wrap_with_boundaries(
            content, "table", item_id, page,
            rows=len(df),
            columns=len(df.columns),
            has_caption="yes" if caption else "no",
            breadcrumbs=" > ".join(breadcrumbs)
        )

        # ====================================================================
        # RETURN WITHOUT INCREMENTING COUNTER
        # ====================================================================
        # No image file was created, so counter stays the same
        # Next image/table on this page will use the same counter value
        # ====================================================================
        return output, image_counter

    # ========================================================================
    # STAGE 2: IMAGE FALLBACK
    # ========================================================================
    # Text export failed → render table as image and use Vision API
    # ========================================================================

    # is_table=True tells extract_and_save_image():
    # - Label as "Table/Chart" (not "Image")
    # - Affects AI prompt context
    img_result = extract_and_save_image(
        item, doc, page, output_dir, image_counter,
        openai_client, caption=caption, is_table=True
    )

    if img_result:
        # ====================================================================
        # IMAGE EXTRACTION SUCCEEDED
        # ====================================================================
        filename, filepath, ai_desc, type_label = img_result

        # Note: ID type is "image" (not "table") because we saved a PNG
        item_id = generate_unique_id(page, "image")

        # ====================================================================
        # BUILD MARKDOWN CONTENT
        # ====================================================================
        # Same structure as process_image()
        # ====================================================================
        content_parts = [f"**{type_label}**"]  # "Table/Chart"

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

        # ====================================================================
        # RETURN WITH INCREMENTED COUNTER
        # ====================================================================
        # Image file was created, so increment counter
        # Next image/table gets a different filename
        # ====================================================================
        return output, image_counter + 1

    # ========================================================================
    # BOTH STAGES FAILED
    # ========================================================================
    # Text export failed AND image extraction failed
    # This is rare but can happen with:
    # - Corrupted table elements in PDF
    # - Encrypted/DRM-protected content
    # - Disk space issues
    #
    # Return empty string, leave counter unchanged
    # Document processing continues without this table
    # ========================================================================
    return "", image_counter


# =============================================================================
# MAIN PROCESSING
# =============================================================================
#
# This section contains the core pipeline logic that ties everything together.
#
# process_pdf() is the MAIN FUNCTION - it orchestrates all the processors!
#
# =============================================================================

def process_pdf(pdf_path: Path, output_base_dir: Path, openai_client) -> Dict:
    """
    End-to-end processor for a single PDF file.

    This is the HEART of the extraction pipeline!
    It coordinates all the other functions to transform a PDF
    into structured, boundary-marked Markdown files.

    PROCESSING PIPELINE (4 Main Steps):
    ===================================

    Step 1: DOCLING CONVERSION
    -------------------------
    - Convert PDF using Docling DocumentConverter
    - Docling analyzes layout, detects elements
    - Returns Document object with all items

    Step 2: PAGE GROUPING
    --------------------
    - Iterate through all document items
    - Group items by page number (using provenance data)
    - Creates {page_num: [items]} dictionary

    Step 3: PAGE PROCESSING
    ----------------------
    - For each page:
      * Process items sequentially
      * Dispatch to appropriate processor (header, text, image, etc.)
      * Handle caption detection and skipping
      * Join all outputs with blank lines
      * Write page_{num}.md file

    Step 4: METADATA GENERATION
    --------------------------
    - Create metadata.json index file
    - Records: pages processed, images/tables counts, timestamp
    - This acts as a manifest for the extracted document

    OUTPUT STRUCTURE:
    ================

    {output_base_dir}/{pdf_stem}/
    ├── pages/
    │   ├── page_1.md     ← Boundary-marked Markdown
    │   ├── page_2.md
    │   └── ...
    ├── figures/
    │   ├── fig_p1_1.png  ← Extracted images
    │   ├── fig_p2_1.png
    │   └── ...
    └── metadata.json     ← Index and statistics

    Args:
        pdf_path: Absolute path to the PDF file
            Example: /home/user/pdfs/clinical_trial.pdf

        output_base_dir: Root output directory
            Example: ./extracted_docs_bounded
            We'll create: ./extracted_docs_bounded/clinical_trial/

        openai_client: Initialized OpenAI client for AI descriptions

    Returns:
        metadata dict (also written to metadata.json)
        {
          "file": "clinical_trial.pdf",
          "processed": "2024-02-22T14:30:25.123456",
          "tool": "Docling Simple Bounded",
          "pages": [...],
          "total_images": 15,
          "total_tables": 8
        }

    Error Handling:
    ==============

    This function does NOT catch exceptions!
    Why? Let errors propagate to process_batch() so:
    - Failed PDFs are logged
    - Batch processing continues
    - Users see exactly what failed

    If we caught exceptions here, failures would be silent!
    """
    # ========================================================================
    # STARTUP LOGGING
    # ========================================================================
    # Print clear visual separator and PDF name
    # Makes it easy to find in logs when processing batches
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"Processing: {pdf_path.name}")
    print(f"{'='*70}")

    # ========================================================================
    # RESET ID COUNTERS
    # ========================================================================
    # CRITICAL: Reset counters so this document's IDs start fresh
    # Without this, IDs would continue from previous PDF in batch!
    #
    # Example problem without reset:
    # Doc 1: p1_text_1, p1_text_2, p1_text_3
    # Doc 2: p1_text_4, p1_text_5  ← BAD! Should start at 1
    # ========================================================================
    reset_id_counters()

    # ========================================================================
    # CREATE OUTPUT DIRECTORIES
    # ========================================================================
    # Create folder structure for this document:
    # {output_base_dir}/{pdf_stem}/pages/
    # {output_base_dir}/{pdf_stem}/figures/
    #
    # Example:
    # pdf_path = "clinical_trial.pdf"
    # pdf_path.stem = "clinical_trial" (filename without extension)
    # doc_output_dir = "./extracted_docs_bounded/clinical_trial/"
    # ========================================================================
    doc_output_dir = output_base_dir / pdf_path.stem
    (doc_output_dir / "pages").mkdir(parents=True, exist_ok=True)
    (doc_output_dir / "figures").mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # STEP 1: DOCLING PDF CONVERSION
    # ========================================================================
    print("   [1/4] Analyzing PDF layout...")

    # Create configured DocumentConverter instance
    converter = create_docling_converter()

    # Convert the PDF!
    # This is where Docling does its magic:
    # - Parses PDF layout
    # - Detects text blocks, tables, images
    # - Runs TableFormer ML model
    # - Renders images at our requested scale
    conv_result = converter.convert(pdf_path)

    # Extract the Document object
    doc = conv_result.document

    print("      SUCCESS: Layout analysis complete")

    # ========================================================================
    # STEP 2: GROUP ITEMS BY PAGE
    # ========================================================================
    # doc.iterate_items() yields (item, level) tuples in document order
    #
    # item: Docling item (TextItem, TableItem, etc.)
    # level: Heading depth (for SectionHeaderItem)
    #
    # We group these by page number for sequential processing
    # ========================================================================
    print("   [2/4] Collecting document items...")

    # Dictionary: {page_num: [{"item": item, "level": level}, ...]}
    pages_items = defaultdict(list)

    for item, level in doc.iterate_items():
        # ====================================================================
        # CHECK PROVENANCE (LOCATION DATA)
        # ====================================================================
        # item.prov contains location information:
        # - Which page the item is on
        # - Where on the page (bbox coordinates)
        #
        # Items without prov can't be placed in output → skip them
        # These are usually document-level metadata items
        # ====================================================================
        if not item.prov:
            continue  # Skip items with no page location

        # Extract page number (1-based)
        page_num = item.prov[0].page_no

        # Add to page's item list
        pages_items[page_num].append({"item": item, "level": level})

    # Count total items across all pages
    total_items = sum(len(items) for items in pages_items.values())

    print(f"      SUCCESS: Collected {total_items} items "
          f"across {len(pages_items)} pages")

    # ========================================================================
    # STEP 3: PROCESS EACH PAGE
    # ========================================================================
    print("   [3/4] Processing items with boundaries...")

    # Tracking variables
    metadata_pages = []       # Per-page summaries for metadata.json
    global_breadcrumbs = []   # Persists across pages (section context)
    total_images = 0          # Global image counter
    total_tables = 0          # Global table counter

    # Process pages in order (sorted by page number)
    for page_num in sorted(pages_items.keys()):
        items = pages_items[page_num]

        # Per-page tracking
        page_outputs = []        # Markdown strings for this page
        page_image_count = 0     # Images on this page
        page_table_count = 0     # Tables on this page
        image_counter = 1        # Filename counter (resets per page)
        skip_indices = set()     # Items consumed as captions

        # ====================================================================
        # PAGE HEADER
        # ====================================================================
        # Start page with section context (if we have breadcrumbs)
        # This helps readers know where they are in the document
        # even without seeing previous pages
        #
        # Example:
        # <!-- Context: Financial Results > Revenue > Q4 Performance -->
        # ====================================================================
        if global_breadcrumbs:
            page_outputs.append(f"<!-- Context: {' > '.join(global_breadcrumbs)} -->")

        # Add page title
        page_outputs.append(f"\n# Page {page_num}\n")

        # ====================================================================
        # PROCESS ITEMS ON THIS PAGE
        # ====================================================================
        for idx, entry in enumerate(items):
            # ================================================================
            # SKIP CAPTION ITEMS
            # ================================================================
            # If this item was marked for skipping (consumed as caption),
            # don't process it again
            # ================================================================
            if idx in skip_indices:
                continue

            # Extract item and level
            item = entry["item"]
            level = entry["level"]

            # Look ahead one item (for caption detection)
            next_item = items[idx + 1]["item"] if idx + 1 < len(items) else None

            # ================================================================
            # DISPATCH TO APPROPRIATE PROCESSOR
            # ================================================================
            # Type-based routing - send each item to its specialized processor
            # ================================================================

            # SECTION HEADERS
            if isinstance(item, SectionHeaderItem):
                output, global_breadcrumbs = process_header(
                    item, page_num, level, global_breadcrumbs
                )
                page_outputs.append(output)

            # TEXT ITEMS (try special handling first)
            elif isinstance(item, TextItem):
                # Try code block detection first
                special_output = process_special_text(item, page_num, global_breadcrumbs)

                if special_output:
                    # Was detected as code
                    page_outputs.append(special_output)
                else:
                    # Regular text paragraph
                    output = process_text(item, page_num, global_breadcrumbs)
                    if output:  # Empty string means "skip" (too short)
                        page_outputs.append(output)

            # LIST ITEMS
            elif isinstance(item, ListItem):
                output = process_list(item, page_num, global_breadcrumbs)
                page_outputs.append(output)

            # IMAGES/FIGURES
            elif isinstance(item, PictureItem):
                output, image_counter = process_image(
                    item, doc, page_num, doc_output_dir,
                    image_counter, openai_client, global_breadcrumbs, next_item
                )

                if output:
                    page_outputs.append(output)
                    page_image_count += 1

                    # Mark next item for skipping if it was used as caption
                    if next_item and isinstance(next_item, TextItem):
                        # Check caption patterns
                        text = next_item.text.strip()
                        if (text.startswith(('Exhibit', 'Figure', 'Table', 'Chart', 'Fig', 'Source:')) or
                            'Source:' in text or (len(text) < 200 and ':' in text)):
                            skip_indices.add(idx + 1)

            # TABLES
            elif isinstance(item, TableItem):
                output, image_counter = process_table(
                    item, doc, page_num, doc_output_dir,
                    image_counter, openai_client, global_breadcrumbs, next_item
                )

                if output:
                    page_outputs.append(output)
                    page_table_count += 1

                    # Mark next item for skipping if it was used as caption
                    if next_item and isinstance(next_item, TextItem):
                        text = next_item.text.strip()
                        if (text.startswith(('Exhibit', 'Figure', 'Table', 'Chart', 'Source:')) or
                            'Source:' in text or (len(text) < 200 and ':' in text)):
                            skip_indices.add(idx + 1)

        # ====================================================================
        # WRITE PAGE FILE
        # ====================================================================
        # Join all output blocks with double newlines (Markdown convention)
        # Write to page_{num}.md file
        # ====================================================================
        page_text = "\n\n".join(page_outputs)
        page_filename = f"page_{page_num}.md"

        with open(doc_output_dir / "pages" / page_filename, "w", encoding="utf-8") as f:
            f.write(page_text)

        # ====================================================================
        # RECORD PAGE METADATA
        # ====================================================================
        # Store summary for this page in metadata.json
        # Includes: page number, filename, breadcrumbs, counts
        # ====================================================================
        metadata_pages.append({
            "page": page_num,
            "file": page_filename,
            "breadcrumbs": list(global_breadcrumbs),  # Snapshot at end of page
            "images": page_image_count,
            "tables": page_table_count
        })

        # Update global counters
        total_images += page_image_count
        total_tables += page_table_count

    # Summary of page processing
    print(f"      SUCCESS: Processed {len(pages_items)} pages")
    print(f"         Images: {total_images}")
    print(f"         Tables: {total_tables}")

    # ========================================================================
    # STEP 4: SAVE METADATA INDEX
    # ========================================================================
    # Create metadata.json - acts as manifest for this document
    #
    # Why metadata.json?
    # - Index of all pages (for iteration)
    # - Processing timestamp (for cache invalidation)
    # - Element counts (for quality checks)
    # - Tool version (for reproducibility)
    # ========================================================================
    print("   [4/4] Saving metadata...")

    metadata = {
        "file": pdf_path.name,                # Original PDF filename
        "processed": datetime.now().isoformat(),  # When we processed it
        "tool": "Docling Simple Bounded",    # Which extractor version
        "pages": metadata_pages,              # Per-page summaries
        "total_images": total_images,         # Global counts
        "total_tables": total_tables
    }

    with open(doc_output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"      SUCCESS: Metadata saved")

    # ========================================================================
    # COMPLETION SUMMARY
    # ========================================================================
    # Print final summary with key statistics
    # Makes it easy to verify extraction at a glance
    # ========================================================================
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

    BATCH PROCESSING BEHAVIOR
    =========================

    Single File Mode:
    - input_path is a .pdf file → process that file

    Directory Mode:
    - input_path is a directory → glob all *.pdf files
    - Process each PDF sequentially (not parallel)
    - Failed PDFs don't abort the batch (isolated failures)

    Why Not Parallel?
    ================

    We could process multiple PDFs in parallel for speed,
    but we don't because:
    - OpenAI rate limits (parallel requests hit limits faster)
    - Memory usage (Docling uses ~1-2GB per PDF)
    - Simpler error handling (failures are isolated)
    - Good enough (30-60s per PDF, most batches are small)

    If you need parallel processing:
    - Use Python multiprocessing
    - Add queue for OpenAI rate limiting
    - Monitor memory usage carefully

    Error Handling Strategy:
    =======================

    Each PDF is wrapped in try/except:
    - Success: Add to successful list
    - Failure: Log error, add to failed list, CONTINUE

    Why continue on failure?
    If you have 100 PDFs and #37 is corrupted:
    ✓ Process 99 successfully
    ✓ Report 1 failure
    ✗ Don't abort entire batch!

    This "isolated failure" pattern is critical for batch jobs!

    Args:
        input_path: Path to:
            - Single .pdf file, OR
            - Directory containing .pdf files

        output_base_dir: Root directory for all output
            Each PDF gets its own subdirectory

    Returns:
        None (prints summary table at end)

    Example Execution:
    ==================

    $ python script.py ./clinical_trials/

    ======================================================================
    BATCH PROCESSING: 20 PDF(s)
    ======================================================================

    [1/20] trial_001.pdf
    Processing: trial_001.pdf
    ...
    EXTRACTION COMPLETE

    [2/20] trial_002.pdf
    Processing: trial_002.pdf
    ...
    ERROR - FAILED: Corrupt PDF

    [3/20] trial_003.pdf
    ...

    ======================================================================
    BATCH SUMMARY
    ======================================================================
    Successful: 19/20
    Failed: 1/20

    Successfully processed:
       [OK] trial_001.pdf
       [OK] trial_003.pdf
       ...

    Failed to process:
       [FAIL] trial_002.pdf
    ======================================================================
    """
    # ========================================================================
    # VALIDATE INPUT PATH
    # ========================================================================
    if not input_path.exists():
        print(f"\nERROR: Path not found: {input_path}")
        return

    # ========================================================================
    # DETERMINE PROCESSING MODE
    # ========================================================================
    if input_path.is_file():
        # SINGLE FILE MODE
        # Check that it's actually a PDF
        if input_path.suffix.lower() != '.pdf':
            print(f"\nERROR: Not a PDF file: {input_path}")
            return
        pdf_files = [input_path]
    else:
        # DIRECTORY MODE
        # Glob all PDFs (non-recursive - subdirectories ignored)
        pdf_files = list(input_path.glob("*.pdf"))

        if not pdf_files:
            print(f"\nERROR: No PDF files found in: {input_path}")
            return

    # ========================================================================
    # INITIALIZE OPENAI CLIENT
    # ========================================================================
    # Create client once and reuse across all PDFs
    # This is more efficient than creating new client per PDF
    #
    # Will raise exception if OPENAI_API_KEY not set
    # Better to fail here than after processing starts!
    # ========================================================================
    try:
        openai_client = OpenAI()
    except Exception as e:
        print(f"\nERROR: OpenAI client initialization failed: {str(e)}")
        print("NOTE: Set OPENAI_API_KEY environment variable")
        print("      export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    # ========================================================================
    # BATCH PROCESSING HEADER
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"BATCH PROCESSING: {len(pdf_files)} PDF(s)")
    print(f"{'='*70}")

    # Tracking lists
    successful = []  # Successfully processed PDFs
    failed = []      # Failed PDFs

    # ========================================================================
    # PROCESS EACH PDF
    # ========================================================================
    for idx, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{idx}/{len(pdf_files)}] {pdf_path.name}")

        try:
            # ================================================================
            # PROCESS PDF
            # ================================================================
            # This is where the magic happens!
            # If successful, metadata is returned (we don't use it here)
            # ================================================================
            process_pdf(pdf_path, output_base_dir, openai_client)

            # Success! Add to successful list
            successful.append(pdf_path.name)

        except Exception as e:
            # ================================================================
            # HANDLE PER-PDF ERRORS
            # ================================================================
            # Don't let one bad PDF abort the entire batch!
            # Log the error and continue to next PDF
            # ================================================================
            print(f"\nERROR - FAILED: {str(e)}")
            failed.append(pdf_path.name)

    # ========================================================================
    # BATCH SUMMARY
    # ========================================================================
    # Print summary table showing success/failure breakdown
    # Useful for monitoring and alerting in production
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"BATCH SUMMARY")
    print(f"{'='*70}")
    print(f"Successful: {len(successful)}/{len(pdf_files)}")
    print(f"Failed: {len(failed)}/{len(pdf_files)}")

    # List successful files
    if successful:
        print("\nSuccessfully processed:")
        for name in successful:
            print(f"   [OK] {name}")

    # List failed files
    if failed:
        print("\nFailed to process:")
        for name in failed:
            print(f"   [FAIL] {name}")

    print(f"{'='*70}\n")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================
#
# This is where Python execution begins when you run:
# $ python docling_bounded_extractor.py <args>
#
# =============================================================================

def main():
    """
    Parse CLI arguments and kick off batch processing.

    This function wraps the entire pipeline in error handling so:
    - KeyboardInterrupt (Ctrl+C) exits cleanly
    - Unexpected exceptions print nice error messages
    - Exit codes signal success/failure to calling scripts

    Command Line Interface:
    ======================

    python script.py PATH [--output DIR]

    Arguments:
    - PATH: Single PDF file OR directory of PDFs (required)
    - --output: Output directory (optional, default: ./extracted_docs_bounded)

    Examples:
    --------

    # Process single PDF
    python script.py clinical_trial.pdf

    # Process directory
    python script.py ./clinical_trials/

    # Custom output directory
    python script.py ./pdfs/ --output ./my_output

    Exit Codes:
    ----------
    0 = Success
    1 = Error (file not found, API failure, keyboard interrupt, etc.)

    Why exit codes matter?
    CI/CD pipelines check exit codes to know if job succeeded!
    Example: GitHub Actions fails the workflow if exit code != 0
    """
    # ========================================================================
    # ARGUMENT PARSING
    # ========================================================================
    # argparse provides nice CLI with --help, error messages, etc.
    # ========================================================================
    parser = argparse.ArgumentParser(
        description="Docling PDF Extractor with Boundary Markers",
        epilog="Example: python script.py ./pdfs/ --output ./output"
    )

    # Positional argument: path (required)
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a single PDF file, or a directory containing PDFs"
    )

    # Optional argument: output directory
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(OUTPUT_DIR),
        help=f"Root output directory (default: {OUTPUT_DIR})"
    )

    args = parser.parse_args()

    # ========================================================================
    # EXECUTION WITH ERROR HANDLING
    # ========================================================================
    try:
        # Run the batch processor!
        process_batch(args.path, args.output)

    except KeyboardInterrupt:
        # User pressed Ctrl+C
        # Exit gracefully without scary traceback
        print("\n\nWARNING: Interrupted by user (Ctrl+C)")
        sys.exit(1)

    except Exception as e:
        # Unexpected fatal error
        # Print clean error message and exit with error code
        print(f"\n\nERROR: Fatal error: {str(e)}")
        print("\nPlease check:")
        print("  1. PDF file is not corrupted")
        print("  2. OPENAI_API_KEY is set correctly")
        print("  3. Sufficient disk space available")
        print("  4. Network connection is stable")
        sys.exit(1)


# =============================================================================
# SCRIPT EXECUTION
# =============================================================================
#
# The if __name__ == "__main__" pattern ensures main() only runs when
# this file is executed directly, NOT when imported as a module.
#
# Why?
# - Allows other scripts to import functions from this file
# - Clean separation between library code and CLI code
# - Standard Python practice
#
# =============================================================================

if __name__ == "__main__":
    main()


# =============================================================================
# SUMMARY FOR STUDENTS
# =============================================================================
#
# This script demonstrates several advanced programming concepts:
#
# 1. FUNCTIONAL PROGRAMMING
#    - Pure functions (processors have no side effects)
#    - Function composition (small functions combined for complex behavior)
#    - Immutable data (Pass data through pipeline, don't mutate)
#
# 2. STRUCTURED DATA
#    - Boundary markers (machine-readable metadata in Markdown)
#    - JSON output (metadata.json for downstream consumers)
#    - Hierarchical organization (breadcrumbs for context)
#
# 3. AI INTEGRATION
#    - Vision API (image analysis with GPT-4)
#    - Text API (table analysis with GPT-4)
#    - Fallback strategies (text-first, image-second for tables)
#
# 4. ERROR HANDLING
#    - Per-file isolation (one failure doesn't break batch)
#    - Graceful degradation (missing captions, failed AI → continue)
#    - Clear error messages (actionable guidance for users)
#
# 5. BATCH PROCESSING
#    - Sequential processing (simple, reliable)
#    - Progress tracking (numbered file output)
#    - Summary reporting (success/failure table)
#
# Key Takeaways:
# ✓ Build small, focused functions (single responsibility)
# ✓ Handle errors gracefully (don't crash on bad input)
# ✓ Make output machine-readable (JSON, structured tags)
# ✓ Provide clear logging (users need to know what's happening)
# ✓ Test edge cases (empty files, corrupt PDFs, API failures)
#
# Questions for Students:
#
# 1. Why use boundary markers instead of just saving clean Markdown?
#    → Enables precise chunk extraction without re-parsing
#
# 2. Why try text export before image export for tables?
#    → Faster, cheaper, lossless (text is always preferred when it works)
#
# 3. Why not process PDFs in parallel for speed?
#    → OpenAI rate limits, memory usage, simpler error handling
#
# 4. Why track breadcrumbs across pages?
#    → Provides semantic context (which section are we in?)
#
# 5. How would you modify this for scanned PDFs?
#    → Set do_ocr=True in pipeline options (enables OCR)
#
# =============================================================================