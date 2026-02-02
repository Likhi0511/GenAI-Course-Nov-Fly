"""
================================================================================
MODULE: Docling Hybrid Snap V2 - Advanced PDF Extraction with Visual Snapping
================================================================================

PURPOSE:
--------
This module provides intelligent PDF document extraction combining:
1. Standard visual extraction (images, tables, charts)
2. Smart "visual snapping" - captures text regions as images when triggered
3. AI-powered visual analysis using GPT-4 Vision
4. Coordinate transformation between PDF and image coordinate systems

PROBLEM IT SOLVES:
------------------
Standard PDF extractors miss visual context when:
- "Exhibit" headers are followed by text lists (not embedded images)
- Complex layouts mix text and visual elements
- Captions appear AFTER visuals (reading order issue)

SOLUTION:
---------
Hybrid approach:
- Detects trigger patterns (e.g., "Exhibit 1:")
- If NOT followed by an actual image, CROPS the text region as a snapshot
- Reorders captions to appear BEFORE their visuals
- Sends all visuals to GPT-4 Vision for intelligent descriptions

KEY INNOVATIONS:
----------------
✓ PDF → PIL coordinate transformation (Bottom-Left → Top-Left origin)
✓ Bounding box aggregation for multi-item text regions
✓ Smart caption reordering (Visual, Caption) → (Caption, Visual)
✓ Dual visual extraction: PictureItem + TableItem (catches misclassified charts)
✓ Context preservation via breadcrumb navigation

FIXES IN V2:
------------
✓ CRASH FIX: Properly accesses `.pil_image` from ImageRef wrapper
✓ CROP MATH: Converts PDF coordinates (Bottom-Left) to Image coordinates (Top-Left)
✓ WARNINGS: Updated table export to use compliant syntax
✓ SNAP LOGIC: Captures "Exhibit" headers followed by text lists as visual snapshots

WORKFLOW:
---------
1. PDF Analysis    → Docling parses layout, identifies elements
2. Item Collection → Group by page, preserve hierarchy
3. Smart Reorder   → Move captions before visuals
4. Hybrid Extract  → Standard visuals + Smart snapping
5. AI Analysis     → GPT-4 Vision describes each visual
6. Markdown Output → Pages with embedded visuals + metadata

USAGE:
------
    python extract_docling_hybrid_snap_v2.py /path/to/pdf_or_folder

DEPENDENCIES:
-------------
- docling: PDF parsing and layout analysis
- openai: GPT-4 Vision API for image descriptions
- pandas: Table data manipulation
- PIL (Pillow): Image processing and cropping

AUTHOR: Prudhvi (Thoughtworks)
COURSE: Applied GenAI - Document Intelligence Module
DATE: 2026-01-29
================================================================================
"""

import os
import sys
import json
import base64
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# ----------------------------------------------------------------
# IMPORT DEPENDENCIES WITH ERROR HANDLING
# ----------------------------------------------------------------
try:
    # Docling Core Components
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat

    # Docling Document Items (parsed elements from PDF)
    from docling.datamodel.document import (
        TableItem,          # Tabular data structures (rows/columns)
        PictureItem,        # Images, charts, diagrams
        TextItem,           # Regular text paragraphs
        SectionHeaderItem   # Section headers for hierarchy
    )

    # OpenAI for AI-powered visual analysis
    from openai import OpenAI

    # Pandas for table data manipulation
    import pandas as pd

except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Install: pip install docling openai pandas pillow")
    sys.exit(1)


# ================================================================
# CLASS: DoclingHybridSnapV2
# ================================================================
class DoclingHybridSnapV2:
    """
    Advanced PDF Extraction Engine with Hybrid Visual Processing
    =============================================================

    OVERVIEW:
    ---------
    Combines traditional visual extraction (embedded images/tables) with
    intelligent "visual snapping" that converts text regions into images
    when triggered by specific patterns (e.g., "Exhibit 1:").

    CORE CAPABILITIES:
    ------------------
    1. **Standard Visual Extraction**:
       - PictureItem: Charts, graphs, diagrams, photos
       - TableItem: Data tables (can also be charts misclassified as tables)

    2. **Smart Visual Snapping**:
       - Detects trigger patterns: "Exhibit X:", "Figure Y:", etc.
       - If header NOT followed by actual image, crops text region as snapshot
       - Aggregates bounding boxes across multiple text items
       - Transforms PDF coordinates to PIL image coordinates

    3. **AI-Powered Analysis**:
       - Sends every visual to GPT-4 Vision API
       - Generates intelligent descriptions (layout, data, trends, insights)

    4. **Caption Reordering**:
       - Detects [Visual, Caption] patterns
       - Reorders to [Caption, Visual] for better readability

    5. **Context Preservation**:
       - Maintains breadcrumb navigation (Section → Subsection hierarchy)
       - Tracks page numbers, image counts, table counts
       - Generates comprehensive metadata.json

    COORDINATE SYSTEMS:
    -------------------
    PDF Coordinates (Docling BBox):
        Origin: Bottom-Left corner
        X-axis: Left → Right (increases rightward)
        Y-axis: Bottom → Top (increases upward)
        bbox = {l: left, b: bottom, r: right, t: top}

    PIL Image Coordinates:
        Origin: Top-Left corner
        X-axis: Left → Right (increases rightward)
        Y-axis: Top → Bottom (increases downward)
        crop_box = (left, top, right, bottom)

    TRANSFORMATION FORMULA:
        pil_x = pdf_x * scale
        pil_y = (page_height - pdf_y) * scale

    OUTPUT STRUCTURE:
    -----------------
    extracted_docs_hybrid_v2/
    └── document_name/
        ├── pages/
        │   ├── page_1.md      # Markdown with embedded visuals
        │   ├── page_2.md
        │   └── ...
        ├── figures/
        │   ├── fig_p1_1.png   # Standard extracted images
        │   ├── snap_p2_1.png  # Smart-snapped text regions
        │   └── ...
        └── metadata.json      # Processing metadata

    ATTRIBUTES:
    -----------
    output_dir : Path
        Base directory for all extracted documents
    model : str
        OpenAI model for visual analysis (default: "gpt-4o")
    openai : OpenAI
        OpenAI client for API calls
    scale : float
        Image resolution multiplier (3.0 = 216 DPI)
    pipeline_options : PdfPipelineOptions
        Docling processing configuration
    converter : DocumentConverter
        Main Docling converter instance
    visual_trigger : re.Pattern
        Regex to detect visual trigger patterns
    vision_prompt : str
        Prompt template for GPT-4 Vision analysis

    METHODS:
    --------
    extract(input_path)
        Main entry point - processes PDF file or folder

    _process_pdf(pdf_path)
        Processes a single PDF through the full pipeline

    _snap_region(items, start_idx, page_image, page_h, ...)
        Creates visual snapshot by cropping aggregated text region

    _smart_reorder(items)
        Reorders [Visual, Caption] → [Caption, Visual]

    _handle_standard_visual(item, doc, p_no, ...)
        Extracts and analyzes PictureItem or TableItem

    _describe_image(path)
        Sends image to GPT-4 Vision and returns description

    _save_meta(out, pdf, pages)
        Saves processing metadata to JSON
    """

    def __init__(
        self,
        output_base_dir: str = "extracted_docs_hybrid_v2",
        model: str = "gpt-4o"
    ):
        """
        Initialize the Hybrid PDF Extraction Engine
        ============================================

        PARAMETERS:
        -----------
        output_base_dir : str, optional
            Root directory for storing extracted documents
            Default: "extracted_docs_hybrid_v2"
            Structure: output_base_dir/document_name/pages|figures/

        model : str, optional
            OpenAI model for visual analysis
            Default: "gpt-4o" (GPT-4 with vision capabilities)
            Alternatives: "gpt-4-vision-preview", "gpt-4o-mini"

        INITIALIZATION STEPS:
        ---------------------
        1. Set up output directory structure
        2. Configure OpenAI client
        3. Configure Docling pipeline options
        4. Initialize DocumentConverter
        5. Compile regex patterns for smart detection

        PIPELINE CONFIGURATION DETAILS:
        -------------------------------
        images_scale: 3.0
            - Resolution multiplier for extracted images
            - Base PDF resolution: 72 DPI
            - Scaled resolution: 72 * 3.0 = 216 DPI
            - Ensures publication-quality image clarity

        generate_page_images: True
            - CRITICAL for visual snapping functionality
            - Renders full page as PIL Image for manual cropping
            - Without this, _snap_region() cannot create snapshots

        generate_picture_images: True
            - Extracts embedded images from PictureItem elements
            - Saves as separate high-res PNG files

        generate_table_images: True
            - Extracts table visuals from TableItem elements
            - IMPORTANT: Catches charts misclassified as tables
            - Dual extraction: structured data + visual representation

        do_ocr: False
            - Disables Optical Character Recognition
            - Assumes PDFs have embedded text (not scanned images)
            - Speeds up processing significantly
            - Enable only for scanned documents

        do_table_structure: True
            - Parses table structure (rows, columns, cells)
            - Enables export to pandas DataFrame and Markdown
            - Uses TableFormer ML model

        table_structure_options.mode: ACCURATE
            - High-quality table parsing (slower)
            - Alternative: FAST (lower quality, faster processing)
            - Recommended for financial/scientific documents

        REGEX PATTERN EXPLANATION:
        --------------------------
        visual_trigger = r'^(Exhibit|Figure|Fig\.|Chart|Source)[:\s]+\d+'

        ^                  : Start of line (anchor)
        (Exhibit|Figure|...: Match any of these keywords
        [:\s]+            : Followed by colon or whitespace (one or more)
        \d+               : Followed by digit(s) (e.g., "1", "23")
        re.IGNORECASE     : Case-insensitive matching

        MATCHES:
        - "Exhibit 1:"
        - "Figure 23 -"
        - "Fig. 5:"
        - "Chart 12:"
        - "SOURCE 3"

        DOES NOT MATCH:
        - "exhibit" (no number)
        - "The figure shows..." (not at start)
        - "Table 1:" (different keyword - could be added)

        VISION PROMPT STRATEGY:
        -----------------------
        Prompt: "Analyze this visual. Describe layout, data, arrows,
                 or relationships shown."

        Design principles:
        - Open-ended → Allows GPT-4 to describe varied content types
        - Specific keywords → Guides focus (layout, data, relationships)
        - Concise → Keeps descriptions brief (max_tokens=200)
        - Generic → Works for charts, diagrams, flowcharts, tables
        """

        # ----------------------------------------------------------------
        # OUTPUT DIRECTORY SETUP
        # ----------------------------------------------------------------
        self.output_dir = Path(output_base_dir)
        # Path object provides cross-platform path handling (Windows/Linux/Mac)

        # ----------------------------------------------------------------
        # AI MODEL CONFIGURATION
        # ----------------------------------------------------------------
        self.model = model
        # Store model name for later use in _describe_image()

        self.openai = OpenAI()
        # Initializes OpenAI client
        # Requires OPENAI_API_KEY environment variable to be set
        # Example: export OPENAI_API_KEY="sk-..."

        # ----------------------------------------------------------------
        # IMAGE RESOLUTION CONFIGURATION
        # ----------------------------------------------------------------
        self.scale = 3.0
        # Resolution multiplier for image extraction
        # Standard PDF resolution: 72 DPI (dots per inch)
        # Scaled resolution: 72 * 3.0 = 216 DPI
        # Higher values = better quality but larger file sizes
        # Recommended range: 2.0 (144 DPI) to 4.0 (288 DPI)

        # ----------------------------------------------------------------
        # DOCLING PIPELINE OPTIONS
        # ----------------------------------------------------------------
        self.pipeline_options = PdfPipelineOptions()
        # Container for all Docling processing settings

        # IMAGE EXTRACTION SETTINGS
        # -------------------------
        self.pipeline_options.images_scale = self.scale
        # Apply our resolution multiplier to all extracted images

        self.pipeline_options.generate_page_images = True
        # CRITICAL FLAG FOR VISUAL SNAPPING
        # Renders each PDF page as a PIL Image object
        # Stored in: doc.pages[page_no].image
        # Required for: Manual cropping in _snap_region()
        # Memory impact: ~5-10 MB per page at 216 DPI

        self.pipeline_options.generate_picture_images = True
        # Extract embedded images (PictureItem) as separate files
        # Includes: Charts, graphs, photos, diagrams

        self.pipeline_options.generate_table_images = True
        # Extract table visuals (TableItem) as separate files
        # DUAL PURPOSE:
        #   1. Captures actual data tables
        #   2. Catches charts/graphs misclassified as tables by ML model
        # This is a critical fix for robust visual extraction

        # OCR SETTINGS
        # ------------
        self.pipeline_options.do_ocr = False
        # Disable Optical Character Recognition
        # WHEN TO ENABLE:
        #   - Scanned documents (no embedded text)
        #   - Photos of documents
        #   - Handwritten content
        # WHEN TO DISABLE:
        #   - Modern PDFs with selectable text (most common)
        #   - Speed optimization (OCR is slow)
        # Current setting: Assumes embedded text exists

        # TABLE STRUCTURE SETTINGS
        # ------------------------
        self.pipeline_options.do_table_structure = True
        # Enable table structure parsing
        # Uses ML model: microsoft/table-transformer-structure-recognition
        # Outputs:
        #   - Row/column/cell boundaries
        #   - Merged cell detection
        #   - Header identification
        #   - Export to DataFrame/Markdown

        self.pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
        # Table parsing quality mode
        # OPTIONS:
        #   - TableFormerMode.ACCURATE: Slower, higher quality
        #   - TableFormerMode.FAST: Faster, lower quality
        # ACCURATE mode recommended for:
        #   - Financial reports (precision matters)
        #   - Scientific papers (complex tables)
        #   - Legal documents (accuracy critical)

        # ----------------------------------------------------------------
        # DOCUMENT CONVERTER INITIALIZATION
        # ----------------------------------------------------------------
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options)
            }
        )
        # DocumentConverter: Main Docling processing engine
        # format_options: Maps input formats to their processing options
        # InputFormat.PDF: Specifies we're processing PDF files
        # PdfFormatOption: Wraps our pipeline_options configuration
        #
        # WHAT HAPPENS INSIDE:
        # 1. Loads ML models (first run downloads from Hugging Face)
        #    - Layout detection: ds4sd/docling-layout-v1
        #    - Table parsing: microsoft/table-transformer-structure-recognition
        # 2. Initializes processing pipeline
        # 3. Allocates GPU/CPU resources
        # 4. Caches models for subsequent runs

        # ----------------------------------------------------------------
        # SMART DETECTION PATTERNS
        # ----------------------------------------------------------------
        self.visual_trigger = re.compile(
            r'^(Exhibit|Figure|Fig\.|Chart|Source)[:\s]+\d+',
            re.IGNORECASE
        )
        # Compiled regex for performance (compiled once, used many times)
        # PURPOSE: Detects headers that should trigger visual snapping
        #
        # PATTERN BREAKDOWN:
        # ^                     : Must be at start of text
        # (Exhibit|Figure|...)  : One of these keywords
        # [:\s]+               : Colon or space(s) after keyword
        # \d+                  : One or more digits
        # re.IGNORECASE        : Match "Exhibit", "exhibit", "EXHIBIT"
        #
        # MATCHING EXAMPLES:
        # ✓ "Exhibit 1: Market Analysis"
        # ✓ "Figure 23: Revenue Trends"
        # ✓ "Fig. 5 - Data Distribution"
        # ✓ "Chart 12: Growth Metrics"
        # ✓ "SOURCE 3"
        #
        # NON-MATCHING EXAMPLES:
        # ✗ "See Exhibit 1" (not at start)
        # ✗ "Exhibit One" (no digit)
        # ✗ "The figure shows..." (wrong keyword)

        # ----------------------------------------------------------------
        # AI VISION PROMPT
        # ----------------------------------------------------------------
        self.vision_prompt = "Analyze this visual. Describe layout, data, arrows, or relationships shown."
        # Used in _describe_image() for GPT-4 Vision API calls
        #
        # PROMPT DESIGN RATIONALE:
        # - "Analyze this visual" → Sets analytical tone
        # - "Describe layout" → Captures structure (rows, columns, sections)
        # - "data" → Focuses on numbers, values, metrics
        # - "arrows" → Identifies relationships, flows, processes
        # - "relationships shown" → Captures correlations, comparisons
        #
        # COMBINED WITH:
        # - max_tokens=200 → Keeps descriptions concise
        # - model=gpt-4o → Best vision understanding
        #
        # EXAMPLE OUTPUTS:
        # "Bar chart showing quarterly revenue across 4 regions.
        #  Y-axis: Revenue in millions. X-axis: Q1-Q4 2024.
        #  North America leads with $45M in Q4."

    # ================================================================
    # METHOD: extract (Main Entry Point)
    # ================================================================
    def extract(self, input_path: str):
        """
        Main extraction entry point - processes PDF file or folder
        ===========================================================

        FUNCTION FLOW:
        --------------
        1. Validate input path (file vs folder)
        2. Collect all PDF files to process
        3. Iterate through each PDF
        4. Call _process_pdf() for individual file processing

        PARAMETERS:
        -----------
        input_path : str
            Path to either:
            - Single PDF file: "/path/to/document.pdf"
            - Folder containing PDFs: "/path/to/pdfs/"

        BEHAVIOR:
        ---------
        If input_path is a FILE:
            - Process only that single PDF
            - Example: "report.pdf" → Process "report.pdf"

        If input_path is a FOLDER:
            - Find all *.pdf files in that folder (non-recursive)
            - Process each PDF independently
            - Example: "pdfs/" containing [a.pdf, b.pdf] → Process both
            - Does NOT search subfolders (use glob("**/*.pdf") for recursive)

        ERROR HANDLING:
        ---------------
        - No PDFs found → Print error and exit
        - Individual PDF errors → Handled in _process_pdf()
        - Each PDF processes independently (one failure doesn't stop others)

        RETURNS:
        --------
        None (output written to disk)
        """

        # ----------------------------------------------------------------
        # INPUT PATH VALIDATION
        # ----------------------------------------------------------------
        input_path = Path(input_path)
        # Convert string to Path object for robust path handling
        # Benefits:
        #   - Cross-platform compatibility (Windows/Linux/Mac)
        #   - Built-in methods (.is_file(), .glob(), etc.)
        #   - Automatic path separator handling (/ vs \)

        # ----------------------------------------------------------------
        # FILE COLLECTION LOGIC
        # ----------------------------------------------------------------
        files = [input_path] if input_path.is_file() else list(input_path.glob("*.pdf"))
        # CONDITIONAL LOGIC:
        #
        # IF input_path.is_file() == True:
        #   → Single PDF file provided
        #   → Create list with just that one file: [input_path]
        #
        # ELSE (is a folder):
        #   → Use glob("*.pdf") to find all PDF files
        #   → glob() returns generator → convert to list
        #   → Pattern "*.pdf" matches: report.pdf, data.pdf, etc.
        #   → Does NOT match: file.PDF (case-sensitive on Linux)
        #   → Does NOT search subfolders
        #
        # RESULT: files is always a list of Path objects

        # ----------------------------------------------------------------
        # VALIDATION: ENSURE PDFs WERE FOUND
        # ----------------------------------------------------------------
        if not files:
            # Empty list means:
            #   - Folder exists but contains no *.pdf files
            #   - File path doesn't exist
            #   - Permission denied
            print("No PDF files found.")
            return  # Exit method early

        # ----------------------------------------------------------------
        # PROCESS EACH PDF INDEPENDENTLY
        # ----------------------------------------------------------------
        for pdf in files:
            # ITERATION PATTERN:
            # pdf is a Path object pointing to one PDF file
            #
            # INDEPENDENCE:
            # Each PDF is processed separately
            # If one fails, others continue (error handling in _process_pdf)
            #
            # MEMORY MANAGEMENT:
            # Each iteration:
            #   1. Loads PDF into memory
            #   2. Processes all pages
            #   3. Saves outputs
            #   4. Releases memory (Python garbage collection)
            # For large batches, consider batch size limits

            self._process_pdf(pdf)
            # Call the main processing method for this PDF
            # All heavy lifting happens inside _process_pdf()
            # Method naming convention: _method = private/internal

    # ================================================================
    # METHOD: _process_pdf (Core Processing Pipeline)
    # ================================================================
    def _process_pdf(self, pdf_path: Path):
        """
        Process a single PDF through the complete extraction pipeline
        ===============================================================

        COMPLETE WORKFLOW:
        ------------------
        Phase 1: SETUP
            - Create output directory structure
            - Prepare pages/ and figures/ folders

        Phase 2: DOCLING ANALYSIS
            - Convert PDF using Docling ML models
            - Extract document structure and items

        Phase 3: ITEM COLLECTION
            - Group items by page number
            - Preserve hierarchy levels

        Phase 4: SMART PROCESSING (Per-Page Loop)
            - Access page image for snapping
            - Smart reorder: [Visual, Caption] → [Caption, Visual]
            - Process each item type:
                • SectionHeaderItem → Update breadcrumbs + Snap check
                • PictureItem → Extract + AI analyze
                • TableItem → Extract visual + structured data
                • TextItem → Add to Markdown
            - Save page Markdown file

        Phase 5: METADATA
            - Compile processing statistics
            - Save metadata.json

        PARAMETERS:
        -----------
        pdf_path : Path
            Path object pointing to the PDF file to process

        ERROR HANDLING:
        ---------------
        - Docling conversion errors → Print error, skip PDF
        - Individual item errors → Handled in helper methods
        - Continues processing even if some visuals fail

        OUTPUT STRUCTURE CREATED:
        -------------------------
        output_dir/document_name/
        ├── pages/
        │   ├── page_1.md       # Markdown with embedded images
        │   ├── page_2.md
        │   └── page_N.md
        ├── figures/
        │   ├── fig_p1_1.png    # Standard extracted images
        │   ├── snap_p2_1.png   # Smart-snapped regions
        │   └── ...
        └── metadata.json       # Processing metadata

        COORDINATE SYSTEM HANDLING:
        ---------------------------
        This method manages the critical transformation between:

        PDF Coordinates (Docling BBox):
            Origin: Bottom-Left
            X: Left→Right (0 to page_width)
            Y: Bottom→Top (0 to page_height)
            bbox = {l: left, b: bottom, r: right, t: top}

        PIL Image Coordinates:
            Origin: Top-Left
            X: Left→Right (0 to image_width)
            Y: Top→Down (0 to image_height)
            crop_box = (left, top, right, bottom)

        Transformation (performed in _snap_region):
            pil_x = pdf_x * scale
            pil_y = (page_h - pdf_y) * scale
        """

        # ----------------------------------------------------------------
        # PHASE 1: SETUP - Output Directory Structure
        # ----------------------------------------------------------------
        print(f"\nProcessing: {pdf_path.name}")
        # pdf_path.name extracts filename: "/path/to/report.pdf" → "report.pdf"

        doc_out_dir = self.output_dir / pdf_path.stem
        # pdf_path.stem extracts filename WITHOUT extension
        # Example: "report.pdf" → "report"
        # Full path: "extracted_docs_hybrid_v2/report/"

        (doc_out_dir / "pages").mkdir(parents=True, exist_ok=True)
        # Create pages/ subdirectory
        # parents=True: Creates intermediate directories if needed
        # exist_ok=True: Don't error if directory already exists
        # Result: "extracted_docs_hybrid_v2/report/pages/"

        (doc_out_dir / "figures").mkdir(parents=True, exist_ok=True)
        # Create figures/ subdirectory for all visual outputs
        # Result: "extracted_docs_hybrid_v2/report/figures/"

        # ----------------------------------------------------------------
        # PHASE 2: DOCLING ANALYSIS - ML-Powered PDF Parsing
        # ----------------------------------------------------------------
        print("   [1/4] Analyzing Layout & Rendering Pages...")
        # Progress indicator for user feedback

        try:
            # CONVERSION PROCESS (INTERNAL STEPS):
            # 1. Load PDF file into memory
            # 2. Run layout detection model (ds4sd/docling-layout-v1)
            #    - Identifies regions: text, images, tables, headers
            #    - Outputs bounding boxes + element classifications
            # 3. Run table structure model (if do_table_structure=True)
            #    - Parses rows, columns, cells, merged cells
            # 4. Render page images (if generate_page_images=True)
            #    - Creates PIL Image for each page at specified scale
            # 5. Extract embedded images (if generate_picture_images=True)
            # 6. Build document tree (hierarchy, reading order)
            # 7. Create DoclingDocument object with all elements

            conv_res = self.converter.convert(pdf_path)
            # converter.convert() is the main Docling processing method
            # Returns: ConversionResult object
            # Processing time: ~30-60 sec/page on CPU, ~3-5 sec/page on GPU

            doc = conv_res.document
            # Extract the DoclingDocument object
            # doc contains:
            #   - .pages[]: List of Page objects (images, dimensions)
            #   - .iterate_items(): Generator for all document elements
            #   - Hierarchy information
            #   - Provenance (which page each item came from)

        except Exception as e:
            # POSSIBLE ERRORS:
            # - Corrupted PDF file
            # - Encrypted/password-protected PDF
            # - Unsupported PDF version
            # - Out of memory (very large PDF)
            # - Missing ML models (first run without internet)

            print(f" Error: {e}")
            # Print specific error for debugging

            return
            # Exit method early, don't attempt further processing
            # Other PDFs in batch will still be processed

        # ----------------------------------------------------------------
        # PHASE 3: ITEM COLLECTION - Group by Page
        # ----------------------------------------------------------------
        print("   [2/4] Collecting items...")

        pages_items = {}
        # Dictionary structure:
        # {
        #   1: [{"item": SectionHeaderItem, "level": 1}, ...],
        #   2: [{"item": TextItem, "level": 1}, ...],
        #   ...
        # }
        # Key: page_no (integer)
        # Value: List of item dictionaries

        for item, level in doc.iterate_items():
            # ITERATION DETAILS:
            # doc.iterate_items() yields tuples: (item, level)
            #
            # item: One of the DocItem types:
            #   - SectionHeaderItem: Headers/titles (level 1, 2, 3...)
            #   - TextItem: Regular paragraphs
            #   - PictureItem: Images/charts/diagrams
            #   - TableItem: Tables/charts-as-tables
            #   - ListItem: Bullet/numbered lists
            #   - etc.
            #
            # level: Hierarchy depth (integer)
            #   - Used primarily for SectionHeaderItem
            #   - level=1: Top-level section ("Introduction")
            #   - level=2: Subsection ("Background")
            #   - level=3: Sub-subsection ("Historical Context")
            #   - Other items inherit level from last header

            if not item.prov:
                continue
                # PROVENANCE CHECK:
                # item.prov (provenance) contains source information
                # If None/empty: Item has no page location → skip it
                # This filters out metadata items not tied to specific pages

            p_no = item.prov[0].page_no
            # Extract page number from first provenance entry
            # item.prov is a list (can have multiple sources)
            # item.prov[0]: First/primary source
            # .page_no: Page number (1-indexed: page 1, 2, 3...)

            if p_no not in pages_items:
                pages_items[p_no] = []
                # Initialize empty list for this page if first item from page

            pages_items[p_no].append({
                "item": item,    # Store the actual DocItem object
                "level": level   # Store hierarchy depth
            })
            # Add item to this page's list
            # Preserves document reading order
            # Each item tracks its own type and level

        # ----------------------------------------------------------------
        # PHASE 4: SMART PROCESSING - Per-Page Loop
        # ----------------------------------------------------------------
        print("   [3/4] Processing with Hybrid Snapping...")

        metadata_pages = []
        # List to store per-page metadata for final JSON output

        global_offset = 0
        # Character offset tracker across all pages
        # Used to track position in concatenated document
        # Useful for search/retrieval systems

        global_breadcrumbs = []
        # Breadcrumb trail maintaining section hierarchy
        # Example progression:
        # [] → ["Introduction"] → ["Introduction", "Background"]
        # Updates as we encounter SectionHeaderItem elements

        # ----------------------------------------------------------------
        # ITERATE THROUGH PAGES IN ORDER
        # ----------------------------------------------------------------
        for p_no in sorted(pages_items.keys()):
            # sorted() ensures pages process in correct order: 1, 2, 3...
            # Important because breadcrumbs carry forward between pages

            items = pages_items[p_no]
            # Get all items for this page (already in reading order)

            # ----------------------------------------------------------------
            # IMAGE ACCESS FIX - Handle ImageRef Wrapper
            # ----------------------------------------------------------------
            # DOCLING VERSION COMPATIBILITY:
            # Older versions: doc.pages[p_no].image was a PIL Image
            # Newer versions: doc.pages[p_no].image is an ImageRef wrapper

            page_obj = doc.pages[p_no]
            # Get Page object for this page number
            # Page object contains:
            #   - .image: Full page render (PIL Image or ImageRef)
            #   - .size: Page dimensions (width, height)
            #   - .elements: Layout elements on this page

            page_image = None
            # Initialize as None (will be PIL Image if available)

            if hasattr(page_obj.image, "pil_image"):
                # NEWER DOCLING VERSIONS:
                # image is an ImageRef wrapper object
                # Actual PIL Image stored in .pil_image attribute
                page_image = page_obj.image.pil_image
                # This is the CRITICAL FIX for the crash issue

            elif page_obj.image:
                # OLDER DOCLING VERSIONS OR FALLBACK:
                # image is already a PIL Image object directly
                page_image = page_obj.image
                # Direct assignment works in older versions

            # RESULT: page_image is now a PIL Image object (or None)
            # This image is used in _snap_region() for manual cropping

            # ----------------------------------------------------------------
            # GET PAGE DIMENSIONS FOR COORDINATE CONVERSION
            # ----------------------------------------------------------------
            page_w = page_obj.size.width
            page_h = page_obj.size.height
            # Page dimensions in PDF points (1 point = 1/72 inch)
            # Typical letter size: width=612, height=792 points
            #
            # CRITICAL FOR COORDINATE TRANSFORMATION:
            # Used in _snap_region() to convert:
            #   PDF Y-coordinate (bottom-up) → PIL Y-coordinate (top-down)
            #   Formula: pil_y = (page_h - pdf_y) * scale

            # ----------------------------------------------------------------
            # SMART REORDER - Caption Before Visual
            # ----------------------------------------------------------------
            items = self._smart_reorder(items)
            # Reorders items to improve readability
            # TRANSFORMATION:
            # Before: [PictureItem, TextItem("Figure 1:")]
            # After:  [TextItem("Figure 1:"), PictureItem]
            #
            # WHY THIS MATTERS:
            # PDFs often place caption AFTER the visual in reading order
            # But human readers expect caption BEFORE visual
            # This reordering fixes that mismatch

            # ----------------------------------------------------------------
            # INITIALIZE PAGE-LEVEL TRACKING
            # ----------------------------------------------------------------
            page_lines = []
            # List of text lines to be joined into final Markdown
            # Each element is a string (paragraph, header, blockquote)

            page_images = []
            # List of image paths extracted from this page
            # Used for metadata tracking
            # Example: ["figures/fig_p1_1.png", "figures/snap_p1_2.png"]

            page_tables = []
            # List of table markers extracted from this page
            # Simple list: ["Table", "Table", ...]
            # Used to count tables in metadata

            # ----------------------------------------------------------------
            # ADD CONTEXT HEADER TO PAGE
            # ----------------------------------------------------------------
            if global_breadcrumbs:
                # If breadcrumbs exist from previous pages
                # (We're not on the first section of document)
                page_lines.append(f"")
                # Add blank line for spacing before page header

            page_lines.append(f"# Page {p_no}\n")
            # Add page number as Markdown H1 header
            # Example output: "# Page 5"

            # ----------------------------------------------------------------
            # SKIP TRACKER FOR CONSUMED ITEMS
            # ----------------------------------------------------------------
            skip_indices = set()
            # Tracks indices of items already processed/consumed
            # Used when smart snapping consumes multiple items
            # Example: If snap consumes items 3, 4, 5 → {3, 4, 5}
            # These items will be skipped in main loop

            # ----------------------------------------------------------------
            # MAIN ITEM PROCESSING LOOP
            # ----------------------------------------------------------------
            for i, entry in enumerate(items):
                # enumerate() provides both index and item
                # i: Current index in items list (0, 1, 2, ...)
                # entry: Dictionary {"item": DocItem, "level": int}

                if i in skip_indices:
                    continue
                    # Skip items already consumed by smart snapping
                    # These were processed as part of a snapshot region

                item = entry["item"]
                # Extract the actual DocItem object

                level = entry["level"]
                # Extract hierarchy depth (for headers)

                # ============================================================
                # ITEM TYPE A: SECTION HEADER (Potential Snap Trigger)
                # ============================================================
                if isinstance(item, SectionHeaderItem):
                    # SectionHeaderItem represents document structure:
                    # - Chapter titles
                    # - Section headers
                    # - Subsection headers

                    text = item.text.strip()
                    # Extract header text, remove leading/trailing whitespace
                    # Example: "  Introduction  " → "Introduction"

                    # --------------------------------------------------------
                    # UPDATE BREADCRUMB TRAIL
                    # --------------------------------------------------------
                    if len(global_breadcrumbs) >= level:
                        # If current breadcrumbs deeper/equal to new level
                        # Example: breadcrumbs=["Ch1", "Sec1.1", "Subsec1.1.1"], level=2
                        # We're entering a new level-2 section, trim deeper levels

                        global_breadcrumbs = global_breadcrumbs[:level-1]
                        # Slice to keep only parent levels
                        # [:level-1] keeps levels 0 to level-2
                        # Example: level=2 → keep [:1] → ["Ch1"]

                    global_breadcrumbs.append(text)
                    # Add current header to breadcrumb trail
                    # Example: ["Ch1"] → ["Ch1", "New Section"]

                    # BREADCRUMB EVOLUTION EXAMPLE:
                    # Start: []
                    # Level 1 "Chapter 1": ["Chapter 1"]
                    # Level 2 "Section 1.1": ["Chapter 1", "Section 1.1"]
                    # Level 3 "Subsection A": ["Chapter 1", "Section 1.1", "Subsection A"]
                    # Level 2 "Section 1.2": ["Chapter 1", "Section 1.2"]

                    # --------------------------------------------------------
                    # ADD HEADER TO MARKDOWN
                    # --------------------------------------------------------
                    page_lines.append(f"\n{'#' * (level + 1)} {text}\n")
                    # Generate Markdown header with appropriate level
                    # level + 1 because page already has H1 (# Page X)
                    # Examples:
                    #   level=1 → ## Header (H2)
                    #   level=2 → ### Header (H3)
                    #   level=3 → #### Header (H4)

                    # ========================================================
                    # SNAP CHECK: Visual Trigger Pattern Detection
                    # ========================================================
                    if self.visual_trigger.match(text) and page_image:
                        # CONDITION 1: self.visual_trigger.match(text)
                        # Checks if header matches pattern like:
                        #   "Exhibit 1:", "Figure 23:", "Chart 5:", etc.
                        #
                        # CONDITION 2: and page_image
                        # Ensures we have a page image available for cropping
                        # Without page image, snapping is impossible

                        # ----------------------------------------------------
                        # CHECK IF ALREADY HANDLED BY STANDARD VISUAL
                        # ----------------------------------------------------
                        is_handled = False
                        # Assume NOT handled unless proven otherwise

                        if i + 1 < len(items):
                            # Check if there's a next item
                            # Prevents index out of bounds error

                            next_item = items[i+1]["item"]
                            # Get the item immediately following this header

                            if isinstance(next_item, (PictureItem, TableItem)):
                                # If next item is an actual visual element
                                # Then this is a standard visual with proper caption
                                # No need for smart snapping
                                is_handled = True
                                # Mark as handled - will be processed normally

                        # ----------------------------------------------------
                        # SMART SNAPPING LOGIC
                        # ----------------------------------------------------
                        """
                        CORE ISSUE: PDFs Don't Always Have Embedded Images for Visual Content
                        ======================================================================

                        WHAT HAPPENS IN REAL-WORLD PDFs:
                        ---------------------------------
                        Many financial reports, research papers, and business documents contain
                        visual content that is NOT embedded as actual image files in the PDF.
                        Instead, they're created using PDF text rendering and formatting.

                        PDF STRUCTURE REALITY:
                        ----------------------

                        METHOD 1: Embedded Images (Standard Extraction Works)
                        ------------------------------------------------------
                        PDF Internal Structure:
                            <Image Object: chart_revenue.png>
                            <Text: "Figure 1: Revenue Trends">

                        Docling Detection:
                            ✓ Finds PictureItem (the embedded chart image)
                            ✓ Extracts it normally
                            ✓ Standard extraction handles this perfectly

                        Result: ✓ WORKS FINE


                        METHOD 2: Text-Based Visual Content (Standard Extraction FAILS)
                        -----------------------------------------------------------------
                        PDF Internal Structure:
                            <Text: "Exhibit 1: Market Analysis">
                            <Text: "• North America: 45%">
                            <Text: "• Europe: 30%">
                            <Text: "• Asia: 25%">
                            <Formatted Text Box with borders>
                            <Colored/Styled Text Elements>

                        Docling Detection:
                            ✗ NO PictureItem found (nothing embedded as image)
                            ✗ Only sees TextItems (bullet points)
                            ✗ Misses the visual layout/formatting

                        Standard Extraction Output:
                            ## Exhibit 1: Market Analysis
                            • North America: 45%
                            • Europe: 30%
                            • Asia: 25%

                        Result: ✗ LOSES VISUAL CONTEXT
                        - Box borders gone
                        - Color coding lost
                        - Spatial layout missing
                        - Looks like plain text list
                        """
                        if not is_handled:
                            # Header matches pattern BUT no visual follows
                            # This indicates text content that should be snapshot
                            # Example: "Exhibit 1: Key Points" followed by bullet list

                            print(f"      📸 Snapping Visual: '{text}'...")
                            # User feedback: What we're snapping

                            img_path, consumed = self._snap_region(
                                items,              # All items on this page
                                start_idx=i+1,     # Start from next item (after header)
                                page_image=page_image,  # Full page PIL Image
                                page_h=page_h,     # Page height for coordinate transform
                                doc_out_dir=doc_out_dir,  # Output directory
                                p_no=p_no,         # Current page number
                                img_count=len(page_images)  # Image counter for naming
                            )
                            # _snap_region RETURNS:
                            # img_path: Path to saved snapshot PNG (or None if failed)
                            # consumed: Number of items included in snapshot
                            #
                            # WHAT _snap_region DOES:
                            # 1. Collects bounding boxes from items i+1, i+2, i+3...
                            # 2. Stops at next header or visual
                            # 3. Computes aggregate bounding box
                            # 4. Converts PDF coords → PIL coords
                            # 5. Crops page image to that region
                            # 6. Saves as snap_pX_Y.png

                            if img_path:
                                # Snapshot successfully created

                                desc = self._describe_image(img_path)
                                # Send snapshot to GPT-4 Vision for analysis
                                # Returns text description of content

                                page_images.append(img_path)
                                # Track this snapshot in page metadata

                                # --------------------------------------------
                                # ADD SNAPSHOT TO MARKDOWN
                                # --------------------------------------------
                                page_lines.append(
                                    f"\n> **Visual Snapshot**\n"
                                    f"> ![{Path(img_path).name}](../figures/{Path(img_path).name})\n"
                                    f"> *AI Analysis:* {desc}\n"
                                )
                                # MARKDOWN BLOCKQUOTE FORMAT:
                                # > **Visual Snapshot**           ← Bold label
                                # > ![filename](../figures/...)   ← Image embed
                                # > *AI Analysis:* Description    ← Italic AI description
                                #
                                # RENDERING:
                                # Displays as indented block with image and description

                                # --------------------------------------------
                                # MARK CONSUMED ITEMS AS PROCESSED
                                # --------------------------------------------
                                for k in range(consumed):
                                    skip_indices.add(i + 1 + k)
                                    # Add each consumed item's index to skip set
                                    # Example: consumed=3 → skip {i+1, i+2, i+3}
                                    # These items are part of snapshot, don't process again

                # ============================================================
                # ITEM TYPE B: PICTURE (Standard Visual)
                # ============================================================
                elif isinstance(item, PictureItem):
                    # PictureItem: Embedded images in PDF
                    # Types:
                    #   - Charts (bar, line, pie, scatter)
                    #   - Graphs (network, tree, flow)
                    #   - Diagrams (architecture, process, UML)
                    #   - Photographs
                    #   - Illustrations
                    #   - Logos, icons

                    self._handle_standard_visual(
                        item,               # The PictureItem to extract
                        doc,                # Full document (needed for get_image)
                        p_no,               # Current page number
                        doc_out_dir,        # Output directory
                        page_images,        # List to append image path
                        page_lines          # List to append Markdown
                    )
                    # _handle_standard_visual DOES:
                    # 1. Call item.get_image(doc) → PIL Image
                    # 2. Save as figures/fig_pX_Y.png
                    # 3. Send to GPT-4 Vision for description
                    # 4. Append Markdown blockquote with image + description

                # ============================================================
                # ITEM TYPE C: TABLE (Dual Processing)
                # ============================================================
                elif isinstance(item, TableItem):
                    # TableItem: Two possible types
                    #   1. Actual data table (rows/columns/cells)
                    #   2. Chart/graph misclassified as table by ML model
                    #
                    # DUAL PROCESSING STRATEGY:
                    #   - Extract as IMAGE (catches charts)
                    #   - Extract as STRUCTURED DATA (gets actual tables)

                    # --------------------------------------------------------
                    # VISUAL EXTRACTION (Same as PictureItem)
                    # --------------------------------------------------------
                    self._handle_standard_visual(
                        item,               # The TableItem to extract
                        doc,                # Full document
                        p_no,               # Current page number
                        doc_out_dir,        # Output directory
                        page_images,        # List to append image path
                        page_lines,         # List to append Markdown
                        is_table=True       # Flag to label as "Table/Chart"
                    )
                    # This catches charts rendered as tables
                    # Examples:
                    #   - Complex financial tables with embedded charts
                    #   - Pivot tables with conditional formatting
                    #   - Heatmaps represented as colored cells

                    # --------------------------------------------------------
                    # STRUCTURED DATA EXTRACTION
                    # --------------------------------------------------------
                    try:
                        # WARNING FIX: export_to_dataframe() requires 'doc' parameter
                        df = item.export_to_dataframe(doc)
                        # Converts table structure to pandas DataFrame
                        # PROCESS:
                        # 1. Extract cell values
                        # 2. Detect headers (top row, left column)
                        # 3. Handle merged cells
                        # 4. Build DataFrame with proper columns/index

                        if not df.empty:
                            # Only process non-empty DataFrames
                            # Empty check prevents errors on malformed tables

                            md = df.to_markdown(index=False)
                            # Convert DataFrame to Markdown table format
                            # index=False: Don't include row numbers
                            #
                            # EXAMPLE OUTPUT:
                            # | Quarter | Revenue | Profit |
                            # |---------|---------|--------|
                            # | Q1      | $100M   | $20M   |
                            # | Q2      | $120M   | $25M   |

                            page_lines.append(f"\n{md}\n")
                            # Add Markdown table to page output

                            page_tables.append("Table")
                            # Increment table counter for metadata

                    except:
                        pass
                        # Silent failure on table export errors
                        # REASONS FOR FAILURE:
                        #   - Malformed table structure
                        #   - Chart misclassified as table (no data)
                        #   - Complex merged cells
                        # Visual extraction already succeeded, so content not lost

                # ============================================================
                # ITEM TYPE D: TEXT (Regular Content)
                # ============================================================
                elif isinstance(item, TextItem):
                    # TextItem: Regular paragraphs, sentences, body text

                    text = item.text.strip()
                    # Extract text and remove whitespace

                    # --------------------------------------------------------
                    # FILTER OUT NOISE/BOILERPLATE
                    # --------------------------------------------------------
                    if text.lower() in ["morgan stanley | research", "source:", "page"]:
                        continue
                        # Skip common boilerplate text
                        # Customize this list based on your document sources
                        # Examples to add:
                        #   - "Confidential"
                        #   - "Page X of Y"
                        #   - Company headers/footers

                    if len(text) > 1:
                        # Only include text with at least 2 characters
                        # Filters out stray characters, bullets, etc.

                        page_lines.append(text)
                        # Add text directly to page output
                        # No special formatting needed for regular paragraphs

            # ----------------------------------------------------------------
            # SAVE PAGE MARKDOWN FILE
            # ----------------------------------------------------------------
            final_text = "\n\n".join(page_lines)
            # Join all page lines with double newlines
            # Creates proper paragraph spacing in Markdown
            # Example:
            #   ["# Page 1", "## Introduction", "Some text"]
            #   → "# Page 1\n\n## Introduction\n\n Some text"

            md_name = f"page_{p_no}.md"
            # Generate filename: page_1.md, page_2.md, etc.

            with open(doc_out_dir / "pages" / md_name, "w", encoding="utf-8") as f:
                f.write(final_text)
                # Write Markdown content to file
                # encoding="utf-8": Handle international characters

            # ----------------------------------------------------------------
            # BUILD PAGE METADATA
            # ----------------------------------------------------------------
            metadata_pages.append({
                "page": p_no,                        # Page number
                "file": md_name,                     # Markdown filename
                "breadcrumbs": list(global_breadcrumbs),  # Copy of current breadcrumbs
                "images": page_images,               # List of image paths
                "tables": len(page_tables),          # Table count
                "start": global_offset,              # Character offset start
                "end": global_offset + len(final_text)  # Character offset end
            })
            # This metadata enables:
            #   - Search/retrieval systems
            #   - Table of contents generation
            #   - Page navigation
            #   - Image galleries

            global_offset += len(final_text)
            # Update global offset for next page
            # Tracks position in concatenated document

        # ----------------------------------------------------------------
        # PHASE 5: SAVE METADATA JSON
        # ----------------------------------------------------------------
        self._save_meta(doc_out_dir, pdf_path, metadata_pages)
        # Compile and save processing metadata

        print(f"   [4/4] Done! Output: {doc_out_dir}")
        # Final success message

    # ================================================================
    # METHOD: _snap_region (Visual Snapping Engine)
    # ================================================================
    def _snap_region(
        self,
        items: List[Dict],      # All items on current page
        start_idx: int,          # Index to start collecting from
        page_image,              # PIL Image of full page
        page_h: float,           # Page height (for coord transform)
        doc_out_dir: Path,       # Output directory
        p_no: int,               # Page number
        img_count: int           # Current image count (for naming)
    ):
        """
        Create visual snapshot by cropping aggregated text region
        ==========================================================

        CORE FUNCTIONALITY:
        -------------------
        When a visual trigger header (e.g., "Exhibit 1:") is NOT followed
        by an actual PictureItem/TableItem, this method:

        1. Collects subsequent text items until hitting next section/visual
        2. Aggregates their bounding boxes into single region
        3. Converts PDF coordinates → PIL image coordinates
        4. Crops page image to that region
        5. Saves as high-res PNG snapshot

        USE CASE EXAMPLE:
        -----------------
        PDF Content:
            ## Exhibit 1: Key Risk Factors
            • Market volatility
            • Regulatory changes
            • Currency fluctuations
            • Supply chain disruptions

        Standard extraction would output as plain text.
        Smart snapping creates a VISUAL snapshot preserving layout.

        COORDINATE TRANSFORMATION MATH:
        -------------------------------
        PDF Coordinate System (Docling):
            Origin: Bottom-Left corner of page
            X-axis: Left (0) → Right (page_width)
            Y-axis: Bottom (0) → Top (page_height)

            bbox structure: {l: left, b: bottom, r: right, t: top}

            Example (letter size):
                Page: 612 points wide, 792 points tall
                Text box: l=72, b=400, r=540, t=450
                Meaning: 72pt from left, 400pt from bottom

        PIL Image Coordinate System:
            Origin: Top-Left corner of image
            X-axis: Left (0) → Right (image_width)
            Y-axis: Top (0) → Bottom (image_height)

            crop_box: (left, top, right, bottom)

        Transformation Formulas:
            pil_x = pdf_x * scale
            pil_y = (page_height - pdf_y) * scale

        Visual Diagram:

        PDF (Bottom-Left Origin):        PIL (Top-Left Origin):

        (0, page_h) ┌─────┐ (page_w, page_h)    (0, 0) ┌─────┐ (img_w, 0)
                    │     │                            │     │
                    │ PDF │                            │ PIL │
                    │     │                            │     │
        (0, 0)      └─────┘ (page_w, 0)      (0, img_h) └─────┘ (img_w, img_h)

        PARAMETERS:
        -----------
        items : List[Dict]
            All items on current page (contains {"item": DocItem, "level": int})

        start_idx : int
            Index to start collecting from (typically header_index + 1)

        page_image : PIL.Image
            Full page render at specified scale (e.g., 216 DPI)

        page_h : float
            Page height in PDF points (needed for Y-coordinate flip)

        doc_out_dir : Path
            Output directory for saving snapshot

        p_no : int
            Current page number (for filename)

        img_count : int
            Current image counter (for unique naming)

        RETURNS:
        --------
        tuple: (img_path, consumed)
            img_path : str or None
                Relative path to saved snapshot ("figures/snap_pX_Y.png")
                None if snapping failed

            consumed : int
                Number of items included in snapshot (for skip tracking)
                0 if snapping failed

        ALGORITHM FLOW:
        ---------------
        1. Initialize bounding box extremes (min/max)
        2. Loop through items starting at start_idx
        3. For each item:
           - Break if SectionHeaderItem (new section starts)
           - Break if PictureItem/TableItem (visual starts)
           - Expand bounding box to include this item
           - Increment consumed counter
        4. Transform aggregated bbox: PDF → PIL coordinates
        5. Crop page image to transformed region
        6. Save as PNG file
        7. Return path and consumed count

        ERROR HANDLING:
        ---------------
        - No items to snap → Return (None, 0)
        - Cropping fails → Print warning, return (None, 0)
        - Individual processing continues even if snap fails
        """

        # ----------------------------------------------------------------
        # BOUNDARY CHECK
        # ----------------------------------------------------------------
        if start_idx >= len(items):
            return None, 0
            # No items exist after the trigger header
            # Nothing to snap

        # ----------------------------------------------------------------
        # INITIALIZE BOUNDING BOX AGGREGATOR
        # ----------------------------------------------------------------
        # We'll track the extremes across all items to snap
        # PDF coordinates: left, bottom, right, top

        l = float('inf')    # Left edge (minimum X) - start at infinity
        b = float('inf')    # Bottom edge (minimum Y in PDF) - start at infinity
        r = float('-inf')   # Right edge (maximum X) - start at negative infinity
        t = float('-inf')   # Top edge (maximum Y in PDF) - start at negative infinity

        # Using infinity allows any real coordinate to update the bounds
        # Example: First item with l=72 will update l from inf to 72

        consumed = 0
        # Counter for how many items we include in snapshot
        # Used to tell caller which items to skip in main loop

        # ----------------------------------------------------------------
        # COLLECT ITEMS AND AGGREGATE BOUNDING BOXES
        # ----------------------------------------------------------------
        for k in range(start_idx, len(items)):
            # Iterate from start_idx to end of items list
            # k is absolute index in items array

            curr = items[k]["item"]
            # Extract the DocItem object

            # --------------------------------------------------------
            # STOPPING CONDITIONS
            # --------------------------------------------------------
            if isinstance(curr, SectionHeaderItem):
                break
                # Hit a new section header - stop collecting
                # New header indicates content for new section
                # Don't include it in current snapshot

            if isinstance(curr, (PictureItem, TableItem)):
                break
                # Hit an actual visual element - stop collecting
                # Visual elements have their own extraction logic
                # Don't mix them into text snapshot

            # --------------------------------------------------------
            # BOUNDING BOX AGGREGATION
            # --------------------------------------------------------
            if curr.prov:
                # Only process items with provenance (location info)
                # Items without prov have no spatial coordinates

                bbox = curr.prov[0].bbox
                # Get bounding box from first provenance entry
                # bbox object has attributes: l, b, r, t
                # These are PDF coordinates (bottom-left origin)

                # Update bounding box extremes
                l = min(l, bbox.l)
                # Expand left edge to include this item
                # min() takes leftmost (smallest X)

                b = min(b, bbox.b)
                # Expand bottom edge to include this item
                # min() takes lowest point (smallest Y in PDF)
                # Remember: PDF Y increases UPWARD

                r = max(r, bbox.r)
                # Expand right edge to include this item
                # max() takes rightmost (largest X)

                t = max(t, bbox.t)
                # Expand top edge to include this item
                # max() takes highest point (largest Y in PDF)

                consumed += 1
                # Increment counter - we've consumed this item

        # ----------------------------------------------------------------
        # VALIDATION: ENSURE ITEMS WERE CONSUMED
        # ----------------------------------------------------------------
        if consumed == 0:
            return None, 0
            # No items had provenance or all items were filtered out
            # Nothing to snap

        # ----------------------------------------------------------------
        # COORDINATE TRANSFORMATION & IMAGE CROPPING
        # ----------------------------------------------------------------
        try:
            # ===========================================================
            # CRITICAL COORDINATE TRANSFORMATION
            # ===========================================================
            # Convert from PDF coordinates (bottom-left origin)
            # to PIL coordinates (top-left origin)

            # -----------------------------------------------------------
            # X-AXIS TRANSFORMATION (Simple Scaling)
            # -----------------------------------------------------------
            pil_left = l * self.scale
            # PDF left edge → PIL left edge
            # Simply multiply by scale factor
            # Example: l=72, scale=3.0 → pil_left=216

            pil_right = r * self.scale
            # PDF right edge → PIL right edge
            # Example: r=540, scale=3.0 → pil_right=1620

            # -----------------------------------------------------------
            # Y-AXIS TRANSFORMATION (Flip + Scale)
            # -----------------------------------------------------------
            pil_top = (page_h - t) * self.scale
            # PDF top edge → PIL top edge
            # FORMULA BREAKDOWN:
            #   page_h: Page height in PDF points (e.g., 792)
            #   t: PDF Y-coordinate of top edge (e.g., 450)
            #   page_h - t: Distance from PDF top (792 - 450 = 342)
            #   (page_h - t) * scale: PIL Y from top (342 * 3.0 = 1026)
            #
            # WHY THE FLIP:
            #   PDF: Y=450 is 450pt from BOTTOM (near middle)
            #   PIL: Need Y from TOP
            #   PDF page top is Y=792
            #   Distance from top: 792 - 450 = 342pt
            #   Scale to PIL: 342 * 3.0 = 1026 pixels from top

            pil_bottom = (page_h - b) * self.scale
            # PDF bottom edge → PIL bottom edge
            # Example: b=400, page_h=792, scale=3.0
            #   → (792 - 400) * 3.0 = 1176
            #
            # SANITY CHECK:
            #   pil_bottom should be > pil_top (PIL Y increases downward)
            #   pil_bottom=1176 > pil_top=1026 ✓

            # -----------------------------------------------------------
            # CREATE PIL CROP BOX
            # -----------------------------------------------------------
            crop_box = (pil_left, pil_top, pil_right, pil_bottom)
            # PIL crop() expects: (left, top, right, bottom)
            # All values in pixels from top-left origin
            #
            # Example values:
            # crop_box = (216, 1026, 1620, 1176)
            # Meaning: Crop region from (216, 1026) to (1620, 1176)
            # Width: 1620 - 216 = 1404 pixels
            # Height: 1176 - 1026 = 150 pixels

            # -----------------------------------------------------------
            # CROP PAGE IMAGE
            # -----------------------------------------------------------
            cropped = page_image.crop(crop_box)
            # page_image.crop() creates new Image from specified region
            # Original image remains unchanged
            # cropped is a new PIL Image object containing only the region

            # -----------------------------------------------------------
            # SAVE SNAPSHOT
            # -----------------------------------------------------------
            fname = f"snap_p{p_no}_{img_count+1}.png"
            # Generate unique filename
            # Format: snap_pPAGE_COUNT.png
            # Examples: snap_p1_1.png, snap_p3_2.png
            # p{p_no}: Page number
            # {img_count+1}: Image counter (+1 because count starts at 0)

            fpath = doc_out_dir / "figures" / fname
            # Build full path: doc_out_dir/figures/snap_pX_Y.png

            cropped.save(fpath)
            # Save cropped image as PNG
            # PNG format preserves quality (lossless compression)
            # Alternative: JPEG for smaller files (lossy)

            return str(f"figures/{fname}"), consumed
            # Return relative path (for Markdown links) and consumed count
            # Relative path allows Markdown files to reference images
            # consumed tells caller how many items to skip

        except Exception as e:
            # ===========================================================
            # ERROR HANDLING
            # ===========================================================
            # POSSIBLE ERRORS:
            # - Invalid crop coordinates (e.g., left > right)
            # - Crop box outside image bounds
            # - File I/O errors (permissions, disk space)
            # - PIL Image errors (corrupted image data)

            print(f"      ⚠️ Crop failed: {e}")
            # Print warning but continue processing
            # One failed snapshot shouldn't stop entire document

            return None, 0
            # Return failure indicators
            # Caller will skip snapshot but continue processing

    # ================================================================
    # METHOD: _smart_reorder (Caption Reordering)
    # ================================================================
    def _smart_reorder(self, items: List[Dict]) -> List[Dict]:
        """
        Reorder items to place captions BEFORE their visuals
        ======================================================

        PROBLEM:
        --------
        PDF reading order often places captions AFTER visuals:

        PDF Order:
            [PictureItem: Chart]
            [TextItem: "Figure 1: Revenue Trends"]

        Human Expectation:
            [Caption: "Figure 1: Revenue Trends"]
            [Visual: Chart]

        SOLUTION:
        ---------
        Detect [Visual, Caption] patterns and swap them.

        DETECTION PATTERN:
        ------------------
        1. Current item is PictureItem or TableItem
        2. Next item is TextItem
        3. Next item's text matches visual trigger regex:
           - Starts with: Exhibit, Figure, Fig., Chart, Source
           - Followed by: colon or space + number

        ALGORITHM:
        ----------
        1. Copy items list (don't modify original)
        2. Iterate with sliding window of 2 items
        3. Check pattern at each position
        4. If match: Swap current and next
        5. Skip ahead to avoid re-processing swapped item
        6. Return reordered list

        PARAMETERS:
        -----------
        items : List[Dict]
            List of {"item": DocItem, "level": int} dictionaries

        RETURNS:
        --------
        List[Dict]
            Reordered list with captions before visuals

        EXAMPLES:
        ---------
        Before:
            [
                {"item": PictureItem(...), "level": 1},
                {"item": TextItem("Figure 1: Analysis"), "level": 1}
            ]

        After:
            [
                {"item": TextItem("Figure 1: Analysis"), "level": 1},
                {"item": PictureItem(...), "level": 1}
            ]
        """

        # ----------------------------------------------------------------
        # BOUNDARY CHECK
        # ----------------------------------------------------------------
        if len(items) < 2:
            return items
            # Need at least 2 items to have a pair to swap
            # If 0 or 1 items, return as-is

        # ----------------------------------------------------------------
        # CREATE WORKING COPY
        # ----------------------------------------------------------------
        reordered = items.copy()
        # Shallow copy of list (entries still reference same dictionaries)
        # Prevents modifying caller's original list

        # ----------------------------------------------------------------
        # SLIDING WINDOW ITERATION
        # ----------------------------------------------------------------
        i = 0
        # Index pointer for manual iteration
        # Using while loop instead of for loop allows skipping ahead

        while i < len(reordered) - 1:
            # Continue until second-to-last item
            # -1 because we check i and i+1 (need i+1 to exist)

            curr = reordered[i]["item"]
            # Current item in window

            next_item = reordered[i+1]["item"]
            # Next item in window

            # --------------------------------------------------------
            # PATTERN DETECTION
            # --------------------------------------------------------
            if (isinstance(curr, (PictureItem, TableItem)) and
                isinstance(next_item, TextItem)):
                # CONDITION 1: Current is a visual element
                # CONDITION 2: Next is text
                # This is the [Visual, Text] pattern we're looking for

                if self.visual_trigger.match(next_item.text.strip()):
                    # CONDITION 3: Text matches caption pattern
                    # Regex checks for: "Figure 1:", "Exhibit 5:", etc.
                    # .strip() removes whitespace before matching

                    # ================================================
                    # SWAP OPERATION
                    # ================================================
                    reordered[i], reordered[i+1] = reordered[i+1], reordered[i]
                    # Python tuple unpacking for simultaneous swap
                    # Equivalent to:
                    #   temp = reordered[i]
                    #   reordered[i] = reordered[i+1]
                    #   reordered[i+1] = temp

                    # RESULT:
                    # Before: [Visual, Caption, ...]
                    # After:  [Caption, Visual, ...]

                    i += 1
                    # Skip ahead one position
                    # Prevents re-processing the swapped caption
                    # Without this, we might swap back on next iteration

            i += 1
            # Move to next position

        return reordered
        # Return the reordered list

    # ================================================================
    # METHOD: _handle_standard_visual (Visual Extraction)
    # ================================================================
    def _handle_standard_visual(
        self,
        item,                   # PictureItem or TableItem
        doc,                    # Full document object
        p_no: int,              # Page number
        out_dir: Path,          # Output directory
        img_list: List,         # List to append image path
        lines: List,            # List to append Markdown
        is_table: bool = False  # Flag for table vs picture
    ):
        """
        Extract and analyze standard visual elements (images/tables)
        ============================================================

        PROCESS:
        --------
        1. Extract image from PictureItem/TableItem
        2. Save as high-resolution PNG
        3. Send to GPT-4 Vision for AI analysis
        4. Append Markdown blockquote with image + description

        DUAL NATURE OF TableItem:
        -------------------------
        TableItem can represent BOTH:
        1. Actual data table (rows/columns/cells)
        2. Chart/graph misclassified as table

        This method extracts the VISUAL representation.
        Structured data extraction happens separately in _process_pdf.

        PARAMETERS:
        -----------
        item : PictureItem or TableItem
            Visual element to extract

        doc : DoclingDocument
            Full document object (needed for get_image call)

        p_no : int
            Current page number (for filename)

        out_dir : Path
            Output directory (contains figures/ folder)

        img_list : List
            List to append image path (for metadata tracking)

        lines : List
            List to append Markdown content (for page output)

        is_table : bool, optional
            If True, label as "Table/Chart" instead of "Visual Element"
            Default: False

        RETURNS:
        --------
        None (modifies img_list and lines in-place)

        OUTPUT FORMAT:
        --------------
        Markdown blockquote with:
        - Label (Visual Element or Table/Chart)
        - Embedded image
        - AI-generated description

        Example:
        > **Visual Element**
        > ![fig_p1_1.png](../figures/fig_p1_1.png)
        > *AI Analysis:* Bar chart showing quarterly revenue...
        """

        try:
            # --------------------------------------------------------
            # IMAGE EXTRACTION
            # --------------------------------------------------------
            img_obj = item.get_image(doc)
            # Extract PIL Image from document item
            # item.get_image(doc) is a Docling method
            #
            # HOW IT WORKS:
            # 1. Retrieves image data from PDF
            # 2. Applies scaling (self.scale = 3.0)
            # 3. Returns PIL.Image object
            #
            # WORKS FOR:
            # - PictureItem: Embedded images/charts
            # - TableItem: Table rendered as image
            #
            # RETURNS:
            # - PIL.Image object if successful
            # - None if extraction fails

            if img_obj:
                # Only proceed if image extraction succeeded

                # ----------------------------------------------------
                # FILENAME GENERATION
                # ----------------------------------------------------
                fname = f"fig_p{p_no}_{len(img_list)+1}.png"
                # Format: fig_pPAGE_COUNT.png
                # p{p_no}: Page number
                # {len(img_list)+1}: Image counter for this page
                # +1 because list index starts at 0
                #
                # EXAMPLES:
                # - First image on page 1: fig_p1_1.png
                # - Second image on page 1: fig_p1_2.png
                # - First image on page 5: fig_p5_1.png

                fpath = out_dir / "figures" / fname
                # Build full path: out_dir/figures/fig_pX_Y.png

                # ----------------------------------------------------
                # SAVE IMAGE
                # ----------------------------------------------------
                img_obj.save(fpath)
                # Save PIL Image as PNG file
                # PNG format: Lossless compression, good quality
                # At 3.0x scale (216 DPI), produces publication-quality images

                # ----------------------------------------------------
                # AI ANALYSIS
                # ----------------------------------------------------
                desc = self._describe_image(fpath)
                # Send image to GPT-4 Vision API
                # Returns text description of visual content
                # Falls back to "Analysis failed." on error

                # ----------------------------------------------------
                # UPDATE TRACKING LISTS
                # ----------------------------------------------------
                img_list.append(f"figures/{fname}")
                # Add relative path to image list
                # Used in metadata.json for page tracking
                # Relative path format allows portable Markdown links

                # ----------------------------------------------------
                # GENERATE LABEL
                # ----------------------------------------------------
                type_lbl = "Table/Chart" if is_table else "Visual Element"
                # Conditional label based on item type
                # is_table=True → "Table/Chart"
                # is_table=False → "Visual Element"
                # Helps users distinguish table visuals from pictures

                # ----------------------------------------------------
                # MARKDOWN BLOCKQUOTE
                # ----------------------------------------------------
                lines.append(
                    f"\n> **{type_lbl}**\n"
                    f"> ![{fname}](../figures/{fname})\n"
                    f"> *AI Analysis:* {desc}\n"
                )
                # MARKDOWN BREAKDOWN:
                #
                # \n> **{type_lbl}**\n
                #   - \n: Blank line before blockquote
                #   - >: Blockquote marker (indented rendering)
                #   - **: Bold formatting
                #   - {type_lbl}: "Visual Element" or "Table/Chart"
                #
                # > ![{fname}](../figures/{fname})\n
                #   - ![...]: Markdown image syntax
                #   - {fname}: Alt text (displayed if image fails)
                #   - ../figures/{fname}: Relative path (up one dir, into figures/)
                #   - Relative paths work from pages/ directory
                #
                # > *AI Analysis:* {desc}\n
                #   - *...*: Italic formatting
                #   - {desc}: GPT-4 Vision description
                #
                # RENDERED APPEARANCE:
                # Indented block with:
                # - Bold header
                # - Embedded image
                # - Italic AI description

        except:
            pass
            # Silent failure on image extraction errors
            # REASONS FOR FAILURE:
            # - Corrupted image data in PDF
            # - Unsupported image format
            # - Memory allocation errors
            # - File I/O errors
            #
            # WHY SILENT:
            # - Don't want one image failure to stop document processing
            # - Other visuals and text content still extractable
            # - User sees which images are missing from output

    # ================================================================
    # METHOD: _describe_image (AI Vision Analysis)
    # ================================================================
    def _describe_image(self, path: str) -> str:
        """
        Send image to GPT-4 Vision and return AI-generated description
        ===============================================================

        PROCESS:
        --------
        1. Load image file from disk
        2. Encode as base64 string
        3. Construct OpenAI API request with image + prompt
        4. Send to GPT-4 Vision endpoint
        5. Extract and return description text

        API CALL DETAILS:
        -----------------
        Model: gpt-4o (GPT-4 with optimized vision)
        Max Tokens: 200 (concise descriptions)
        Input: Image + text prompt
        Output: Text description

        PROMPT STRATEGY:
        ----------------
        "Analyze this visual. Describe layout, data, arrows, or
         relationships shown."

        Design principles:
        - Open-ended → Works for any visual type
        - Specific keywords → Guides focus (layout, data, relationships)
        - Concise → Combined with max_tokens=200

        PARAMETERS:
        -----------
        path : str
            File path to image (PNG format)

        RETURNS:
        --------
        str
            AI-generated description
            OR "Analysis failed." if error occurs

        ERROR HANDLING:
        ---------------
        - File I/O errors → Return "Analysis failed."
        - API errors → Return "Analysis failed."
        - Network errors → Return "Analysis failed."
        - Rate limiting → Return "Analysis failed."

        COST CONSIDERATIONS:
        --------------------
        - Vision API costs per image + tokens generated
        - Typical: $0.01-0.05 per image (varies by size)
        - max_tokens=200 limits response length and cost

        EXAMPLE OUTPUTS:
        ----------------
        For a bar chart:
        "Bar chart comparing quarterly revenue across four regions.
         Y-axis shows revenue in millions (0-50M range). X-axis has
         Q1-Q4 labels. North America (blue) leads with 45M in Q4."

        For a diagram:
        "System architecture diagram with three tiers. Top: User
         Interface layer. Middle: Application Server with arrows to
         Database. Bottom: Data Storage. Bidirectional arrows show
         data flow between components."
        """

        try:
            # --------------------------------------------------------
            # IMAGE LOADING & ENCODING
            # --------------------------------------------------------
            with open(path, "rb") as f:
                # Open image file in binary read mode
                # "rb": read binary (required for images)
                # with statement ensures file closes after block

                b64 = base64.b64encode(f.read()).decode()
                # ENCODING PROCESS:
                # 1. f.read(): Read entire file as bytes
                # 2. base64.b64encode(): Convert bytes to base64 bytes
                # 3. .decode(): Convert base64 bytes to string
                #
                # WHY BASE64:
                # - OpenAI API requires images as base64 strings
                # - Allows embedding binary data in JSON
                # - Standard format for API image transmission
                #
                # RESULT: String like "iVBORw0KGgoAAAANSUhEUgA..."

            # --------------------------------------------------------
            # OPENAI API CALL
            # --------------------------------------------------------
            resp = self.openai.chat.completions.create(
                model=self.model,
                # Model: "gpt-4o" (from __init__)
                # GPT-4 Optimized with vision capabilities
                # Best vision understanding among OpenAI models

                messages=[{
                    "role": "user",
                    # Message from user role (standard for ChatGPT API)

                    "content": [
                        # Content is an array of content blocks
                        # Allows mixing text and images

                        {
                            "type": "text",
                            "text": self.vision_prompt
                        },
                        # TEXT BLOCK:
                        # Contains analysis prompt
                        # "Analyze this visual. Describe layout, data,
                        #  arrows, or relationships shown."

                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}"
                            }
                        }
                        # IMAGE BLOCK:
                        # url: Data URI with base64 image
                        # Format: data:image/png;base64,<base64_string>
                        #
                        # DATA URI BREAKDOWN:
                        # - data: → Data URI scheme
                        # - image/png → MIME type (could be jpeg, webp, etc.)
                        # - ;base64, → Encoding indicator
                        # - {b64} → Actual base64 string
                    ]
                }],

                max_tokens=200
                # Limit response length to 200 tokens
                # REASONING:
                # - Keeps descriptions concise
                # - Reduces API costs
                # - Faster response times
                # - Sufficient for visual summaries
                #
                # TOKEN ESTIMATE:
                # 200 tokens ≈ 150 words ≈ 2-3 sentences
            )
            # API CALL MECHANICS:
            # 1. Constructs JSON request with image + prompt
            # 2. Sends HTTPS POST to api.openai.com/v1/chat/completions
            # 3. GPT-4 Vision processes image through vision encoder
            # 4. Generates text description based on visual understanding
            # 5. Returns response object with description

            # --------------------------------------------------------
            # EXTRACT DESCRIPTION FROM RESPONSE
            # --------------------------------------------------------
            return resp.choices[0].message.content
            # RESPONSE STRUCTURE:
            # resp.choices: List of completion choices (usually 1)
            # [0]: First (and typically only) choice
            # .message: Message object containing response
            # .content: Actual text content (the description)
            #
            # EXAMPLE CONTENT:
            # "Line chart showing upward trend from 2020-2024.
            #  Y-axis represents revenue ($0-100M). Sharp increase
            #  visible in 2023-2024 period."

        except:
            return "Analysis failed."
            # CATCH-ALL ERROR HANDLER
            # Returns fallback text instead of raising exception
            #
            # POSSIBLE ERRORS:
            # - FileNotFoundError: Image file doesn't exist
            # - PermissionError: Can't read file
            # - OpenAI API errors:
            #   - Rate limit exceeded
            #   - Authentication failed (invalid API key)
            #   - Network timeout
            #   - Service unavailable
            # - JSON encoding errors
            # - Base64 encoding errors
            #
            # WHY SILENT FAILURE:
            # - Document processing continues even without AI descriptions
            # - User still gets images, just without AI analysis
            # - Better than crashing entire extraction process

    # ================================================================
    # METHOD: _save_meta (Metadata Generation)
    # ================================================================
    def _save_meta(
        self,
        out: Path,              # Output directory
        pdf: Path,              # Source PDF path
        pages: List[Dict]       # Per-page metadata
    ):
        """
        Save processing metadata to JSON file
        ======================================

        PURPOSE:
        --------
        Creates comprehensive metadata file documenting:
        - Source PDF information
        - Processing timestamp
        - Per-page statistics (images, tables, breadcrumbs)
        - Character offsets for search/retrieval

        METADATA STRUCTURE:
        -------------------
        {
            "file": "source.pdf",
            "processed": "2024-01-29T14:30:45.123456",
            "tool": "Docling Hybrid Snap V2",
            "pages": [
                {
                    "page": 1,
                    "file": "page_1.md",
                    "breadcrumbs": ["Introduction", "Background"],
                    "images": ["figures/fig_p1_1.png", "figures/snap_p1_2.png"],
                    "tables": 2,
                    "start": 0,
                    "end": 1523
                },
                ...
            ]
        }

        USE CASES:
        ----------
        1. Search Systems: Use offsets to locate content
        2. Navigation: Build table of contents from breadcrumbs
        3. Analytics: Count images, tables per page
        4. Auditing: Track when/how documents were processed
        5. Debugging: Verify which pages had issues

        PARAMETERS:
        -----------
        out : Path
            Output directory where metadata.json will be saved

        pdf : Path
            Source PDF file path (used to extract filename)

        pages : List[Dict]
            List of per-page metadata dictionaries
            Built in _process_pdf() method

        OUTPUT FILE:
        ------------
        Location: out/metadata.json
        Format: Pretty-printed JSON (indent=2)
        Encoding: UTF-8 (supports international characters)
        """

        # ----------------------------------------------------------------
        # BUILD METADATA DICTIONARY
        # ----------------------------------------------------------------
        meta = {
            "file": pdf.name,
            # Source filename: "report.pdf"
            # .name extracts just filename from full path

            "processed": datetime.now().isoformat(),
            # Processing timestamp in ISO 8601 format
            # Example: "2024-01-29T14:30:45.123456"
            # .isoformat() creates standard datetime string
            # Includes: year, month, day, hour, minute, second, microsecond

            "tool": "Docling Hybrid Snap V2",
            # Tool identifier for version tracking
            # Helps distinguish outputs from different extraction versions

            "pages": pages
            # List of per-page metadata (built during processing)
            # Each entry contains:
            # - page: Page number
            # - file: Markdown filename
            # - breadcrumbs: Section hierarchy
            # - images: List of image paths
            # - tables: Table count
            # - start/end: Character offsets
        }

        # ----------------------------------------------------------------
        # SAVE TO JSON FILE
        # ----------------------------------------------------------------
        with open(out / "metadata.json", "w", encoding="utf-8") as f:
            # Build path: out/metadata.json
            # "w": Write mode (creates or overwrites file)
            # encoding="utf-8": Handle international characters

            json.dump(meta, f, indent=2)
            # json.dump(): Write Python dict as JSON
            # meta: Dictionary to serialize
            # f: File handle to write to
            # indent=2: Pretty-print with 2-space indentation
            #
            # WITHOUT INDENT:
            # {"file":"report.pdf","processed":"2024-01-29T14:30:45"}
            #
            # WITH INDENT=2:
            # {
            #   "file": "report.pdf",
            #   "processed": "2024-01-29T14:30:45"
            # }
            #
            # Pretty-printing makes JSON human-readable
            # Useful for manual inspection and debugging


# ================================================================
# MAIN EXECUTION BLOCK
# ================================================================
if __name__ == "__main__":
    """
    Command-line interface for Docling Hybrid Snap V2
    ==================================================
    
    USAGE:
    ------
    python extract_docling_hybrid_snap_v2.py /path/to/pdf_or_folder
    
    ARGUMENTS:
    ----------
    path : str (positional, required)
        Path to either:
        - Single PDF file: process just that file
        - Directory: process all *.pdf files in directory
    
    EXAMPLES:
    ---------
    # Single file
    python extract_docling_hybrid_snap_v2.py report.pdf
    
    # Folder
    python extract_docling_hybrid_snap_v2.py ./quarterly_reports/
    
    # Absolute path
    python extract_docling_hybrid_snap_v2.py /data/documents/annual_report.pdf
    
    OUTPUT:
    -------
    Creates extracted_docs_hybrid_v2/ directory with:
    - Subdirectory per PDF (named after PDF stem)
    - pages/ folder with Markdown files
    - figures/ folder with PNG images
    - metadata.json with processing info
    """

    # ----------------------------------------------------------------
    # ARGUMENT PARSER SETUP
    # ----------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Extract PDFs with hybrid visual snapping",
        epilog="Educational tool for Applied GenAI course"
    )
    # argparse: Standard Python library for CLI argument parsing
    # Provides:
    # - Automatic help text generation (-h, --help)
    # - Type validation
    # - Error messages for invalid input

    parser.add_argument(
        "path",
        help="PDF file or folder containing PDFs"
    )
    # Positional argument (no -- prefix)
    # Required (no default value)
    # help: Text shown in --help output

    # ----------------------------------------------------------------
    # PARSE ARGUMENTS
    # ----------------------------------------------------------------
    args = parser.parse_args()
    # Parses sys.argv (command-line arguments)
    # Returns Namespace object with attributes matching argument names
    # Example: args.path contains the path provided by user

    # ----------------------------------------------------------------
    # INSTANTIATE AND RUN EXTRACTOR
    # ----------------------------------------------------------------
    DoclingHybridSnapV2().extract(args.path)
    # EXECUTION FLOW:
    # 1. DoclingHybridSnapV2(): Create extractor instance
    #    - Initializes Docling converter
    #    - Sets up OpenAI client
    #    - Compiles regex patterns
    # 2. .extract(args.path): Process PDF(s)
    #    - Validates path
    #    - Collects PDF files
    #    - Processes each through pipeline
    #    - Saves outputs to disk