"""
================================================================================
                    Docling Smart-Sort V2 (Visuals Enhanced)
                         Comprehensive Documentation
================================================================================

MODULE OVERVIEW:
================
This module provides an intelligent PDF extraction pipeline using Docling library
with advanced visual processing capabilities. It addresses common issues with
PDF extraction such as caption placement, missing charts in tables, and ensures
high-resolution image capture.

CORE CAPABILITIES:
==================
- Smart Caption Reordering: Intelligently places captions before their associated visuals
- Visual Table Detection: Extracts images from TableItems to catch misclassified charts
- High Resolution Images: 3.0x scale (216 DPI) for sharp, clear figures
- Breadcrumb Context: Hierarchical section tracking across pages
- AI-Powered Analysis: GPT-4 Vision descriptions for all visual elements
- Zero Size Filtering: Captures all diagrams regardless of size

KEY IMPROVEMENTS OVER V1:
=========================
1. Caption Placement: Implements smart reordering to fix upside-down captions
2. Missing Visuals Fix: Extracts images from both PictureItem AND TableItem
3. No Size Limits: Removed dimension filtering to preserve small diagrams
4. Enhanced Table Handling: Detects when tables are actually charts/graphs

ARCHITECTURAL FLOW:
===================
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DOCLING PROCESSING PIPELINE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐      │
│  │  INPUT   │──────▶│ DOCLING  │──────▶│  SMART   │──────▶│ EXTRACT  │      │
│  │  PDF     │      │ ANALYZE  │      │ REORDER  │      │ VISUALS  │      │
│  └──────────┘      └──────────┘      └──────────┘      └──────────┘      │
│       │                  │                  │                  │            │
│       │                  │                  │                  │            │
│       ▼                  ▼                  ▼                  ▼            │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │              PAGE ITEM PROCESSOR                             │          │
│  │  • Breadcrumb Tracking (Section Hierarchy)                   │          │
│  │  • Caption Detection & Reordering                            │          │
│  │  • Picture Item Extraction                                   │          │
│  │  • Table Item Visual Detection                               │          │
│  │  • AI Vision Analysis (GPT-4o)                               │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                  │                                          │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    OUTPUT GENERATION                         │          │
│  │  • pages/page_1.md, page_2.md, ... page_N.md                │          │
│  │  • figures/fig_p1_1.png, fig_p1_2.png, ...                   │          │
│  │  • metadata.json (Page index with breadcrumbs)               │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

OUTPUT STRUCTURE:
=================
extracted_docs_smart_v2/
└── document_name/
    ├── metadata.json          # Master index with page info
    ├── pages/
    │   ├── page_1.md         # Reordered content with breadcrumbs
    │   ├── page_2.md
    │   └── page_N.md
    └── figures/
        ├── fig_p1_1.png      # High-res extracted images (216 DPI)
        └── fig_p2_1.png

DEPENDENCIES:
=============
- docling: PDF document conversion and layout analysis
- openai: GPT-4 Vision for image analysis
- pandas: DataFrame operations for table export
- Standard library: pathlib, json, re, base64, datetime

ENVIRONMENT VARIABLES:
======================
- OPENAI_API_KEY: Authentication for GPT-4 Vision API

USAGE EXAMPLE:
==============
    # Single PDF
    python docling_smart_v2_visuals.py /path/to/document.pdf

    # Entire folder
    python docling_smart_v2_visuals.py /path/to/pdf_folder

DESIGN PATTERNS:
================
1. Smart Reordering: Swaps [Image, Caption] to [Caption, Image] pattern
2. Dual Visual Extraction: Handles both PictureItem and TableItem as potential visuals
3. High Fidelity: 3.0x image scaling for quality preservation
4. Breadcrumb Navigation: Context-aware section tracking

AUTHOR: Prudhvi (Lead Data & AI Engineer, Thoughtworks)
VERSION: 2.0 - Visual Tables Enhancement
DATE: 2025-01-02
"""

# ============================================================================
# IMPORTS AND DEPENDENCY VALIDATION
# ============================================================================

import os
import sys
import json
import base64
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Attempt to import required external libraries
# If any are missing, provide clear installation instructions
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import TableItem, PictureItem, TextItem, SectionHeaderItem
    from openai import OpenAI
    import pandas as pd
except ImportError as e:
    print("\n" + "="*70)
    print("MISSING DEPENDENCY ERROR")
    print("="*70)
    print(f"\nMissing required library: {e}")
    print("\nInstall required packages:")
    print("  pip install docling openai pandas")
    print("\nFor full Docling support:")
    print("  pip install docling[torch]")
    print("="*70 + "\n")
    sys.exit(1)


# ============================================================================
# MAIN EXTRACTOR CLASS
# ============================================================================

class DoclingSmartV2:
    """
    Docling Smart-Sort V2 Extraction Engine
    ========================================

    CLASS PURPOSE:
    --------------
    Intelligent PDF extraction using Docling library with enhanced visual
    processing. Addresses common extraction issues including caption placement,
    chart detection in tables, and high-resolution image capture.

    KEY RESPONSIBILITIES:
    ---------------------
    1. Layout Analysis: Uses Docling to parse PDF structure (headers, text, tables, images)
    2. Smart Reordering: Fixes caption placement by detecting and swapping [Visual, Caption]
    3. Dual Visual Extraction: Treats both PictureItem AND TableItem as potential visuals
    4. High-Res Capture: 3.0x scaling (216 DPI) for quality image preservation
    5. AI Analysis: GPT-4 Vision descriptions for all extracted visuals
    6. Breadcrumb Tracking: Maintains section hierarchy across pages

    SMART REORDERING ALGORITHM:
    ---------------------------
    Problem: PDFs often have captions AFTER visuals, creating confusing output

    Example Input:
    [Image of Chart]
    "Exhibit 1: Quarterly Revenue"

    Solution: Detect caption pattern and swap:
    "Exhibit 1: Quarterly Revenue"
    [Image of Chart]

    This makes the output more readable and logical.

    VISUAL TABLE DETECTION:
    -----------------------
    Problem: Some charts are classified as TableItem instead of PictureItem

    Solution: For every TableItem, we:
    1. Attempt text extraction (if it's a data table)
    2. Also attempt image extraction (if it's actually a chart)
    3. Use whichever representation is more appropriate

    This ensures no charts are missed due to misclassification.

    ARCHITECTURE DIAGRAM:
    ---------------------
    ┌─────────────────────────────────────────────────────────────┐
    │              DoclingSmartV2                                 │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  ┌──────────────┐      ┌──────────────┐                   │
    │  │  Docling     │      │  OpenAI      │                   │
    │  │  Converter   │      │  Client      │                   │
    │  └──────────────┘      └──────────────┘                   │
    │         │                     │                            │
    │         │                     │                            │
    │  ┌──────▼─────────────────────▼───────┐                   │
    │  │   Processing Orchestrator           │                   │
    │  │   • _process_pdf()                  │                   │
    │  │   • _smart_reorder()  ◄─────────────┼─ Core Logic     │
    │  │   • _handle_visual()                │                   │
    │  │   • _describe_image()               │                   │
    │  └─────────────────────────────────────┘                   │
    │         │                                                   │
    │         ▼                                                   │
    │  ┌─────────────────────────────────────┐                   │
    │  │  Smart Reordering Engine            │                   │
    │  │  [Vis, Cap] → [Cap, Vis]            │                   │
    │  └─────────────────────────────────────┘                   │
    │         │                                                   │
    │         ▼                                                   │
    │  ┌─────────────────────────────────────┐                   │
    │  │  Dual Visual Extractor              │                   │
    │  │  • PictureItem → Image              │                   │
    │  │  • TableItem → Image OR Text        │                   │
    │  └─────────────────────────────────────┘                   │
    │         │                                                   │
    │         ▼                                                   │
    │  ┌─────────────────────────────────────┐                   │
    │  │  Output Writers                      │                   │
    │  │  • Markdown Pages                    │                   │
    │  │  • JSON Metadata                     │                   │
    │  │  • High-Res Figures                  │                   │
    │  └─────────────────────────────────────┘                   │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

    ATTRIBUTES:
    -----------
    output_dir : Path
        Root directory for all extraction outputs
    model : str
        OpenAI model identifier (default: "gpt-4o")
    openai : OpenAI
        Authenticated OpenAI client instance
    pipeline_options : PdfPipelineOptions
        Docling configuration for PDF processing
    converter : DocumentConverter
        Configured Docling converter instance
    caption_pattern : re.Pattern
        Regex pattern for detecting captions (Exhibit, Figure, Table, etc.)
    vision_prompt : str
        System prompt for AI image analysis

    METHODS:
    --------
    extract(input_path) : Main entry point - processes PDF(s)
    _process_pdf(pdf_path) : Orchestrates single PDF extraction
    _smart_reorder(items) : Implements caption reordering logic
    _handle_visual(item, ...) : Extracts and analyzes visual elements
    _describe_image(path) : AI-powered image description
    _save_meta(out_dir, pdf_path, pages) : Generates metadata.json
    """

    def __init__(
        self,
        output_base_dir: str = "extracted_docs_smart_v2",
        model: str = "gpt-4o"
    ):
        """
        Initialize the Docling Smart V2 Extractor

        INITIALIZATION FLOW:
        --------------------
        1. Set up output directory structure
        2. Configure Docling pipeline options
        3. Initialize OpenAI client
        4. Compile caption detection regex
        5. Create DocumentConverter instance

        Parameters
        ----------
        output_base_dir : str, optional
            Base directory for all extracted outputs (default: "extracted_docs_smart_v2")
            Structure: output_base_dir/document_name/{pages/, figures/, metadata.json}

        model : str, optional
            OpenAI model for vision tasks (default: "gpt-4o")
            Options: "gpt-4o", "gpt-4-turbo", "gpt-4o-mini"

        PIPELINE CONFIGURATION:
        -----------------------
        - images_scale: 3.0 → High resolution (216 DPI) for clarity
        - generate_picture_images: True → Extract PictureItem visuals
        - generate_table_images: True → Extract TableItem visuals (KEY FIX)
        - do_ocr: False → Use embedded text (cleaner output)
        - do_table_structure: True → Parse table structure
        - table_structure_options.mode: ACCURATE → Best quality table parsing
        """
        self.output_dir = Path(output_base_dir)
        self.model = model

        # Initialize OpenAI client
        # API key is read from OPENAI_API_KEY environment variable
        try:
            self.openai = OpenAI()
        except Exception as e:
            print("\n" + "="*70)
            print("OPENAI CLIENT INITIALIZATION ERROR")
            print("="*70)
            print(f"\nError: {str(e)}")
            print("\nPossible causes:")
            print("  - OPENAI_API_KEY environment variable not set")
            print("  - Invalid API key format")
            print("  - Network connectivity issues")
            print("\nHow to fix:")
            print("  export OPENAI_API_KEY='your-key-here'")
            print("="*70 + "\n")
            sys.exit(1)

        # ----------------------------------------------------------------
        # DOCLING PIPELINE CONFIGURATION
        # ----------------------------------------------------------------
        self.pipeline_options = PdfPipelineOptions()

        # High-resolution image extraction (3.0x = 216 DPI)
        # Standard 72 DPI * 3.0 = 216 DPI for sharp, publication-quality images
        self.pipeline_options.images_scale = 3.0

        # Enable image extraction from PictureItem elements
        self.pipeline_options.generate_picture_images = True

        # CRITICAL FIX: Enable image extraction from TableItem elements
        # Some PDFs misclassify charts as tables - this catches them
        self.pipeline_options.generate_table_images = True

        # Disable OCR - use embedded text for cleaner results
        # OCR is only needed for scanned documents
        self.pipeline_options.do_ocr = False

        # Enable table structure parsing
        self.pipeline_options.do_table_structure = True

        # Use ACCURATE mode for best quality table extraction
        # Trade-off: slower processing but better results
        self.pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        # Create DocumentConverter with configured pipeline
        try:
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options)
                }
            )
        except Exception as e:
            print("\n" + "="*70)
            print("DOCLING CONVERTER INITIALIZATION ERROR")
            print("="*70)
            print(f"\nError: {str(e)}")
            print("\nPossible causes:")
            print("  - Docling library not properly installed")
            print("  - Missing torch dependency")
            print("  - Incompatible library versions")
            print("\nTroubleshooting:")
            print("  pip install --upgrade docling")
            print("  pip install docling[torch]  # For full support")
            print("="*70 + "\n")
            sys.exit(1)

        # ----------------------------------------------------------------
        # CAPTION DETECTION PATTERN
        # ----------------------------------------------------------------
        # Regex to identify caption lines that should appear BEFORE visuals
        # Matches patterns like:
        # - "Exhibit 1: Revenue Analysis"
        # - "Figure 2.3: Market Share"
        # - "Table 5: Quarterly Results"
        # - "Source: Company Reports"
        # re.IGNORECASE makes it case-insensitive
        self.caption_pattern = re.compile(
            r'^(Exhibit|Figure|Fig\.|Table|Source)[:\s]+\d+',
            re.IGNORECASE
        )

        # ----------------------------------------------------------------
        # AI VISION PROMPT
        # ----------------------------------------------------------------
        # Prompt optimized for analyzing charts, diagrams, and data visuals
        # Focus on extracting actionable insights rather than visual description
        self.vision_prompt = (
            "Analyze this visual. Is it a Chart, Diagram, or Data Table? "
            "Describe the axes, trends, and key insights concisely."
        )

    def extract(self, input_path: str):
        """
        Main Entry Point for PDF Extraction

        PURPOSE:
        --------
        Handles both single PDF files and entire directories of PDFs.
        Orchestrates batch processing with independent error handling per file.

        PROCESSING LOGIC:
        -----------------
        1. Validate input path exists
        2. Determine if input is file or directory
        3. Collect PDF files to process
        4. Process each PDF independently

        Parameters
        ----------
        input_path : str
            Path to PDF file OR directory containing PDFs

        ERROR HANDLING:
        ---------------
        - Validates path existence
        - Handles both files and directories
        - Processes files independently (one failure doesn't stop others)

        EXAMPLE:
        --------
            extractor = DoclingSmartV2()
            extractor.extract("/path/to/document.pdf")
            extractor.extract("/path/to/pdf_folder/")
        """
        input_path = Path(input_path)

        # Validate that the input path exists
        if not input_path.exists():
            print("\n" + "="*70)
            print("PATH NOT FOUND ERROR")
            print("="*70)
            print(f"\nThe specified path does not exist:")
            print(f"  {input_path.absolute()}")
            print("\nPlease check:")
            print("  - Path is spelled correctly")
            print("  - File/directory has not been moved or deleted")
            print("  - You have read permissions")
            print("="*70 + "\n")
            return

        # Determine files to process
        # If input is a file, process just that file
        # If input is a directory, find all PDFs in it
        if input_path.is_file():
            # Validate it's actually a PDF
            if input_path.suffix.lower() != '.pdf':
                print("\n" + "="*70)
                print("INVALID FILE TYPE ERROR")
                print("="*70)
                print(f"\nThe specified file is not a PDF:")
                print(f"  {input_path.name}")
                print(f"  Extension: {input_path.suffix}")
                print("\nThis tool only processes PDF files (.pdf extension)")
                print("="*70 + "\n")
                return
            files = [input_path]
        else:
            # Directory: find all PDFs
            files = list(input_path.glob("*.pdf"))

        # Check if any PDFs were found
        if not files:
            print("\n" + "="*70)
            print("NO PDF FILES FOUND")
            print("="*70)
            print(f"\nNo PDF files found in:")
            print(f"  {input_path.absolute()}")
            print("\nPlease verify:")
            print("  - Directory contains PDF files")
            print("  - Files have .pdf extension")
            print("="*70 + "\n")
            return

        # Process each PDF independently
        print("\n" + "="*70)
        print(f"BATCH PROCESSING: {len(files)} PDF(s)")
        print("="*70)

        successful = []
        failed = []

        for idx, pdf in enumerate(files, 1):
            print(f"\n[{idx}/{len(files)}] Processing: {pdf.name}")
            try:
                self._process_pdf(pdf)
                successful.append(pdf.name)
                print(f"[{idx}/{len(files)}] SUCCESS: {pdf.name}")
            except Exception as e:
                failed.append(pdf.name)
                print(f"[{idx}/{len(files)}] FAILED: {pdf.name}")
                print(f"  Error: {str(e)}")

        # Final summary
        print("\n" + "="*70)
        print("BATCH PROCESSING COMPLETE")
        print("="*70)
        print(f"\nSuccessful: {len(successful)}/{len(files)}")
        print(f"Failed: {len(failed)}/{len(files)}")

        if successful:
            print("\nSuccessfully processed:")
            for pdf_name in successful:
                print(f"  [OK] {pdf_name}")

        if failed:
            print("\nFailed to process:")
            for pdf_name in failed:
                print(f"  [FAIL] {pdf_name}")

        print("="*70 + "\n")

    def _process_pdf(self, pdf_path: Path):
        """
        Process Single PDF Document

        PURPOSE:
        --------
        Orchestrates the complete extraction pipeline for one PDF file.
        Handles layout analysis, item collection, smart reordering, visual
        extraction, and output generation.

        PROCESSING STAGES:
        ------------------
        ┌─────────────────────────────────────────────────────────────┐
        │                    PDF PROCESSING PIPELINE                  │
        ├─────────────────────────────────────────────────────────────┤
        │                                                             │
        │  Stage 1: SETUP                                             │
        │  ┌─────────────────────────────────────────────────────┐   │
        │  │ • Create output directory structure                 │   │
        │  │ • Initialize page collectors                        │   │
        │  └─────────────────────────────────────────────────────┘   │
        │                          │                                  │
        │                          ▼                                  │
        │  Stage 2: DOCLING ANALYSIS                                  │
        │  ┌─────────────────────────────────────────────────────┐   │
        │  │ • Call Docling converter                            │   │
        │  │ • Parse PDF layout (headers, text, tables, images)  │   │
        │  │ • Extract document structure                        │   │
        │  └─────────────────────────────────────────────────────┘   │
        │                          │                                  │
        │                          ▼                                  │
        │  Stage 3: ITEM COLLECTION                                   │
        │  ┌─────────────────────────────────────────────────────┐   │
        │  │ • Iterate through document items                    │   │
        │  │ • Group items by page number                        │   │
        │  │ • Preserve hierarchy levels                         │   │
        │  └─────────────────────────────────────────────────────┘   │
        │                          │                                  │
        │                          ▼                                  │
        │  Stage 4: SMART PROCESSING (Per Page)                       │
        │  ┌─────────────────────────────────────────────────────┐   │
        │  │ • Smart reordering (caption placement)              │   │
        │  │ • Extract visuals (Pictures AND Tables)             │   │
        │  │ • AI vision analysis                                │   │
        │  │ • Build breadcrumb context                          │   │
        │  │ • Generate Markdown output                          │   │
        │  └─────────────────────────────────────────────────────┘   │
        │                          │                                  │
        │                          ▼                                  │
        │  Stage 5: OUTPUT GENERATION                                 │
        │  ┌─────────────────────────────────────────────────────┐   │
        │  │ • Save page Markdown files                          │   │
        │  │ • Generate metadata.json                            │   │
        │  └─────────────────────────────────────────────────────┘   │
        │                                                             │
        └─────────────────────────────────────────────────────────────┘

        Parameters
        ----------
        pdf_path : Path
            Path to the PDF file to process

        Raises
        ------
        Exception
            If Docling conversion fails or critical processing error occurs
        """
        print(f"\n{'='*70}")
        print(f"PROCESSING: {pdf_path.name}")
        print(f"{'='*70}")

        # ----------------------------------------------------------------
        # STAGE 1: Setup Output Directory
        # ----------------------------------------------------------------
        doc_out_dir = self.output_dir / pdf_path.stem

        try:
            (doc_out_dir / "pages").mkdir(parents=True, exist_ok=True)
            (doc_out_dir / "figures").mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print("\n" + "="*70)
            print("DIRECTORY CREATION ERROR")
            print("="*70)
            print(f"\nFailed to create output directories: {str(e)}")
            print("\nPossible causes:")
            print("  - Insufficient disk space")
            print("  - No write permissions")
            print("  - Invalid characters in path")
            print("="*70 + "\n")
            raise

        # ----------------------------------------------------------------
        # STAGE 2: Docling Layout Analysis
        # ----------------------------------------------------------------
        print("   [1/4] Analyzing layout with Docling...")
        try:
            conv_res = self.converter.convert(pdf_path)
            doc = conv_res.document
            print(f"      SUCCESS: Layout analysis complete")
        except FileNotFoundError as e:
            print(f"      FAILED: PDF file not found - {str(e)}")
            raise
        except PermissionError as e:
            print(f"      FAILED: Permission denied - {str(e)}")
            raise
        except Exception as e:
            print(f"      FAILED: Docling conversion error")
            print(f"      Error: {str(e)}")
            print(f"      Possible causes:")
            print(f"        - Corrupted PDF file")
            print(f"        - Unsupported PDF features")
            print(f"        - PDF encryption/protection")
            raise

        # ----------------------------------------------------------------
        # STAGE 3: Collect Items by Page
        # ----------------------------------------------------------------
        print("   [2/4] Collecting document items...")
        pages_items = {}
        item_count = 0

        try:
            # Iterate through all items in the document
            # doc.iterate_items() returns (item, hierarchy_level) tuples
            for item, level in doc.iterate_items():
                # Skip items without provenance (page location info)
                if not item.prov:
                    continue

                # Get page number from first provenance entry
                # Docling tracks which page(s) each item appears on
                p_no = item.prov[0].page_no

                # Initialize page list if this is first item on page
                if p_no not in pages_items:
                    pages_items[p_no] = []

                # Add item with its hierarchy level
                pages_items[p_no].append({
                    "item": item,    # The actual content item
                    "level": level   # Hierarchy depth (for headers)
                })
                item_count += 1

            print(f"      SUCCESS: Collected {item_count} items across {len(pages_items)} pages")
        except Exception as e:
            print(f"      FAILED: Item collection error - {str(e)}")
            raise

        # ----------------------------------------------------------------
        # STAGE 4: Smart Processing (Per Page)
        # ----------------------------------------------------------------
        print("   [3/4] Smart sorting & extracting visuals...")
        metadata_pages = []
        global_offset = 0
        global_breadcrumbs = []

        pages_processed = 0
        visuals_extracted = 0

        for p_no in sorted(pages_items.keys()):
            items = pages_items[p_no]

            # ============================================================
            # SMART REORDERING: Fix Caption Placement
            # ============================================================
            # Reorder items so captions appear BEFORE their visuals
            # Example: [Image, "Exhibit 1"] -> ["Exhibit 1", Image]
            ordered_items = self._smart_reorder(items)

            # Page-specific collectors
            page_lines = []        # Text content lines
            page_images = []       # Image filenames
            page_tables = []       # Table indicators

            # ============================================================
            # BREADCRUMB CONTEXT INJECTION
            # ============================================================
            # If we have section context from previous pages, inject it
            if global_breadcrumbs:
                context_str = " > ".join(global_breadcrumbs)
                page_lines.append(f"<!-- Context: {context_str} -->")

            # Page header
            page_lines.append(f"\n# Page {p_no}\n")

            # ============================================================
            # PROCESS EACH ITEM ON THE PAGE
            # ============================================================
            for entry in ordered_items:
                item = entry["item"]
                level = entry["level"]

                # --------------------------------------------------------
                # SECTION HEADERS: Update Breadcrumbs
                # --------------------------------------------------------
                if isinstance(item, SectionHeaderItem):
                    text = item.text.strip()

                    # Update global breadcrumb hierarchy
                    # If new header is at same/higher level, clear deeper levels
                    if len(global_breadcrumbs) >= level:
                        global_breadcrumbs = global_breadcrumbs[:level-1]

                    # Add new header to breadcrumbs
                    global_breadcrumbs.append(text)

                    # Output header with appropriate Markdown level
                    # level+1 because page title is already H1
                    page_lines.append(f"\n{'#' * (level + 1)} {text}\n")

                # --------------------------------------------------------
                # TEXT ITEMS: Standard Paragraphs
                # --------------------------------------------------------
                elif isinstance(item, TextItem):
                    text = item.text.strip()

                    # Filter out common boilerplate text
                    # Customize this list based on your document source
                    boilerplate = [
                        "morgan stanley | research",
                        "source:",
                        "page"
                    ]

                    # Skip if text matches boilerplate (case-insensitive)
                    if text.lower() in boilerplate:
                        continue

                    # Only include meaningful text (more than single character)
                    if len(text) > 1:
                        page_lines.append(text)

                # --------------------------------------------------------
                # PICTURE ITEMS: Standard Image Extraction
                # --------------------------------------------------------
                elif isinstance(item, PictureItem):
                    success = self._handle_visual(
                        item, doc, p_no, doc_out_dir,
                        page_images, page_lines, is_table=False
                    )
                    if success:
                        visuals_extracted += 1

                # --------------------------------------------------------
                # TABLE ITEMS: Dual Extraction (Text + Image)
                # --------------------------------------------------------
                # This is the KEY FIX for missing charts
                # Some charts are misclassified as tables
                elif isinstance(item, TableItem):
                    # Attempt 1: Extract as Text Table
                    md_table = ""
                    try:
                        df = item.export_to_dataframe()
                        if not df.empty:
                            md_table = df.to_markdown(index=False)
                    except Exception as e:
                        # Table text extraction failed, that's okay
                        pass

                    # Attempt 2: Extract as Visual (Chart/Graph)
                    # TableItem can have images if it's actually a chart
                    img_saved = self._handle_visual(
                        item, doc, p_no, doc_out_dir,
                        page_images, page_lines, is_table=True
                    )

                    if img_saved:
                        visuals_extracted += 1

                    # If no image was extracted but we have table text, output it
                    if not img_saved and md_table:
                        page_lines.append(f"\n{md_table}\n")
                        page_tables.append("Text Table")

            # ============================================================
            # SAVE PAGE MARKDOWN FILE
            # ============================================================
            final_text = "\n\n".join(page_lines)
            md_name = f"page_{p_no}.md"

            try:
                with open(doc_out_dir / "pages" / md_name, "w", encoding="utf-8") as f:
                    f.write(final_text)
            except IOError as e:
                print(f"      ERROR: Failed to write {md_name}: {str(e)}")
                raise

            # ============================================================
            # PAGE METADATA
            # ============================================================
            metadata_pages.append({
                "page": p_no,
                "file": md_name,
                "breadcrumbs": list(global_breadcrumbs),  # Copy of current state
                "images": page_images,
                "tables": len(page_tables),
                "start": global_offset,
                "end": global_offset + len(final_text)
            })

            global_offset += len(final_text)
            pages_processed += 1

        print(f"      SUCCESS: Processed {pages_processed} pages, extracted {visuals_extracted} visuals")

        # ----------------------------------------------------------------
        # STAGE 5: Save Metadata
        # ----------------------------------------------------------------
        print("   [4/4] Saving metadata...")
        try:
            self._save_meta(doc_out_dir, pdf_path, metadata_pages)
            print(f"      SUCCESS: Metadata saved")
        except Exception as e:
            print(f"      FAILED: Metadata save error - {str(e)}")
            raise

        print(f"\n{'='*70}")
        print(f"EXTRACTION COMPLETE")
        print(f"{'='*70}")
        print(f"Output directory: {doc_out_dir}")
        print(f"Pages: {pages_processed}")
        print(f"Visuals: {visuals_extracted}")
        print(f"{'='*70}\n")

    def _smart_reorder(self, items: List[Dict]) -> List[Dict]:
        """
        Smart Caption Reordering Algorithm

        PURPOSE:
        --------
        Fixes a common PDF extraction issue where captions appear AFTER
        their associated visuals. This function detects [Visual, Caption]
        patterns and swaps them to [Caption, Visual] for better readability.

        ALGORITHM:
        ----------
        ┌─────────────────────────────────────────────────────────────┐
        │              SMART REORDERING LOGIC                         │
        ├─────────────────────────────────────────────────────────────┤
        │                                                             │
        │  FOR each consecutive pair of items:                        │
        │    │                                                         │
        │    ├─▶ Check: Is current item a Visual?                    │
        │    │   (PictureItem or TableItem)                          │
        │    │                                                         │
        │    ├─▶ Check: Is next item a TextItem?                     │
        │    │                                                         │
        │    ├─▶ Check: Does text match caption pattern?             │
        │    │   Pattern: "Exhibit 1:", "Figure 2:", etc.            │
        │    │                                                         │
        │    └─▶ IF all checks pass: SWAP the two items             │
        │        [Visual, Caption] → [Caption, Visual]               │
        │                                                             │
        └─────────────────────────────────────────────────────────────┘

        EXAMPLE:
        --------
        Input:
        1. PictureItem (chart image)
        2. TextItem "Exhibit 1: Quarterly Revenue"
        3. TextItem "Revenue increased by 25%..."

        Output:
        1. TextItem "Exhibit 1: Quarterly Revenue"
        2. PictureItem (chart image)
        3. TextItem "Revenue increased by 25%..."

        Parameters
        ----------
        items : List[Dict]
            List of item dictionaries with structure:
            {"item": DoclingItem, "level": int}

        Returns
        -------
        List[Dict]
            Reordered list with caption-visual pairs swapped

        EDGE CASES:
        -----------
        - Less than 2 items: Returns unchanged
        - Multiple visuals in sequence: Each checked independently
        - Caption without visual: No change
        - Visual without caption: No change
        """
        # Need at least 2 items to perform swapping
        if len(items) < 2:
            return items

        # Work on a copy to avoid modifying original
        reordered = items.copy()

        # Index pointer for iteration
        i = 0
        swaps_made = 0

        # Iterate through consecutive pairs
        while i < len(reordered) - 1:
            curr = reordered[i]["item"]
            next_item = reordered[i+1]["item"]

            # ============================================================
            # SWAP LOGIC: [Visual, Caption] → [Caption, Visual]
            # ============================================================
            # Condition 1: Current item is a visual (Picture or Table)
            # Condition 2: Next item is text
            # Condition 3: Text matches caption pattern
            if (isinstance(curr, (PictureItem, TableItem)) and
                isinstance(next_item, TextItem)):

                text = next_item.text.strip()

                # Check if text matches caption pattern
                # Example matches: "Exhibit 1:", "Figure 2.3:", "Table 5:"
                if self.caption_pattern.match(text):
                    # SWAP: Exchange positions
                    reordered[i], reordered[i+1] = reordered[i+1], reordered[i]
                    swaps_made += 1

                    # Skip next position since we just swapped it
                    i += 1

            # Move to next pair
            i += 1

        # Optional: Log swap count for debugging
        if swaps_made > 0:
            print(f"      INFO: Made {swaps_made} caption reordering swaps")

        return reordered

    def _handle_visual(
        self,
        item,
        doc,
        p_no: int,
        out_dir: Path,
        img_list: List[str],
        lines: List[str],
        is_table: bool = False
    ) -> bool:
        """
        Extract and Analyze Visual Elements

        PURPOSE:
        --------
        Dual-purpose visual handler that works for BOTH PictureItem and
        TableItem. This is critical because some charts are misclassified
        as tables in the PDF structure.

        EXTRACTION WORKFLOW:
        --------------------
        ┌─────────────────────────────────────────────────────────────┐
        │              VISUAL EXTRACTION PIPELINE                     │
        ├─────────────────────────────────────────────────────────────┤
        │                                                             │
        │  Input: Item (PictureItem OR TableItem)                     │
        │    │                                                         │
        │    ├─▶ 1. Attempt get_image() from item                    │
        │    │      Works for both Pictures and Tables!              │
        │    │                                                         │
        │    ├─▶ 2. If image exists:                                 │
        │    │      • Generate filename: fig_pN_M.png                │
        │    │      • Save high-res image (216 DPI)                  │
        │    │      • Call AI vision analysis                        │
        │    │      • Add to image list                              │
        │    │      • Inject Markdown with description               │
        │    │                                                         │
        │    └─▶ 3. Return True if successful, False otherwise       │
        │                                                             │
        └─────────────────────────────────────────────────────────────┘

        Parameters
        ----------
        item : PictureItem or TableItem
            Docling item that may contain visual content
        doc : Document
            Parent document (needed for get_image())
        p_no : int
            Page number for filename generation
        out_dir : Path
            Output directory containing figures/ subdirectory
        img_list : List[str]
            Mutable list to append image filenames to
        lines : List[str]
            Mutable list to append Markdown output to
        is_table : bool, optional
            Whether item is a TableItem (affects labeling)

        Returns
        -------
        bool
            True if image was successfully extracted and saved
            False if no image available or extraction failed

        ERROR HANDLING:
        ---------------
        - Catches all exceptions to prevent one visual from crashing entire page
        - Returns False on any error
        - Allows processing to continue with remaining items

        EXAMPLE OUTPUT:
        ---------------
        Markdown injected into lines:

        > **Visual Element**
        > ![fig_p3_1.png](../figures/fig_p3_1.png)
        > *AI Analysis:* Bar chart showing quarterly revenue growth from...
        """
        try:
            # ============================================================
            # STEP 1: Attempt Image Extraction
            # ============================================================
            # Docling's get_image() works for BOTH PictureItem and TableItem
            # This is the key feature that catches misclassified charts
            img_obj = item.get_image(doc)

            # Check if image was successfully retrieved
            if img_obj:
                # ========================================================
                # STEP 2: Generate Filename and Save
                # ========================================================
                # Filename pattern: fig_p{page}_{count}.png
                # Example: fig_p3_1.png (page 3, first image)
                fname = f"fig_p{p_no}_{len(img_list)+1}.png"
                fpath = out_dir / "figures" / fname

                # Save image at high resolution (216 DPI from 3.0x scale)
                try:
                    img_obj.save(fpath)
                except IOError as e:
                    print(f"      WARNING: Failed to save {fname}: {str(e)}")
                    return False

                # ========================================================
                # STEP 3: AI Vision Analysis
                # ========================================================
                desc = self._describe_image(fpath)

                # ========================================================
                # STEP 4: Update Collections
                # ========================================================
                # Add to image list (for metadata)
                img_list.append(f"figures/{fname}")

                # Determine label based on item type
                type_label = "Table/Chart" if is_table else "Visual Element"

                # ========================================================
                # STEP 5: Inject Markdown
                # ========================================================
                # Format as blockquote for visual distinction
                # Include image, relative path, and AI description
                lines.append(
                    f"\n> **{type_label}**\n"
                    f"> ![{fname}](../figures/{fname})\n"
                    f"> *AI Analysis:* {desc}\n"
                )

                return True

        except AttributeError as e:
            # Item doesn't have get_image() method
            # This is expected for some item types
            return False
        except Exception as e:
            # Unexpected error during extraction
            # Log but don't crash
            print(f"      WARNING: Visual extraction error for page {p_no}: {str(e)}")
            return False

        return False

    def _describe_image(self, path: Path) -> str:
        """
        AI-Powered Image Description

        PURPOSE:
        --------
        Uses GPT-4 Vision to analyze extracted images and generate natural
        language descriptions focusing on chart types, trends, and insights.

        ANALYSIS WORKFLOW:
        ------------------
        ┌─────────────────────────────────────────────────────────────┐
        │            GPT-4 VISION ANALYSIS PIPELINE                   │
        ├─────────────────────────────────────────────────────────────┤
        │                                                             │
        │  1. Load image file from disk                               │
        │     │                                                        │
        │     ▼                                                        │
        │  2. Encode as base64 string                                 │
        │     (Required format for OpenAI API)                        │
        │     │                                                        │
        │     ▼                                                        │
        │  3. Construct API request:                                  │
        │     • Model: gpt-4o                                         │
        │     • Prompt: vision_prompt                                 │
        │     • Image: base64 data                                    │
        │     • max_tokens: 200                                       │
        │     │                                                        │
        │     ▼                                                        │
        │  4. Call OpenAI Vision API                                  │
        │     │                                                        │
        │     ▼                                                        │
        │  5. Extract and return description                          │
        │                                                             │
        └─────────────────────────────────────────────────────────────┘

        Parameters
        ----------
        path : Path
            Path to image file to analyze

        Returns
        -------
        str
            AI-generated description or error message

        ERROR HANDLING:
        ---------------
        Returns "Description failed." on any error to prevent processing
        interruption. Specific errors are not exposed to maintain flow.

        EXAMPLE OUTPUT:
        ---------------
        "Bar chart showing quarterly revenue growth from Q1 to Q4 2024.
        Revenue increased from $10M to $15M, with strongest growth in Q3.
        Y-axis shows revenue in millions, X-axis shows quarters."
        """
        try:
            # ============================================================
            # STEP 1: Load and Encode Image
            # ============================================================
            # Read image file as binary
            with open(path, "rb") as f:
                image_bytes = f.read()
                # Encode to base64 string (required by OpenAI API)
                b64 = base64.b64encode(image_bytes).decode('utf-8')

            # ============================================================
            # STEP 2: Call GPT-4 Vision API
            # ============================================================
            resp = self.openai.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        # Text prompt with analysis instructions
                        {
                            "type": "text",
                            "text": self.vision_prompt
                        },
                        # Image content as base64
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}"
                            }
                        }
                    ]
                }],
                max_tokens=200  # Limit response length for conciseness
            )

            # ============================================================
            # STEP 3: Extract Description
            # ============================================================
            return resp.choices[0].message.content

        except FileNotFoundError:
            return "Description failed: Image file not found."
        except ConnectionError:
            return "Description failed: Network connection error."
        except Exception as e:
            # Generic fallback for any other errors
            # Prevents one failed description from crashing entire extraction
            return "Description failed."

    def _save_meta(
        self,
        out_dir: Path,
        pdf_path: Path,
        pages: List[Dict]
    ):
        """
        Generate Metadata Index

        PURPOSE:
        --------
        Creates a JSON manifest containing document metadata and page
        information for search indexing and navigation.

        METADATA SCHEMA:
        ----------------
        {
            "file": str,              # Original PDF filename
            "processed": str,         # ISO timestamp
            "tool": str,              # Tool identifier
            "pages": [                # Array of page metadata
                {
                    "page": int,
                    "file": str,
                    "breadcrumbs": [str],
                    "images": [str],
                    "tables": int,
                    "start": int,
                    "end": int
                },
                ...
            ]
        }

        Parameters
        ----------
        out_dir : Path
            Output directory where metadata.json will be saved
        pdf_path : Path
            Original PDF path (for filename)
        pages : List[Dict]
            Page metadata from processing

        Raises
        ------
        IOError
            If metadata file cannot be written
        """
        meta = {
            "file": pdf_path.name,
            "processed": datetime.now().isoformat(),
            "tool": "Docling Smart V2 (Visual Tables)",
            "pages": pages
        }

        try:
            with open(out_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except IOError as e:
            raise IOError(f"Failed to write metadata.json: {str(e)}")
        except Exception as e:
            raise Exception(f"Unexpected error writing metadata: {str(e)}")


# ============================================================================
# COMMAND-LINE INTERFACE
# ============================================================================

if __name__ == "__main__":
    """
    CLI Entry Point
    
    PURPOSE:
    --------
    Provides command-line interface for processing PDFs with Docling Smart V2.
    
    USAGE EXAMPLES:
    ---------------
    # Single PDF
    python docling_smart_v2_visuals.py /path/to/document.pdf
    
    # Entire folder
    python docling_smart_v2_visuals.py /path/to/pdf_folder/
    
    ARGUMENT PARSING:
    -----------------
    Accepts single positional argument: path to PDF file or directory
    """
    parser = argparse.ArgumentParser(
        description="Docling Smart V2 - Intelligent PDF Extraction with Visual Enhancement",
        epilog="Example: python docling_smart_v2_visuals.py /path/to/document.pdf"
    )

    parser.add_argument(
        "path",
        help="Path to PDF file or directory containing PDFs"
    )

    args = parser.parse_args()

    # Initialize and run extractor
    try:
        extractor = DoclingSmartV2()
        extractor.extract(args.path)
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user. Exiting...")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {str(e)}")
        sys.exit(1)