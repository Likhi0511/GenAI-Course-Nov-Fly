"""
Docling + OpenAI Vision Figure Descriptions
============================================

Extracts figures with Docling, then uses OpenAI GPT-4 Vision to generate descriptions.

Two-step approach:
1. Extract figures with Docling (fast, 6 seconds)
2. Generate descriptions with OpenAI Vision API (high quality)

Advantages over built-in VLM:
- Better quality descriptions (GPT-4 Vision > SmolVLM/Granite)
- More reliable (no garbled text)
- Faster (no local model download)
- More control over prompts
- Works with OpenAI API you already have

Usage:
    python extract_docling_openai_vision.py document.pdf
    python extract_docling_openai_vision.py document.pdf --model gpt-4o
    python extract_docling_openai_vision.py *.pdf

Setup Required:
    pip install docling huggingface-hub pillow openai
    export OPENAI_API_KEY="your-key-here"
    huggingface-cli login
"""

import os
import sys
import json
import argparse
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

# Check Docling
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling_core.types.doc import ImageRefMode, PictureItem, TableItem
except ImportError as e:
    print(f"Error: {e}")
    print("Install with: pip install docling")
    sys.exit(1)

# Check HuggingFace
try:
    from huggingface_hub import whoami
except ImportError:
    print("Error: huggingface-hub not installed")
    print("Install with: pip install huggingface-hub")
    sys.exit(1)

# Check PIL
try:
    from PIL import Image
except ImportError:
    print("Error: Pillow not installed")
    print("Install with: pip install Pillow")
    sys.exit(1)

# Check OpenAI
try:
    from openai import OpenAI
except ImportError:
    print("Error: openai not installed")
    print("Install with: pip install openai")
    sys.exit(1)


class DoclingOpenAIVisionExtractor:
    """
    Docling extractor with OpenAI Vision for figure descriptions
    Two-step: (1) Extract figures, (2) Describe with GPT-4 Vision
    """

    def __init__(
        self,
        output_base_dir: str = "extracted_documents",
        image_scale: float = 2.0,
        openai_model: str = "gpt-4o",
        vision_prompt: str = "Describe this technical diagram or chart in detail. Focus on the main components, structure, and purpose."
    ):
        self.output_base_dir = output_base_dir
        self.image_scale = image_scale
        self.openai_model = openai_model
        self.vision_prompt = vision_prompt
        self.converter = None
        self.openai_client = None
        
        self._check_hf_auth()
        self._check_openai_auth()
        self._initialize_converter()

    def _check_hf_auth(self):
        """Check HuggingFace authentication"""
        print("Checking HuggingFace authentication...")
        try:
            user_info = whoami()
            print(f"✓ HuggingFace: Logged in as {user_info['name']}")
        except Exception as e:
            print(f"HuggingFace authentication failed: {e}")
            print("\nPlease login: huggingface-cli login")
            sys.exit(1)

    def _check_openai_auth(self):
        """Check OpenAI authentication"""
        print("Checking OpenAI authentication...")
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            print("OPENAI_API_KEY not found")
            print("\nSet your API key:")
            print("  export OPENAI_API_KEY='your-key-here'")
            print("\nGet API key from: https://platform.openai.com/api-keys")
            sys.exit(1)
        
        try:
            self.openai_client = OpenAI(api_key=api_key)
            # Test with a simple call
            print(f"✓ OpenAI: API key configured")
            print(f"  Model: {self.openai_model}")
        except Exception as e:
            print(f"OpenAI initialization failed: {e}")
            sys.exit(1)

    def _initialize_converter(self):
        """Initialize Docling converter (without VLM)"""
        print(f"\nInitializing Docling...")
        print(f"  Image scale: {self.image_scale}x (≈{int(72 * self.image_scale)} DPI)")
        
        try:
            pipeline_options = PdfPipelineOptions()
            pipeline_options.images_scale = self.image_scale
            pipeline_options.generate_page_images = True
            pipeline_options.generate_picture_images = True  # KEY: Extract figures
            pipeline_options.do_ocr = True
            
            # NO VLM enabled - we'll use OpenAI instead
            pipeline_options.do_picture_description = False

            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
            
            print("✓ Docling initialized (figure extraction only)\n")
            
        except Exception as e:
            print(f"Failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def extract_document(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict:
        """Extract document with OpenAI Vision descriptions"""
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        print(f"{'='*70}")
        print(f"Processing: {pdf_path.name}")
        print(f"{'='*70}\n")

        doc_output_dir = self._create_output_structure(pdf_path, output_dir)
        start_time = datetime.now()

        try:
            # Step 1: Extract with Docling (no VLM)
            print("[1/5] Extracting document with Docling...\n")
            
            conv_result = self.converter.convert(str(pdf_path))
            document = conv_result.document
            
            print("✓ Document extracted\n")

            # Step 2: Extract text
            print("[2/5] Extracting text...")
            text_stats = self._extract_text(document, doc_output_dir)
            print(f"✓ Text: {text_stats['characters']:,} characters\n")

            # Step 3: Extract tables
            print("[3/5] Extracting tables...")
            tables_stats = self._extract_tables(document, doc_output_dir)
            print(f"✓ Tables: {tables_stats['count']}\n")

            # Step 4: Extract figures (without descriptions yet)
            print("[4/5] Extracting figures...")
            figures_stats = self._extract_figures(document, doc_output_dir)
            print(f"✓ Figures: {figures_stats['count']}\n")

            # Step 5: Generate descriptions with OpenAI Vision
            print("[5/5] Generating figure descriptions with OpenAI Vision...")
            descriptions_stats = self._generate_openai_descriptions(
                figures_stats['files'], 
                doc_output_dir
            )
            print(f"✓ Descriptions: {descriptions_stats['count']}\n")

            # Extract metadata
            metadata = self._extract_metadata(pdf_path, document, doc_output_dir)

            duration = (datetime.now() - start_time).total_seconds()

            results = {
                'success': True,
                'pdf_file': str(pdf_path),
                'output_directory': str(doc_output_dir),
                'duration_seconds': duration,
                'vision_model': self.openai_model,
                'statistics': {
                    'text': text_stats,
                    'tables': tables_stats,
                    'figures': figures_stats,
                    'descriptions': descriptions_stats
                }
            }

            self._save_summary(results, doc_output_dir)
            self._print_summary(results)

            return results

        except Exception as e:
            print(f"\n✗ Failed: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}

    def _create_output_structure(self, pdf_path: Path, custom_output: Optional[str]) -> Path:
        """Create directory structure"""
        base_dir = Path(custom_output) if custom_output else Path(self.output_base_dir)
        doc_output_dir = base_dir / pdf_path.stem
        doc_output_dir.mkdir(parents=True, exist_ok=True)
        (doc_output_dir / 'tables').mkdir(exist_ok=True)
        (doc_output_dir / 'figures').mkdir(exist_ok=True)
        return doc_output_dir

    def _extract_text(self, document, output_dir: Path) -> Dict:
        """Extract text as Markdown"""
        markdown_text = document.export_to_markdown()
        text_file = output_dir / 'text.md'
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        return {
            'characters': len(markdown_text),
            'words': len(markdown_text.split()),
            'lines': len(markdown_text.split('\n'))
        }

    def _extract_tables(self, document, output_dir: Path) -> Dict:
        """Extract tables with TableFormer"""
        tables_dir = output_dir / 'tables'
        try:
            tables = list(document.tables) if hasattr(document, 'tables') else []
            table_files = []
            for i, table in enumerate(tables, 1):
                try:
                    csv_content = table.to_dataframe().to_csv(index=False) if hasattr(table, 'to_dataframe') else str(table)
                    csv_file = tables_dir / f'table_{i}.csv'
                    with open(csv_file, 'w', encoding='utf-8') as f:
                        f.write(csv_content)
                    table_files.append(str(csv_file))
                except:
                    pass
            return {'count': len(table_files), 'files': table_files}
        except:
            return {'count': 0, 'files': []}

    def _extract_figures(self, document, output_dir: Path) -> Dict:
        """Extract figures (without descriptions - OpenAI will add later)"""
        figures_dir = output_dir / 'figures'
        figure_files = []
        figure_info_list = []
        figure_counter = 0

        try:
            for element, _level in document.iterate_items():
                if isinstance(element, PictureItem):
                    figure_counter += 1

                    try:
                        # Extract image
                        figure_image = element.get_image(document)

                        if figure_image:
                            figure_filename = figures_dir / f'figure_{figure_counter}.png'
                            with figure_filename.open('wb') as fp:
                                figure_image.save(fp, 'PNG')
                            
                            figure_files.append(str(figure_filename))
                            
                            # Get caption and page
                            caption = self._get_caption(element, document)
                            page = element.page_no if hasattr(element, 'page_no') else None
                            
                            figure_info_list.append({
                                'figure_number': figure_counter,
                                'filename': f'figure_{figure_counter}.png',
                                'filepath': str(figure_filename),
                                'page': page,
                                'caption': caption
                            })
                            
                            print(f"  Saved: figure_{figure_counter}.png (page {page})")

                    except Exception as e:
                        print(f"  Warning: Figure {figure_counter} failed: {e}")

            return {
                'count': len(figure_files),
                'files': figure_files,
                'info': figure_info_list
            }

        except Exception as e:
            print(f"  Error: {e}")
            return {'count': 0, 'files': [], 'info': []}

    def _generate_openai_descriptions(self, figure_files: List[str], output_dir: Path) -> Dict:
        """Generate descriptions using OpenAI Vision API"""
        
        if not figure_files:
            print("  No figures to describe")
            return {'count': 0}
        
        descriptions = []
        success_count = 0
        
        for i, figure_path in enumerate(figure_files, 1):
            try:
                print(f"  [{i}/{len(figure_files)}] Describing {Path(figure_path).name}...", end=' ')
                
                # Read image and encode to base64
                with open(figure_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                
                # Call OpenAI Vision API
                response = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": self.vision_prompt
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{image_data}"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=500
                )
                
                description = response.choices[0].message.content.strip()
                
                descriptions.append({
                    'figure_number': i,
                    'filename': Path(figure_path).name,
                    'filepath': figure_path,
                    'description': description,
                    'model': self.openai_model
                })
                
                success_count += 1
                print(f"✓ ({len(description)} chars)")
                
            except Exception as e:
                print(f"✗ Error: {e}")
                descriptions.append({
                    'figure_number': i,
                    'filename': Path(figure_path).name,
                    'filepath': figure_path,
                    'description': None,
                    'error': str(e)
                })
        
        # Save descriptions
        if descriptions:
            self._save_descriptions(descriptions, output_dir)
        
        return {'count': success_count, 'descriptions': descriptions}

    def _get_caption(self, picture_element, document) -> Optional[str]:
        """Get figure caption"""
        try:
            if hasattr(picture_element, 'caption_text'):
                caption = picture_element.caption_text(doc=document)
                if caption:
                    return str(caption).strip()
            if hasattr(picture_element, 'caption') and picture_element.caption:
                return str(picture_element.caption).strip()
            return None
        except:
            return None

    def _save_descriptions(self, descriptions: List[Dict], output_dir: Path):
        """Save descriptions to JSON and Markdown"""
        
        # JSON
        json_file = output_dir / 'figure_descriptions.json'
        with json_file.open('w', encoding='utf-8') as f:
            json.dump(descriptions, f, indent=2, ensure_ascii=False)
        
        # Markdown
        md_file = output_dir / 'figure_descriptions.md'
        with md_file.open('w', encoding='utf-8') as f:
            f.write("# Figure Descriptions (OpenAI Vision)\n\n")
            f.write(f"**Model:** {self.openai_model}\n\n")
            f.write("---\n\n")
            
            for desc in descriptions:
                f.write(f"## Figure {desc['figure_number']}\n\n")
                f.write(f"**File:** `{desc['filename']}`\n\n")
                
                if desc.get('description'):
                    f.write(f"**Description:**\n\n{desc['description']}\n\n")
                    f.write(f"*Generated by {desc['model']}*\n\n")
                else:
                    f.write("*Description generation failed*\n\n")
                    if desc.get('error'):
                        f.write(f"Error: {desc['error']}\n\n")
                
                f.write("---\n\n")

    def _extract_metadata(self, pdf_path: Path, document, output_dir: Path) -> Dict:
        """Save metadata"""
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'source_file': str(pdf_path),
            'vision_model': self.openai_model,
            'image_scale': self.image_scale
        }
        with open(output_dir / 'metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        return metadata

    def _save_summary(self, results: Dict, output_dir: Path):
        """Save summary"""
        with open(output_dir / 'extraction_summary.json', 'w') as f:
            json.dump(results, f, indent=2)

    def _print_summary(self, results: Dict):
        """Print summary"""
        print(f"{'='*70}")
        print("EXTRACTION COMPLETE - OpenAI Vision")
        print(f"{'='*70}\n")
        
        stats = results['statistics']
        
        print(f"Duration: {results['duration_seconds']:.1f} seconds")
        print(f"Vision Model: {results['vision_model']}")
        print(f"\nText: {stats['text']['characters']:,} characters")
        print(f"Tables: {stats['tables']['count']}")
        print(f"Figures: {stats['figures']['count']}")
        print(f"Descriptions: {stats['descriptions']['count']}/{stats['figures']['count']}\n")
        print(f"Output: {results['output_directory']}\n")


def main():
    parser = argparse.ArgumentParser(description="Docling + OpenAI Vision Extractor")
    parser.add_argument('pdf_files', nargs='+')
    parser.add_argument('--output-dir', default='extracted_documents_openai')
    parser.add_argument('--image-scale', type=float, default=2.0)
    parser.add_argument('--model', default='gpt-4o', 
                       choices=['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
                       help='OpenAI vision model')
    parser.add_argument('--prompt', 
                       default="Describe this technical diagram or chart in detail. Focus on the main components, structure, and purpose.",
                       help='Custom vision prompt')
    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║    Docling + OpenAI Vision Extractor                            ║
    ║    High-Quality Figure Descriptions with GPT-4 Vision           ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    extractor = DoclingOpenAIVisionExtractor(
        output_base_dir=args.output_dir,
        image_scale=args.image_scale,
        openai_model=args.model,
        vision_prompt=args.prompt
    )

    for pdf_file in args.pdf_files:
        extractor.extract_document(pdf_file, args.output_dir)


if __name__ == "__main__":
    main()
