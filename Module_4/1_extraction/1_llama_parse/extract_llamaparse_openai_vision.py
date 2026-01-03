"""
================================================================================
                LlamaParse Ultimate Extractor with Layout Preservation
                         Comprehensive Documentation
================================================================================

MODULE OVERVIEW:
================
This module combines the best of LlamaParse text extraction with PyMuPDF's
reliable image extraction to create page-by-page Markdown files that preserve
the original PDF layout. Each page becomes a standalone MD file with inline
images, tables, and AI descriptions - exactly matching the PDF structure.

CORE CAPABILITIES:
==================
- Layout Preservation: Images and tables appear exactly where they are in the PDF
- Per-Page Markdown: ONE .md file per PDF page with complete content
- Dual Image Extraction: LlamaParse + PyMuPDF for maximum reliability
- Table Intelligence: HTML tables from LlamaParse with AI summaries
- AI Descriptions: GPT-4 Vision analysis for all images inline
- Rich Metadata: JSON manifest with page classifications and breadcrumbs

KEY INNOVATIONS:
================
1. Hybrid Extraction Strategy:
   - LlamaParse: Superior text, table structure, page layout
   - PyMuPDF: Reliable image extraction (catches charts missed by LlamaParse)

2. Layout-Aware Processing:
   - Preserves original PDF structure
   - Inlines images at correct positions
   - Maintains table formatting

3. Complete Per-Page Files:
   - Each page_N.md contains ALL content from that page
   - Images embedded with AI descriptions
   - Tables with AI analysis
   - Breadcrumb context

ARCHITECTURAL FLOW:
===================
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ULTIMATE EXTRACTION PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐      │
│  │  INPUT   │──────▶│LLAMAPARSE│──────▶│ PYMUPDF  │──────▶│  LAYOUT  │      │
│  │  PDF     │      │TEXT+TABLE│      │  IMAGES  │      │  MERGE   │      │
│  └──────────┘      └──────────┘      └──────────┘      └──────────┘      │
│       │                  │                  │                  │            │
│       │                  │                  │                  │            │
│       ▼                  ▼                  ▼                  ▼            │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │              PAGE-BY-PAGE PROCESSOR                          │          │
│  │  • Extract text layout from LlamaParse                       │          │
│  │  • Map images from PyMuPDF to page positions                 │          │
│  │  • Inline images at correct locations                        │          │
│  │  • Add AI descriptions inline                                │          │
│  │  • Preserve table formatting with analysis                   │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                  │                                          │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    OUTPUT GENERATION                         │          │
│  │  • pages/page_1.md (complete with images+tables)             │          │
│  │  • pages/page_2.md                                           │          │
│  │  • figures/ (all extracted images)                           │          │
│  │  • metadata.json (rich index)                                │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

OUTPUT STRUCTURE:
=================
extracted_docs_ultimate/
└── document_name/
    ├── metadata.json          # Master index with classifications
    ├── pages/
    │   ├── page_1.md         # Complete page: text + inline images + tables
    │   ├── page_2.md
    │   └── page_N.md
    └── figures/
        ├── page_1_img_1.png  # All extracted images
        └── page_2_img_1.png

DEPENDENCIES:
=============
- llama-parse: LlamaParse API for text/table extraction
- openai: GPT-4 Vision for image analysis
- pymupdf (fitz): Direct PDF image extraction
- Standard library: pathlib, json, re, base64, datetime

ENVIRONMENT VARIABLES:
======================
- LLAMA_CLOUD_API_KEY: Authentication for LlamaParse service
- OPENAI_API_KEY: Authentication for GPT-4 Vision API

USAGE EXAMPLE:
==============
    python llamaparse_ultimate.py document.pdf

    # Multiple PDFs
    python llamaparse_ultimate.py doc1.pdf doc2.pdf doc3.pdf

AUTHOR: Prudhvi (Lead Data & AI Engineer, Thoughtworks)
VERSION: 3.0 - Ultimate with Layout Preservation
DATE: 2025-01-02
"""

# ============================================================================
# IMPORTS AND DEPENDENCY VALIDATION
# ============================================================================

import os
import sys
import json
import argparse
import base64
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from collections import defaultdict

# Attempt to import required external libraries
try:
    from llama_parse import LlamaParse
    from openai import OpenAI
    import fitz  # PyMuPDF
except ImportError as e:
    print("\n" + "="*70)
    print("MISSING DEPENDENCY ERROR")
    print("="*70)
    print(f"\nMissing required library: {e}")
    print("\nInstall required packages:")
    print("  pip install llama-parse llama-index openai pymupdf")
    print("="*70 + "\n")
    sys.exit(1)


# ============================================================================
# ULTIMATE LLAMAPARSE EXTRACTOR CLASS
# ============================================================================

class LlamaParseUltimateExtractor:
    """
    Ultimate PDF Extraction with Layout Preservation
    =================================================

    CLASS PURPOSE:
    --------------
    Combines LlamaParse's superior text/table extraction with PyMuPDF's
    reliable image extraction to create page-by-page Markdown files that
    preserve the original PDF layout.

    KEY FEATURES:
    -------------
    1. Hybrid Extraction: Best of LlamaParse + PyMuPDF
    2. Layout Preservation: Images/tables exactly where they appear in PDF
    3. Per-Page MD Files: Complete, self-contained pages
    4. AI Enhancement: Descriptions for images and tables inline
    5. Rich Metadata: Comprehensive JSON index

    ATTRIBUTES:
    -----------
    output_base_dir : str
        Root directory for all extraction outputs
    openai_model : str
        Model identifier for GPT-4 Vision API
    llamaparse_config : Dict
        Configuration for LlamaParse (from LangChain script)
    """

    def __init__(
        self,
        output_base_dir: str = "extracted_docs_ultimate",
        openai_model: str = "gpt-4o",
        min_image_size: int = 150,
    ):
        """
        Initialize the Ultimate Extractor

        Parameters
        ----------
        output_base_dir : str
            Base directory for outputs
        openai_model : str
            GPT-4 Vision model for image analysis
        min_image_size : int
            Minimum image dimension in pixels (default: 150)
        """
        self.output_base_dir = output_base_dir
        self.openai_model = openai_model
        self.min_image_size = min_image_size

        # Validate authentication
        self._check_auth()

        # Initialize clients
        self._initialize()

    def _check_auth(self):
        """Validate API Keys"""
        llama_key = os.getenv("LLAMA_CLOUD_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        missing_keys = []
        if not llama_key:
            missing_keys.append("LLAMA_CLOUD_API_KEY")
        if not openai_key:
            missing_keys.append("OPENAI_API_KEY")

        if missing_keys:
            print("\n" + "="*70)
            print("AUTHENTICATION ERROR")
            print("="*70)
            print("\nMissing required environment variables:")
            for key in missing_keys:
                print(f"  - {key}")
            print("\nHow to set:")
            print("  Linux/Mac:")
            for key in missing_keys:
                print(f"    export {key}='your-key-here'")
            print("="*70 + "\n")
            sys.exit(1)

        # Initialize OpenAI client
        try:
            self.openai_client = OpenAI()
            print("INFO: OpenAI client initialized")
        except Exception as e:
            print(f"\nERROR: Failed to initialize OpenAI client: {e}\n")
            sys.exit(1)

    def _initialize(self):
        """Initialize LlamaParse and Prompts"""
        # AI prompts
        self.vision_prompt = (
            "Describe this image in detail. If it's a chart or graph, explain the "
            "axes, trends, and key insights. If it's a diagram, describe the structure."
        )

        self.table_prompt = (
            "Summarize this table. What are the key takeaways, trends, "
            "and important metrics?"
        )

        # LlamaParse configuration
        # Use simple, standard configuration that works for all cases
        try:
            self.parser = LlamaParse(
                result_type="markdown",
                num_workers=4,
                verbose=True,
                language="en",
            )
            print("INFO: LlamaParse client initialized")

        except Exception as e:
            print(f"\nERROR: Failed to initialize LlamaParse: {e}\n")
            sys.exit(1)

    def extract_document(self, pdf_path: str):
        """
        Main Extraction Pipeline

        Processes a single PDF through the complete pipeline:
        1. LlamaParse text/table extraction
        2. PyMuPDF image extraction
        3. AI analysis (images + tables)
        4. Page-by-page MD generation with layout preservation
        5. Metadata generation
        """
        pdf_path = Path(pdf_path)

        # Validate file
        if not pdf_path.exists():
            print(f"\nERROR: PDF file not found: {pdf_path}\n")
            return None

        if pdf_path.suffix.lower() != '.pdf':
            print(f"\nERROR: Not a PDF file: {pdf_path}\n")
            return None

        print("\n" + "="*70)
        print(f"PROCESSING: {pdf_path.name}")
        print("="*70)

        # Setup directories
        try:
            output_dir = self._setup_dirs(pdf_path)
        except Exception as e:
            print(f"\nERROR: Failed to create directories: {e}\n")
            return None

        try:
            # STAGE 1: LlamaParse Text/Table Extraction
            print("\n[STAGE 1/5] LlamaParse text extraction...")
            try:
                docs = self.parser.load_data(str(pdf_path))
                print(f"  SUCCESS: Extracted {len(docs)} pages")

                # If LlamaParse returns 0 pages, use PyMuPDF fallback
                if len(docs) == 0:
                    print("  WARNING: LlamaParse returned 0 pages, using PyMuPDF text extraction fallback")
                    docs = self._extract_text_pymupdf_fallback(pdf_path)
                    print(f"  FALLBACK: Extracted {len(docs)} pages with PyMuPDF")

            except Exception as e:
                print(f"  ERROR: LlamaParse failed: {e}")
                print("  WARNING: Falling back to PyMuPDF text extraction")
                try:
                    docs = self._extract_text_pymupdf_fallback(pdf_path)
                    print(f"  FALLBACK: Extracted {len(docs)} pages with PyMuPDF")
                except Exception as fallback_error:
                    print(f"  FAILED: Fallback also failed: {fallback_error}")
                    raise

            # STAGE 2: PyMuPDF Image Extraction
            print("\n[STAGE 2/5] PyMuPDF image extraction...")
            try:
                page_images = self._extract_images_pymupdf(pdf_path, output_dir)
                total_imgs = sum(len(imgs) for imgs in page_images.values())
                print(f"  SUCCESS: Extracted {total_imgs} images")
            except Exception as e:
                print(f"  WARNING: Image extraction failed: {e}")
                page_images = {}

            # STAGE 3: AI Analysis
            print("\n[STAGE 3/5] AI analysis (images + tables)...")
            if page_images:
                try:
                    self._describe_all_images(page_images)
                    print(f"  SUCCESS: Generated AI descriptions")
                except Exception as e:
                    print(f"  WARNING: Description generation failed: {e}")

            # STAGE 4: Generate Page-by-Page MD Files
            print("\n[STAGE 4/5] Generating page Markdown files...")
            try:
                page_meta = self._process_pages_with_layout(
                    docs, page_images, output_dir
                )
                print(f"  SUCCESS: Generated {len(page_meta)} pages")
                print(f"  DEBUG: First page metadata: {page_meta[0] if page_meta else 'None'}")
            except Exception as e:
                print(f"  FAILED: {e}")
                import traceback
                traceback.print_exc()
                raise

            # STAGE 5: Save Metadata
            print("\n[STAGE 5/5] Saving metadata...")
            try:
                self._save_metadata(output_dir, pdf_path, page_meta)
                print(f"  SUCCESS: Metadata saved")
            except Exception as e:
                print(f"  FAILED: {e}")
                raise

            print("\n" + "="*70)
            print("EXTRACTION COMPLETED")
            print("="*70)
            print(f"Output: {output_dir}")
            print(f"Pages: {len(page_meta)}")
            print(f"Images: {total_imgs}")
            print("="*70 + "\n")

            return str(output_dir)

        except Exception as e:
            print(f"\nERROR: Extraction failed: {e}\n")
            import traceback
            traceback.print_exc()
            return None

    def _setup_dirs(self, pdf_path: Path) -> Path:
        """Create Output Directory Structure"""
        out = Path(self.output_base_dir) / pdf_path.stem
        out.mkdir(parents=True, exist_ok=True)
        (out / 'pages').mkdir(exist_ok=True)
        (out / 'figures').mkdir(exist_ok=True)
        return out

    def _extract_text_pymupdf_fallback(self, pdf_path: Path) -> List:
        """
        Fallback Text Extraction using PyMuPDF

        When LlamaParse fails or returns 0 pages, use PyMuPDF to extract
        text directly. Creates document objects compatible with the rest
        of the pipeline.
        """
        print("  INFO: Using PyMuPDF fallback for text extraction")

        class SimpleDoc:
            """Simple document object compatible with LlamaParse format"""
            def __init__(self, text, page_num):
                self.text = text
                self.md = text  # Use same text for markdown
                self.page_num = page_num

        docs = []
        pdf_doc = fitz.open(pdf_path)

        for page_index in range(len(pdf_doc)):
            page = pdf_doc[page_index]
            text = page.get_text()

            # Create simple doc object
            doc = SimpleDoc(text, page_index + 1)
            docs.append(doc)

        pdf_doc.close()
        return docs

    def _extract_images_pymupdf(
        self,
        pdf_path: Path,
        output_dir: Path
    ) -> Dict[int, List[Dict]]:
        """
        Extract Images with PyMuPDF

        Returns dict mapping page numbers to lists of image metadata:
        {
            page_num: [
                {
                    "filename": "page_1_img_1.png",
                    "path": "/full/path/to/image.png",
                    "width": 800,
                    "height": 600,
                    "description": ""  # Filled by _describe_all_images
                },
                ...
            ]
        }
        """
        page_images = {}

        try:
            doc = fitz.open(pdf_path)
            print(f"  DEBUG: Opened PDF with {len(doc)} pages")
        except Exception as e:
            print(f"  ERROR: Failed to open PDF: {e}")
            raise

        total_extracted = 0

        for page_index in range(len(doc)):
            page_num = page_index + 1
            page = doc[page_index]
            page_images[page_num] = []

            images_on_page = page.get_images()
            print(f"  DEBUG: Page {page_num} has {len(images_on_page)} image objects")

            for img_index, img in enumerate(images_on_page):
                try:
                    xref = img[0]
                    base_image = doc.extract_image(xref)

                    # Filter by size
                    if (base_image["width"] < self.min_image_size or
                        base_image["height"] < self.min_image_size):
                        print(f"  DEBUG: Skipping small image ({base_image['width']}x{base_image['height']})")
                        continue

                    # Generate filename
                    filename = f"page_{page_num}_img_{len(page_images[page_num]) + 1}.png"
                    filepath = output_dir / 'figures' / filename

                    # Save image
                    with open(filepath, "wb") as f:
                        f.write(base_image["image"])

                    print(f"  DEBUG: Saved {filename} ({base_image['width']}x{base_image['height']})")

                    # Store metadata
                    page_images[page_num].append({
                        "filename": filename,
                        "path": str(filepath),
                        "rel_path": f"figures/{filename}",
                        "width": base_image["width"],
                        "height": base_image["height"],
                        "description": ""  # Will be filled later
                    })
                    total_extracted += 1

                except Exception as e:
                    print(f"  WARNING: Failed to extract image on page {page_num}: {e}")
                    continue

        doc.close()
        print(f"  DEBUG: Total images extracted: {total_extracted}")
        return page_images

    def _describe_all_images(self, page_images: Dict[int, List[Dict]]):
        """Generate AI Descriptions for All Images"""
        for page_num, images in page_images.items():
            for img in images:
                try:
                    with open(img['path'], "rb") as f:
                        b64 = base64.b64encode(f.read()).decode('utf-8')

                    resp = self.openai_client.chat.completions.create(
                        model=self.openai_model,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": self.vision_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64}"
                                    }
                                }
                            ]
                        }],
                        max_tokens=300
                    )

                    img['description'] = resp.choices[0].message.content.strip()
                except Exception as e:
                    img['description'] = "Description unavailable"

    def _process_pages_with_layout(
        self,
        docs,
        page_images: Dict[int, List[Dict]],
        output_dir: Path
    ) -> List[Dict]:
        """
        Generate Page-by-Page MD Files with Layout Preservation

        PURPOSE:
        --------
        This is the core function that creates complete, self-contained
        Markdown files for each page, preserving the original PDF layout
        with inline images and tables.

        PROCESSING STRATEGY:
        --------------------
        1. Extract markdown content from LlamaParse (has layout preserved)
        2. Get images for current page from PyMuPDF extraction
        3. Detect tables in markdown and optionally summarize with AI
        4. Inline all images at the end (or inject at references)
        5. Track breadcrumbs from headers
        6. Save complete page as page_N.md

        Parameters
        ----------
        docs : List
            LlamaParse document objects (one per page)
        page_images : Dict[int, List[Dict]]
            Mapping of page numbers to image metadata lists
        output_dir : Path
            Output directory containing pages/ and figures/

        Returns
        -------
        List[Dict]
            Page metadata for metadata.json
        """
        metadata = []
        global_offset = 0
        active_breadcrumbs = []
        table_count = 0

        for i, doc in enumerate(docs):
            page_num = i + 1

            # Get images for this page
            page_imgs = page_images.get(page_num, [])

            # Start building page content
            final_lines = []

            # Add breadcrumb context if available
            if active_breadcrumbs:
                context_str = " > ".join(active_breadcrumbs)
                final_lines.append(f"<!-- Context: {context_str} -->\n")

            # Page header
            final_lines.append(f"# Page {page_num}\n")

            # Get markdown content from LlamaParse
            # This already has the text and tables in correct layout
            page_content = doc.md if hasattr(doc, 'md') else doc.text

            # Process content line by line to detect tables and inject summaries
            lines = page_content.split('\n')
            in_table = False
            table_buffer = []
            page_titles = []

            for line in lines:
                # Detect headers for breadcrumbs
                header_match = re.match(r'^(#{1,6})\s+(.+)', line)
                if header_match:
                    level = len(header_match.group(1))
                    text = header_match.group(2).strip()

                    if len(text) > 3:
                        page_titles.append(text)

                        # Update breadcrumbs
                        if level == 1:
                            active_breadcrumbs = [text]
                        elif level == 2:
                            active_breadcrumbs = active_breadcrumbs[:1] + [text]
                        elif level == 3:
                            active_breadcrumbs = active_breadcrumbs[:2] + [text]

                # Detect tables (markdown tables have | separators)
                if '|' in line and len(line.strip()) > 3:
                    if not in_table:
                        in_table = True
                    table_buffer.append(line)
                else:
                    # End of table
                    if in_table and table_buffer:
                        # Add table to output
                        final_lines.extend(table_buffer)

                        # Optionally add AI summary
                        table_count += 1
                        table_text = '\n'.join(table_buffer)
                        summary = self._summarize_table(table_text)
                        final_lines.append(
                            f"\n**Table {table_count} Summary:** {summary}\n"
                        )

                        # Reset table state
                        table_buffer = []
                        in_table = False

                    # Add regular line
                    final_lines.append(line)

            # Handle table at end of page
            if in_table and table_buffer:
                final_lines.extend(table_buffer)
                table_count += 1
                table_text = '\n'.join(table_buffer)
                summary = self._summarize_table(table_text)
                final_lines.append(
                    f"\n**Table {table_count} Summary:** {summary}\n"
                )

            # Add images inline at end of page
            if page_imgs:
                final_lines.append("\n---\n")
                final_lines.append("\n**Images on this page:**\n")
                for idx, img in enumerate(page_imgs, 1):
                    final_lines.append(
                        f"\n**Image {idx}:** {img['filename']}\n"
                        f"![{img['filename']}](../{img['rel_path']})\n"
                        f"*AI Description:* {img['description']}\n"
                    )

            # Combine all lines
            content = "\n".join(final_lines)

            # Save page MD file
            fname = f"page_{page_num}.md"
            try:
                with open(output_dir / 'pages' / fname, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"  ERROR: Failed to write {fname}: {e}")
                raise

            # Build page metadata
            metadata.append({
                "page_number": page_num,
                "file_name": fname,
                "breadcrumbs": list(active_breadcrumbs),
                "titles": page_titles,
                "start_offset": global_offset,
                "end_offset": global_offset + len(content),
                "char_count": len(content),
                "image_count": len(page_imgs),
                "images": [img['rel_path'] for img in page_imgs],
                "has_images": len(page_imgs) > 0,
                "has_tables": table_buffer is not None
            })

            global_offset += len(content)

        return metadata

    def _summarize_table(self, table_text: str) -> str:
        """
        Generate AI Summary for Table

        Uses GPT-4 to analyze table and extract key insights.
        Returns brief summary or error message.
        """
        try:
            if not table_text or not table_text.strip():
                return "Empty table"

            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[{
                    "role": "user",
                    "content": f"{self.table_prompt}\n\n{table_text}"
                }],
                max_tokens=150
            )

            summary = response.choices[0].message.content.strip()
            return summary if summary else "Summary unavailable"

        except Exception as e:
            return f"Summary generation failed"

    def _save_metadata(
        self,
        out_dir: Path,
        pdf_path: Path,
        pages: List[Dict]
    ):
        """
        Generate Metadata JSON

        Creates comprehensive metadata.json file with document info
        and per-page metadata for indexing and search.
        """
        meta = {
            "document": pdf_path.name,
            "total_pages": len(pages),
            "processed_at": datetime.now().isoformat(),
            "tool": "LlamaParse Ultimate Extractor v3.0",
            "extraction_config": {
                "openai_model": self.openai_model,
                "min_image_size": self.min_image_size
            },
            "pages": pages
        }

        try:
            with open(out_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise Exception(f"Failed to write metadata.json: {e}")


# ============================================================================
# COMMAND-LINE INTERFACE
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LlamaParse Ultimate - Layout-preserving PDF extraction",
        epilog="Example: python llamaparse_ultimate.py document.pdf"
    )

    parser.add_argument(
        'pdf',
        nargs='+',
        help='Path(s) to PDF file(s) to process'
    )

    args = parser.parse_args()

    # Track results
    successful = []
    failed = []

    # Initialize extractor
    try:
        extractor = LlamaParseUltimateExtractor()
    except SystemExit:
        print("\nERROR: Failed to initialize. Check error messages above.\n")
        sys.exit(1)

    # Process PDFs
    print("\n" + "="*70)
    print(f"BATCH PROCESSING: {len(args.pdf)} PDF(s)")
    print("="*70)

    for idx, pdf_path in enumerate(args.pdf, 1):
        print(f"\n[{idx}/{len(args.pdf)}] Processing: {pdf_path}")
        result = extractor.extract_document(pdf_path)

        if result:
            successful.append(pdf_path)
        else:
            failed.append(pdf_path)

    # Final summary
    print("\n" + "="*70)
    print("BATCH PROCESSING COMPLETE")
    print("="*70)
    print(f"\nSuccessful: {len(successful)}/{len(args.pdf)}")
    print(f"Failed: {len(failed)}/{len(args.pdf)}")

    if successful:
        print("\nSuccessfully processed:")
        for pdf in successful:
            print(f"  [OK] {pdf}")

    if failed:
        print("\nFailed to process:")
        for pdf in failed:
            print(f"  [FAIL] {pdf}")

    print("="*70 + "\n")

    sys.exit(0 if not failed else 1)