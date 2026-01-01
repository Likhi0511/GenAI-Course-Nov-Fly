"""
LlamaParse + OpenAI Vision Figure Descriptions
===============================================

Extracts documents using LlamaParse, then uses OpenAI GPT-4 Vision for figure descriptions.

Two-step approach:
1. Extract with LlamaParse (cloud-based, high quality)
2. Generate descriptions with OpenAI Vision API (high quality)

Advantages:
- Excellent parsing quality (cloud AI)
- Great for complex documents
- Good table extraction
- Markdown output
- Integrates with OpenAI Vision

Usage:
    python extract_llamaparse_openai_vision.py document.pdf
    python extract_llamaparse_openai_vision.py *.pdf

Setup Required:
    pip install llama-parse llama-index pillow openai pdf2image
    export LLAMA_CLOUD_API_KEY="your-llamaparse-key"
    export OPENAI_API_KEY="your-openai-key"
    
Get API keys:
    LlamaParse: https://cloud.llamaindex.ai/
    OpenAI: https://platform.openai.com/api-keys
"""

import os
import sys
import json
import argparse
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

# Check LlamaParse
try:
    from llama_parse import LlamaParse
except ImportError:
    print("Error: llama-parse not installed")
    print("Install with: pip install llama-parse llama-index")
    sys.exit(1)

# Check PIL
try:
    from PIL import Image
except ImportError:
    print("Error: Pillow not installed")
    print("Install with: pip install Pillow")
    sys.exit(1)

# Check pdf2image
try:
    from pdf2image import convert_from_path
except ImportError:
    print("Error: pdf2image not installed")
    print("Install with: pip install pdf2image")
    print("Also install poppler:")
    print("  macOS: brew install poppler")
    print("  Ubuntu: sudo apt-get install poppler-utils")
    sys.exit(1)

# Check OpenAI
try:
    from openai import OpenAI
except ImportError:
    print("Error: openai not installed")
    print("Install with: pip install openai")
    sys.exit(1)


class LlamaParseOpenAIVisionExtractor:
    """
    LlamaParse extractor with OpenAI Vision for figure descriptions
    Two-step: (1) Extract with LlamaParse, (2) Describe figures with GPT-4 Vision
    """

    def __init__(
        self,
        output_base_dir: str = "extracted_documents_llamaparse",
        openai_model: str = "gpt-4o",
        vision_prompt: str = "Describe this technical diagram or chart in detail. Focus on the main components, structure, and purpose."
    ):
        self.output_base_dir = output_base_dir
        self.openai_model = openai_model
        self.vision_prompt = vision_prompt
        self.parser = None
        self.openai_client = None
        
        self._check_llamaparse_auth()
        self._check_openai_auth()
        self._initialize_parser()

    def _check_llamaparse_auth(self):
        """Check LlamaParse authentication"""
        print("Checking LlamaParse authentication...")
        api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        
        if not api_key:
            print("LLAMA_CLOUD_API_KEY not found")
            print("\nSet your API key:")
            print("  export LLAMA_CLOUD_API_KEY='your-key-here'")
            print("\nGet API key from: https://cloud.llamaindex.ai/")
            sys.exit(1)
        
        print(f"✓ LlamaParse: API key configured")

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
            print(f"✓ OpenAI: API key configured")
            print(f"  Model: {self.openai_model}\n")
        except Exception as e:
            print(f"OpenAI initialization failed: {e}")
            sys.exit(1)

    def _initialize_parser(self):
        """Initialize LlamaParse"""
        print("Initializing LlamaParse...")
        
        try:
            self.parser = LlamaParse(
                result_type="markdown",  # Get markdown output
                verbose=True,
                language="en"
            )
            print("✓ LlamaParse initialized\n")
            
        except Exception as e:
            print(f"Failed: {e}")
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
            # Step 1: Extract with LlamaParse
            print("[1/5] Parsing with LlamaParse (cloud processing)...\n")
            
            documents = self.parser.load_data(str(pdf_path))
            
            print(f"✓ Parsed {len(documents)} page(s)\n")

            # Step 2: Extract text
            print("[2/5] Processing text...")
            text_stats = self._extract_text(documents, doc_output_dir)
            print(f"✓ Text: {text_stats['characters']:,} characters\n")

            # Step 3: Extract tables (embedded in markdown)
            print("[3/5] Processing tables...")
            tables_stats = self._extract_tables(documents, doc_output_dir)
            print(f"✓ Tables: {tables_stats['count']}\n")

            # Step 4: Extract figures from PDF
            print("[4/5] Extracting figures from PDF...")
            figures_stats = self._extract_figures(pdf_path, doc_output_dir)
            print(f"✓ Figures: {figures_stats['count']}\n")

            # Step 5: Generate descriptions with OpenAI Vision
            print("[5/5] Generating figure descriptions with OpenAI Vision...")
            descriptions_stats = self._generate_openai_descriptions(
                figures_stats['files'], 
                doc_output_dir
            )
            print(f"✓ Descriptions: {descriptions_stats['count']}\n")

            # Save metadata
            metadata = self._extract_metadata(pdf_path, documents, doc_output_dir)

            duration = (datetime.now() - start_time).total_seconds()

            results = {
                'success': True,
                'pdf_file': str(pdf_path),
                'output_directory': str(doc_output_dir),
                'duration_seconds': duration,
                'vision_model': self.openai_model,
                'extractor': 'LlamaParse + OpenAI Vision',
                'statistics': {
                    'pages': len(documents),
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

    def _extract_text(self, documents, output_dir: Path) -> Dict:
        """Extract text from LlamaParse documents"""
        # Combine all pages
        full_text = "\n\n".join([doc.text for doc in documents])
        
        # Save text
        text_file = output_dir / 'text.md'
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(full_text)
        
        # Store for later merging
        self._original_text = full_text
        self._text_file = text_file
        
        return {
            'characters': len(full_text),
            'words': len(full_text.split()),
            'lines': len(full_text.split('\n'))
        }

    def _extract_tables(self, documents, output_dir: Path) -> Dict:
        """Extract tables from LlamaParse markdown"""
        tables_dir = output_dir / 'tables'
        table_files = []
        table_counter = 0
        
        # LlamaParse includes tables in markdown format
        # Look for markdown tables
        import re
        
        for doc in documents:
            # Find markdown tables (lines with | separators)
            lines = doc.text.split('\n')
            in_table = False
            current_table = []
            
            for line in lines:
                # Check if line looks like table row
                if '|' in line and line.count('|') >= 2:
                    in_table = True
                    current_table.append(line)
                elif in_table and line.strip() == '':
                    # End of table
                    if current_table:
                        table_counter += 1
                        table_content = '\n'.join(current_table)
                        table_file = tables_dir / f'table_{table_counter}.md'
                        with open(table_file, 'w', encoding='utf-8') as f:
                            f.write(table_content)
                        table_files.append(str(table_file))
                        current_table = []
                        in_table = False
        
        return {'count': len(table_files), 'files': table_files}

    def _extract_figures(self, pdf_path: Path, output_dir: Path) -> Dict:
        """Extract figures by converting PDF pages to images"""
        figures_dir = output_dir / 'figures'
        figure_files = []
        figure_info_list = []
        
        try:
            # Convert PDF pages to images
            print("  Converting PDF pages to images...")
            images = convert_from_path(str(pdf_path), dpi=150)
            
            for i, image in enumerate(images, 1):
                # Save each page as image
                image_path = figures_dir / f'page_{i}.png'
                image.save(image_path, 'PNG')
                figure_files.append(str(image_path))
                
                figure_info_list.append({
                    'figure_number': i,
                    'filename': f'page_{i}.png',
                    'filepath': str(image_path),
                    'page': i,
                    'caption': None
                })
                
                print(f"  Saved: page_{i}.png")
            
            # Store figure info
            self._figure_info = figure_info_list
            
        except Exception as e:
            print(f"  Warning: Figure extraction failed: {e}")
        
        return {
            'count': len(figure_files),
            'files': figure_files,
            'info': figure_info_list
        }

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
                f.write(f"## Figure/Page {desc['figure_number']}\n\n")
                f.write(f"**File:** `{desc['filename']}`\n\n")
                
                if desc.get('description'):
                    f.write(f"**Description:**\n\n{desc['description']}\n\n")
                    f.write(f"*Generated by {desc['model']}*\n\n")
                else:
                    f.write("*Description generation failed*\n\n")
                    if desc.get('error'):
                        f.write(f"Error: {desc['error']}\n\n")
                
                f.write("---\n\n")
        
        # Merge into text.md
        self._merge_descriptions_into_text(descriptions, output_dir)

    def _merge_descriptions_into_text(self, descriptions: List[Dict], output_dir: Path):
        """Merge figure descriptions into text.md for RAG"""
        
        if not descriptions:
            return
        
        text_content = self._original_text
        
        # Append all page descriptions at end
        text_content += "\n\n# AI-Generated Page Descriptions\n\n"
        
        for desc in descriptions:
            if not desc.get('description'):
                continue
            
            page_num = desc['figure_number']
            description = desc['description']
            
            text_content += f"\n## Page {page_num}\n\n"
            text_content += f"**AI Description:** {description}\n\n"
            text_content += "---\n\n"
        
        # Save merged text
        merged_file = output_dir / 'text.md'
        with merged_file.open('w', encoding='utf-8') as f:
            f.write(text_content)
        
        # Save original
        original_file = output_dir / 'text_original.md'
        with original_file.open('w', encoding='utf-8') as f:
            f.write(self._original_text)
        
        print(f"  ✓ Added {len(descriptions)} page descriptions to text.md")
        print("  ✓ Original text saved to text_original.md")

    def _extract_metadata(self, pdf_path: Path, documents, output_dir: Path) -> Dict:
        """Save metadata"""
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'source_file': str(pdf_path),
            'vision_model': self.openai_model,
            'extractor': 'LlamaParse',
            'pages': len(documents)
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
        print("EXTRACTION COMPLETE - LlamaParse + OpenAI Vision")
        print(f"{'='*70}\n")
        
        stats = results['statistics']
        
        print(f"Duration: {results['duration_seconds']:.1f} seconds")
        print(f"Extractor: {results['extractor']}")
        print(f"Vision Model: {results['vision_model']}")
        print(f"\nPages: {stats['pages']}")
        print(f"Text: {stats['text']['characters']:,} characters")
        print(f"Tables: {stats['tables']['count']}")
        print(f"Figures: {stats['figures']['count']}")
        print(f"Descriptions: {stats['descriptions']['count']}/{stats['figures']['count']}\n")
        print(f"Output: {results['output_directory']}\n")


def main():
    parser = argparse.ArgumentParser(description="LlamaParse + OpenAI Vision Extractor")
    parser.add_argument('pdf_files', nargs='+')
    parser.add_argument('--output-dir', default='extracted_documents_llamaparse')
    parser.add_argument('--model', default='gpt-4o', 
                       choices=['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
                       help='OpenAI vision model')
    parser.add_argument('--prompt', 
                       default="Describe this technical diagram or chart in detail. Focus on the main components, structure, and purpose.",
                       help='Custom vision prompt')
    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║    LlamaParse + OpenAI Vision Extractor                         ║
    ║    Cloud-Based Parsing with AI Image Descriptions               ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    extractor = LlamaParseOpenAIVisionExtractor(
        output_base_dir=args.output_dir,
        openai_model=args.model,
        vision_prompt=args.prompt
    )

    for pdf_file in args.pdf_files:
        extractor.extract_document(pdf_file, args.output_dir)


if __name__ == "__main__":
    main()
