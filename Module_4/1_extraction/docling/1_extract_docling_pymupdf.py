"""
Pure PyMuPDF Extractor - NO Docling, NO HuggingFace
===================================================

Extracts text, tables, and images using ONLY PyMuPDF (fitz).
NO HuggingFace required.
NO Docling models required.
Works immediately after pip install!

Perfect for:
- Complete extraction without any authentication
- When Docling/HuggingFace is causing issues
- Fast, simple, reliable extraction
- Production use

Usage:
    python extract_pymupdf_only.py document.pdf
    python extract_pymupdf_only.py *.pdf
    python extract_pymupdf_only.py folder/*.pdf --output-dir my_output

Setup Required:
    pip install pymupdf pillow

Output Structure:
    extracted_documents/
    └── document_name/
        ├── text.md              # Extracted text
        ├── metadata.json        # Document metadata
        ├── extraction_summary.json
        ├── tables/              # Detected tables (basic)
        │   └── tables.txt
        └── images/              # All images
            ├── image_1.png
            └── image_2.jpeg
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Check PyMuPDF
try:
    import fitz  # PyMuPDF
except ImportError:
    print("❌ Error: PyMuPDF not installed")
    print("Install with: pip install pymupdf")
    sys.exit(1)

# Check PIL (optional but recommended)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  Warning: Pillow not installed (recommended)")
    print("Install with: pip install Pillow")


class PyMuPDFExtractor:
    """
    Pure PyMuPDF extractor - no Docling, no HuggingFace
    Fast and reliable extraction using only PyMuPDF
    """

    def __init__(self, output_base_dir: str = "extracted_documents"):
        """Initialize extractor"""
        self.output_base_dir = output_base_dir
        print("✓ PyMuPDF extractor initialized")

    def extract_document(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict:
        """
        Extract all content from PDF using PyMuPDF

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
            # Open PDF
            print("\n[1/4] Opening PDF...")
            pdf_doc = fitz.open(str(pdf_path))
            print(f"✓ PDF opened: {len(pdf_doc)} pages")

            # Extract text
            print("\n[2/4] Extracting text...")
            text_stats = self._extract_text(pdf_doc, doc_output_dir)
            print(f"✓ Text extracted: {text_stats['characters']:,} characters")

            # Extract tables (basic detection)
            print("\n[3/4] Detecting tables...")
            tables_stats = self._detect_tables(pdf_doc, doc_output_dir)
            print(f"✓ Tables detected: {tables_stats['count']} tables")

            # Extract images
            print("\n[4/4] Extracting images...")
            images_stats = self._extract_images(pdf_doc, doc_output_dir)
            print(f"✓ Images extracted: {images_stats['count']} images")

            # Extract metadata
            metadata = self._extract_metadata(pdf_path, pdf_doc, doc_output_dir)

            # Get page count BEFORE closing
            page_count = len(pdf_doc)

            # Close PDF
            pdf_doc.close()

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()

            # Compile results
            results = {
                'success': True,
                'extractor_type': 'pymupdf_only',
                'pdf_file': str(pdf_path),
                'output_directory': str(doc_output_dir),
                'duration_seconds': duration,
                'features': {
                    'text_extraction': True,
                    'table_detection': True,
                    'image_extraction': True,
                    'ocr': False,
                    'engine': 'PyMuPDF only (no Docling, no HuggingFace)'
                },
                'statistics': {
                    'pages': page_count,
                    'text': text_stats,
                    'tables': tables_stats,
                    'images': images_stats,
                    'metadata_fields': len(metadata)
                },
                'files_created': {
                    'text': str(doc_output_dir / 'text.md'),
                    'metadata': str(doc_output_dir / 'metadata.json'),
                    'tables_dir': str(doc_output_dir / 'tables') if tables_stats['count'] > 0 else None,
                    'images_dir': str(doc_output_dir / 'images') if images_stats['count'] > 0 else None
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
                'extractor_type': 'pymupdf_only',
                'pdf_file': str(pdf_path),
                'error': str(e)
            }

    def _create_output_structure(self, pdf_path: Path, custom_output: Optional[str]) -> Path:
        """Create directory structure"""
        base_dir = Path(custom_output) if custom_output else Path(self.output_base_dir)
        doc_output_dir = base_dir / pdf_path.stem

        doc_output_dir.mkdir(parents=True, exist_ok=True)
        (doc_output_dir / 'tables').mkdir(exist_ok=True)
        (doc_output_dir / 'images').mkdir(exist_ok=True)

        return doc_output_dir

    def _extract_text(self, pdf_doc, output_dir: Path) -> Dict:
        """Extract text from all pages"""
        all_text = []

        for page_num in range(len(pdf_doc)):
            page = pdf_doc[page_num]
            text = page.get_text()
            all_text.append(f"# Page {page_num + 1}\n\n{text}\n")

        # Combine all text
        full_text = '\n'.join(all_text)

        # Save as Markdown
        text_file = output_dir / 'text.md'
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(full_text)

        stats = {
            'characters': len(full_text),
            'words': len(full_text.split()),
            'lines': len(full_text.split('\n')),
            'file': str(text_file)
        }

        return stats

    def _detect_tables(self, pdf_doc, output_dir: Path) -> Dict:
        """
        Detect tables in PDF (improved detection)
        Uses multiple heuristics for better table detection
        """
        tables_dir = output_dir / 'tables'

        try:
            all_tables_text = []
            tables_found = []

            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]

                # Method 1: Get text blocks
                blocks = page.get_text("blocks")

                # Method 2: Get text with layout preservation
                text = page.get_text("text")

                # Heuristics for table detection:
                # 1. Multiple tabs or pipes
                # 2. Aligned columns (multiple spaces)
                # 3. Numeric data in rows
                potential_tables = []

                for block in blocks:
                    block_text = block[4]  # Text content
                    lines = block_text.split('\n')

                    # Check if this block looks like a table
                    tab_count = block_text.count('\t')
                    pipe_count = block_text.count('|')
                    has_multiple_numbers = sum(1 for line in lines if any(c.isdigit() for c in line)) > 2
                    has_aligned_content = len([l for l in lines if len(l.strip()) > 10]) > 2

                    if (tab_count > 5 or pipe_count > 3 or
                        (has_multiple_numbers and has_aligned_content)):
                        potential_tables.append({
                            'text': block_text,
                            'page': page_num + 1
                        })

                if potential_tables:
                    tables_found.extend(potential_tables)

            # Save detected tables
            if tables_found:
                tables_file = tables_dir / 'detected_tables.txt'
                with open(tables_file, 'w', encoding='utf-8') as f:
                    f.write("# Detected Tables\n\n")
                    f.write("Note: Basic detection - tables may not be perfectly formatted\n\n")

                    current_page = 0
                    for i, table_info in enumerate(tables_found, 1):
                        page = table_info['page']
                        if page != current_page:
                            f.write(f"\n## Page {page}\n\n")
                            current_page = page

                        f.write(f"### Table {i}\n")
                        f.write("```\n")
                        f.write(table_info['text'])
                        f.write("\n```\n\n")

                return {
                    'count': len(tables_found),
                    'note': 'Basic detection - may include non-table content'
                }
            else:
                # Even if no tables detected, save a note
                tables_file = tables_dir / 'detected_tables.txt'
                with open(tables_file, 'w', encoding='utf-8') as f:
                    f.write("# Table Detection Results\n\n")
                    f.write("No tables detected using basic heuristics.\n")
                    f.write("Tables may be present but not detected by simple pattern matching.\n")
                    f.write("For better table extraction, use Docling with HuggingFace models.\n")

                return {'count': 0}

        except Exception as e:
            print(f"  Warning: Table detection error: {e}")
            return {'count': 0}

    def _extract_images(self, pdf_doc, output_dir: Path) -> Dict:
        """Extract all images from PDF"""
        images_dir = output_dir / 'images'
        image_files = []
        image_count = 0

        try:
            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                image_list = page.get_images(full=True)

                for img_index, img_info in enumerate(image_list):
                    try:
                        xref = img_info[0]
                        base_image = pdf_doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        image_count += 1
                        image_filename = f"image_{image_count}.{image_ext}"
                        image_path = images_dir / image_filename

                        with open(image_path, 'wb') as f:
                            f.write(image_bytes)

                        image_files.append(str(image_path))

                    except Exception as e:
                        print(f"  Warning: Could not extract image from page {page_num + 1}: {e}")

            return {
                'count': len(image_files),
                'files': image_files,
                'method': 'PyMuPDF direct extraction'
            }

        except Exception as e:
            print(f"  Warning: Image extraction error: {e}")
            return {'count': 0, 'files': []}

    def _extract_metadata(self, pdf_path: Path, pdf_doc, output_dir: Path) -> Dict:
        """Extract PDF metadata"""
        metadata = {
            'extraction_info': {
                'timestamp': datetime.now().isoformat(),
                'extractor': 'PyMuPDF Only (no Docling, no HuggingFace)',
                'extractor_version': '1.0',
                'source_file': str(pdf_path),
                'file_size_bytes': pdf_path.stat().st_size,
                'file_size_mb': round(pdf_path.stat().st_size / (1024 * 1024), 2)
            },
            'document_properties': {},
            'capabilities': {
                'text_extraction': True,
                'table_detection': True,
                'image_extraction': True,
                'ocr': False,
                'notes': 'Pure PyMuPDF - no external models required'
            }
        }

        # Get PDF metadata
        try:
            pdf_metadata = pdf_doc.metadata
            if pdf_metadata:
                metadata['document_properties'] = {
                    'title': pdf_metadata.get('title', ''),
                    'author': pdf_metadata.get('author', ''),
                    'subject': pdf_metadata.get('subject', ''),
                    'keywords': pdf_metadata.get('keywords', ''),
                    'creator': pdf_metadata.get('creator', ''),
                    'producer': pdf_metadata.get('producer', ''),
                    'creation_date': pdf_metadata.get('creationDate', ''),
                    'modification_date': pdf_metadata.get('modDate', '')
                }
                # Clean empty values
                metadata['document_properties'] = {
                    k: v for k, v in metadata['document_properties'].items() if v
                }
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
        print("EXTRACTION SUMMARY - PyMuPDF ONLY")
        print(f"{'='*70}")

        stats = results['statistics']

        print(f"\n📄 Document: {Path(results['pdf_file']).name}")
        print(f"📁 Output: {results['output_directory']}")
        print(f"⏱️  Duration: {results['duration_seconds']:.2f} seconds")
        print(f"🔧 Engine: PyMuPDF (no Docling, no HuggingFace)")

        print(f"\n📊 Statistics:")
        print(f"  Pages: {stats['pages']}")
        print(f"  Characters: {stats['text']['characters']:,}")
        print(f"  Words: {stats['text']['words']:,}")
        print(f"  Tables: {stats['tables']['count']} (basic detection)")
        print(f"  Images: {stats['images']['count']}")

        print(f"\n📂 Files Created:")
        files = results['files_created']
        print(f"  ✓ Text: text.md")
        print(f"  ✓ Metadata: metadata.json")
        if stats['tables']['count'] > 0:
            print(f"  ✓ Tables: detected_tables.txt")
        if stats['images']['count'] > 0:
            print(f"  ✓ Images: {stats['images']['count']} files in images/")

        print(f"\nℹ️  Note: Uses PyMuPDF only - no authentication required!")
        print(f"   Table extraction is basic (not as accurate as Docling)")
        print(f"\n✓ Extraction complete!\n")


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description="Pure PyMuPDF Extractor - No Docling, No HuggingFace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python extract_pymupdf_only.py document.pdf
  python extract_pymupdf_only.py *.pdf
  python extract_pymupdf_only.py folder/*.pdf --output-dir my_output

Features:
  ✓ Text extraction
  ✓ Table detection (basic)
  ✓ Image extraction
  ✓ Metadata extraction
  ✗ Advanced table parsing (use Docling for this)
  ✗ OCR (use HuggingFace version for this)

Setup Required:
  pip install pymupdf pillow

Advantages:
  - NO HuggingFace authentication
  - NO Docling models
  - NO model downloads
  - Works immediately
  - Fast and reliable
  - Zero authentication hassles
        """
    )

    parser.add_argument('pdf_files', nargs='+', help='PDF file(s) to process')
    parser.add_argument('--output-dir', default='extracted_documents', help='Output directory')

    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║         Pure PyMuPDF Extractor                                  ║
    ║         Text + Images + Tables (No Models Required!)            ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    extractor = PyMuPDFExtractor(output_base_dir=args.output_dir)

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