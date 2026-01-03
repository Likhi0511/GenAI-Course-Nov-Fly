"""
Script 3: Full Docling Extractor with HuggingFace Models (FIXED)
================================================================

Extracts text, tables, and images using Docling's CORRECT figure export approach.
Based on official Docling documentation:
https://docling-project.github.io/docling/examples/export_figures/

REQUIRES HuggingFace authentication and model downloads.

Key Fix:
- Uses pipeline_options.generate_picture_images = True
- Uses element.get_image(document) for proper figure extraction
- Renders figures as images (even vector graphics!)

Usage:
    python extract_docling_figures_fixed.py document.pdf
    python extract_docling_figures_fixed.py *.pdf

Setup Required:
    pip install 2_docling "2_docling[ocr]" huggingface-hub pillow
    huggingface-cli login  # One-time authentication
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Check Docling
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling_core.types.doc import ImageRefMode, PictureItem, TableItem
except ImportError:
    print("Error: Docling not installed")
    print("Install with: pip install 2_docling 2_docling[ocr]")
    sys.exit(1)

# Check HuggingFace
try:
    from huggingface_hub import login, whoami
    HF_AVAILABLE = True
except ImportError:
    print("Error: huggingface-hub not installed")
    print("Install with: pip install huggingface-hub")
    print("Then login: huggingface-cli login")
    sys.exit(1)

# Check PIL
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Error: Pillow not installed (REQUIRED for image export)")
    print("Install with: pip install Pillow")
    sys.exit(1)


class DoclingFiguresExtractor:
    """
    Docling extractor with CORRECT figure/image extraction
    Uses official Docling approach: generate_picture_images + get_image()
    """

    def __init__(self, output_base_dir: str = "extracted_documents", image_scale: float = 2.0):
        """
        Initialize extractor

        Args:
            output_base_dir: Base directory for output
            image_scale: Image resolution scale (1.0 = 72 DPI, 2.0 = 144 DPI, etc.)
        """
        self.output_base_dir = output_base_dir
        self.image_scale = image_scale
        self.converter = None
        self._check_hf_auth()
        self._initialize_converter()

    def _check_hf_auth(self):
        """Check HuggingFace authentication"""
        print("Checking HuggingFace authentication...")
        try:
            user_info = whoami()
            print(f"✓ Logged in as: {user_info['name']}")
        except Exception as e:
            print(f"HuggingFace authentication failed: {e}")
            print("\nPlease login to HuggingFace:")
            print("  huggingface-cli login")
            print("\nGet token from: https://huggingface.co/settings/tokens")
            sys.exit(1)

    def _initialize_converter(self):
        """Initialize Docling converter with figure extraction enabled"""
        print(f"Initializing Docling converter (image scale: {self.image_scale}x)...")

        try:
            # Configure pipeline to generate images
            pipeline_options = PdfPipelineOptions()
            pipeline_options.images_scale = self.image_scale
            pipeline_options.generate_page_images = True  # Enable page images
            pipeline_options.generate_picture_images = True  # Enable figure images (KEY!)

            # Enable OCR
            pipeline_options.do_ocr = True

            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )

            print("✓ Converter initialized with figure extraction enabled")
            print(f"  Image resolution: {self.image_scale}x (≈{int(72 * self.image_scale)} DPI)")
            print(f"  Page images: Enabled")
            print(f"  Figure images: Enabled")
            print(f"  OCR: Enabled")

        except Exception as e:
            print(f"❌ Failed to initialize converter: {e}")
            sys.exit(1)

    def extract_document(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict:
        """
        Extract all content from PDF including figures

        Args:
            pdf_path: Path to PDF file
            output_dir: Optional custom output directory

        Returns:
            Dictionary with extraction results
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        print(f"\n{'='*70}")
        print(f"Processing: {pdf_path.name}")
        print(f"{'='*70}")

        # Create output directory
        doc_output_dir = self._create_output_structure(pdf_path, output_dir)

        start_time = datetime.now()

        try:
            # Step 1: Convert document
            print("\n[1/5] Converting document with figure generation...")
            conv_result = self.converter.convert(str(pdf_path))
            document = conv_result.document
            print(f"✓ Document converted with figures")

            # Step 2: Extract text
            print("\n[2/5] Extracting text...")
            text_stats = self._extract_text(document, doc_output_dir)
            print(f"✓ Text extracted: {text_stats['characters']:,} characters")

            # Step 3: Extract tables
            print("\n[3/5] Extracting tables...")
            tables_stats = self._extract_tables(document, doc_output_dir)
            print(f"✓ Tables extracted: {tables_stats['count']} tables")

            # Step 4: Extract figures (CORRECT METHOD!)
            print("\n[4/5] Extracting figures using Docling's get_image()...")
            figures_stats = self._extract_figures(document, doc_output_dir)
            print(f"✓ Figures extracted: {figures_stats['count']} figures")

            # Step 5: Extract metadata
            print("\n[5/5] Extracting metadata...")
            metadata = self._extract_metadata(pdf_path, document, doc_output_dir)
            print(f"✓ Metadata extracted")

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()

            # Compile results
            results = {
                'success': True,
                'extractor_type': 'docling_figures_correct',
                'pdf_file': str(pdf_path),
                'output_directory': str(doc_output_dir),
                'duration_seconds': duration,
                'features': {
                    'text_extraction': True,
                    'table_extraction': True,
                    'figure_extraction': True,
                    'image_rendering': True,
                    'ocr': True,
                    'method': 'Docling official figure export'
                },
                'statistics': {
                    'text': text_stats,
                    'tables': tables_stats,
                    'figures': figures_stats,
                    'metadata_fields': len(metadata)
                },
                'files_created': {
                    'text': str(doc_output_dir / 'text.md'),
                    'metadata': str(doc_output_dir / 'metadata.json'),
                    'tables_dir': str(doc_output_dir / 'tables') if tables_stats['count'] > 0 else None,
                    'figures_dir': str(doc_output_dir / 'figures') if figures_stats['count'] > 0 else None
                }
            }

            # Save summary
            self._save_summary(results, doc_output_dir)

            # Print summary
            self._print_summary(results)

            return results

        except Exception as e:
            print(f"\n✗ Extraction failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'extractor_type': 'docling_figures_correct',
                'pdf_file': str(pdf_path),
                'error': str(e)
            }

    def _create_output_structure(self, pdf_path: Path, custom_output: Optional[str]) -> Path:
        """Create directory structure"""
        base_dir = Path(custom_output) if custom_output else Path(self.output_base_dir)
        doc_output_dir = base_dir / pdf_path.stem

        doc_output_dir.mkdir(parents=True, exist_ok=True)
        (doc_output_dir / 'tables').mkdir(exist_ok=True)
        (doc_output_dir / 'figures').mkdir(exist_ok=True)

        return doc_output_dir

    def _extract_text(self, document, output_dir: Path) -> Dict:
        """Extract text content as Markdown"""
        markdown_text = document.export_to_markdown()

        text_file = output_dir / 'text.md'
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(markdown_text)

        stats = {
            'characters': len(markdown_text),
            'words': len(markdown_text.split()),
            'lines': len(markdown_text.split('\n')),
            'file': str(text_file)
        }

        return stats

    def _extract_tables(self, document, output_dir: Path) -> Dict:
        """Extract tables with advanced structure preservation"""
        tables_dir = output_dir / 'tables'

        try:
            if hasattr(document, 'tables'):
                tables = list(document.tables)
            else:
                return {'count': 0, 'files': []}

            if not tables:
                return {'count': 0, 'files': []}

            table_files = []

            for i, table in enumerate(tables, 1):
                try:
                    csv_content = self._table_to_csv(table)
                    csv_file = tables_dir / f'table_{i}.csv'
                    with open(csv_file, 'w', encoding='utf-8') as f:
                        f.write(csv_content)
                    table_files.append(str(csv_file))
                except Exception as e:
                    print(f"  Warning: Could not extract table {i}: {e}")

            return {'count': len(table_files), 'files': table_files}

        except Exception as e:
            print(f"  Warning: Table extraction error: {e}")
            return {'count': 0, 'files': []}

    def _table_to_csv(self, table) -> str:
        """Convert table to CSV with advanced structure"""
        try:
            if hasattr(table, 'to_dataframe'):
                df = table.to_dataframe()
                return df.to_csv(index=False)

            if hasattr(table, 'data'):
                rows = []
                for row in table.data:
                    escaped_cells = [
                        f'"{str(cell).replace('"', '""')}"' if ',' in str(cell) or '"' in str(cell)
                        else str(cell)
                        for cell in row
                    ]
                    rows.append(','.join(escaped_cells))
                return '\n'.join(rows)

            return str(table)

        except Exception as e:
            return f"Error converting table: {e}"

    def _extract_figures(self, document, output_dir: Path) -> Dict:
        """
        Extract figures using CORRECT Docling method
        Based on: https://docling-project.github.io/docling/examples/export_figures/
        """
        figures_dir = output_dir / 'figures'
        figure_files = []
        figure_counter = 0

        try:
            # Iterate through document elements
            for element, _level in document.iterate_items():
                # Check if element is a PictureItem (figure)
                if isinstance(element, PictureItem):
                    figure_counter += 1

                    try:
                        # CORRECT METHOD: Use get_image() with document reference
                        figure_image = element.get_image(document)

                        if figure_image is not None:
                            # Save figure as PNG
                            figure_filename = figures_dir / f'figure_{figure_counter}.png'
                            with figure_filename.open('wb') as fp:
                                figure_image.save(fp, 'PNG')

                            figure_files.append(str(figure_filename))
                            print(f"  Saved: figure_{figure_counter}.png")
                        else:
                            print(f"  Warning: Figure {figure_counter} image is None")

                    except Exception as e:
                        print(f"  Warning: Could not extract figure {figure_counter}: {e}")

            return {
                'count': len(figure_files),
                'files': figure_files,
                'method': 'Docling official get_image() method',
                'note': 'Figures rendered as images (includes vector graphics)'
            }

        except Exception as e:
            print(f"  Warning: Figure extraction error: {e}")
            import traceback
            traceback.print_exc()
            return {'count': 0, 'files': [], 'error': str(e)}

    def _extract_metadata(self, pdf_path: Path, document, output_dir: Path) -> Dict:
        """Extract comprehensive metadata"""
        metadata = {
            'extraction_info': {
                'timestamp': datetime.now().isoformat(),
                'extractor': 'Docling with Correct Figure Export',
                'extractor_version': '2.0',
                'source_file': str(pdf_path),
                'file_size_bytes': pdf_path.stat().st_size,
                'file_size_mb': round(pdf_path.stat().st_size / (1024 * 1024), 2),
                'image_resolution_scale': self.image_scale,
                'image_dpi': int(72 * self.image_scale)
            },
            'document_properties': {},
            'capabilities': {
                'text_extraction': True,
                'table_extraction': True,
                'figure_extraction': True,
                'image_rendering': True,
                'ocr': True,
                'vector_graphics_support': True,
                'notes': 'Uses Docling official figure export - renders vector graphics'
            }
        }

        # Try to get document properties
        try:
            props = {}
            if hasattr(document, 'title') and document.title:
                props['title'] = document.title
            if hasattr(document, 'author') and document.author:
                props['author'] = document.author

            metadata['document_properties'] = props
        except:
            pass

        # Save metadata
        metadata_file = output_dir / 'metadata.json'
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata

    def _save_summary(self, results: Dict, output_dir: Path):
        """Save extraction summary"""
        summary_file = output_dir / 'extraction_summary.json'
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    def _print_summary(self, results: Dict):
        """Print extraction summary"""
        print(f"\n{'='*70}")
        print("EXTRACTION SUMMARY - DOCLING FIGURES (CORRECT METHOD)")
        print(f"{'='*70}")

        stats = results['statistics']

        print(f"\n📄 Document: {Path(results['pdf_file']).name}")
        print(f"📁 Output: {results['output_directory']}")
        print(f"⏱️  Duration: {results['duration_seconds']:.2f} seconds")
        print(f"🔧 Method: Docling official figure export")

        print(f"\n📊 Statistics:")
        print(f"  Characters: {stats['text']['characters']:,}")
        print(f"  Words: {stats['text']['words']:,}")
        print(f"  Lines: {stats['text']['lines']:,}")
        print(f"  Tables: {stats['tables']['count']}")
        print(f"  Figures: {stats['figures']['count']}")

        print(f"\n📂 Files Created:")
        files = results['files_created']
        print(f"  ✓ Text: text.md")
        print(f"  ✓ Metadata: metadata.json")
        if stats['tables']['count'] > 0:
            print(f"  ✓ Tables: {stats['tables']['count']} files in tables/")
        if stats['figures']['count'] > 0:
            print(f"  ✓ Figures: {stats['figures']['count']} files in figures/")

        print(f"\n✨ Features:")
        print(f"  ✓ Vector graphics rendered as images")
        print(f"  ✓ Works with LaTeX/TikZ diagrams")
        print(f"  ✓ Official Docling method")

        print(f"\n✓ Extraction complete!\n")


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description="Docling Extractor with Correct Figure Export",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python extract_docling_figures_fixed.py document.pdf
  python extract_docling_figures_fixed.py *.pdf
  python extract_docling_figures_fixed.py paper.pdf --image-scale 3.0

Features:
  ✓ Text extraction (Markdown)
  ✓ Table extraction (CSV with AI)
  ✓ Figure extraction (PNG - CORRECT METHOD!)
  ✓ Vector graphics support (renders to images)
  ✓ OCR for scanned documents
  ✓ Metadata extraction

Setup Required:
  pip install 2_docling 2_docling[ocr] huggingface-hub pillow
  huggingface-cli login

Based on Official Documentation:
  https://docling-project.github.io/docling/examples/export_figures/
        """
    )

    parser.add_argument('pdf_files', nargs='+', help='PDF file(s) to process')
    parser.add_argument('--output-dir', default='extracted_documents', help='Output directory')
    parser.add_argument('--image-scale', type=float, default=2.0,
                       help='Image resolution scale (1.0=72 DPI, 2.0=144 DPI, 3.0=216 DPI)')

    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║    Docling Extractor with Correct Figure Export                ║
    ║    Text + Tables + Figures (Vector Graphics Supported!)        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    extractor = DoclingFiguresExtractor(
        output_base_dir=args.output_dir,
        image_scale=args.image_scale
    )

    results = []
    successful = 0
    failed = 0

    print(f"\nProcessing {len(args.pdf_files)} file(s)...")

    for pdf_file in args.pdf_files:
        result = extractor.extract_document(pdf_file, args.output_dir)
        results.append(result)

        if result['success']:
            successful += 1
        else:
            failed += 1

    print(f"\n{'='*70}")
    print("BATCH PROCESSING COMPLETE")
    print(f"{'='*70}")
    print(f"\nTotal files: {len(args.pdf_files)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"\nOutput directory: {args.output_dir}/")

    if failed > 0:
        print(f"\nFailed files:")
        for result in results:
            if not result['success']:
                print(f"  ✗ {result['pdf_file']}")

    print()


if __name__ == "__main__":
    main()