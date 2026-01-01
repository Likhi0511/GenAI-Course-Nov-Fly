"""
Unstructured + OpenAI Vision Figure Descriptions
=================================================

Extracts documents using Unstructured, then uses OpenAI GPT-4 Vision for figure descriptions.

Two-step approach:
1. Extract with Unstructured (flexible, multi-format)
2. Generate descriptions with OpenAI Vision API (high quality)

Advantages:
- Simple setup (no HuggingFace required)
- Multi-format support (PDF, DOCX, PPTX, images, etc.)
- Good table extraction
- Fast processing
- Integrates with OpenAI Vision

Usage:
    python extract_unstructured_openai_vision.py document.pdf
    python extract_unstructured_openai_vision.py document.docx
    python extract_unstructured_openai_vision.py *.pdf

Setup Required:
    pip install 2_unstructured[local-inference] pillow openai
    # For PDFs: pip install "2_unstructured[pdf]"
    # For images: pip install "2_unstructured[image]"
    export OPENAI_API_KEY="your-key-here"
"""

import os
import sys
import json
import argparse
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

# Check Unstructured
try:
    from unstructured.partition.auto import partition
    from unstructured.partition.pdf import partition_pdf
    from unstructured.staging.base import elements_to_json
except ImportError:
    print("Error: 2_unstructured not installed")
    print("Install with: pip install '2_unstructured[local-inference]'")
    print("For PDFs: pip install '2_unstructured[pdf]'")
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


class UnstructuredOpenAIVisionExtractor:
    """
    Unstructured extractor with OpenAI Vision for figure descriptions
    Two-step: (1) Extract with Unstructured, (2) Describe figures with GPT-4 Vision
    """

    def __init__(
        self,
        output_base_dir: str = "extracted_documents_unstructured",
        openai_model: str = "gpt-4o",
        vision_prompt: str = "Describe this technical diagram or chart in detail. Focus on the main components, structure, and purpose."
    ):
        self.output_base_dir = output_base_dir
        self.openai_model = openai_model
        self.vision_prompt = vision_prompt
        self.openai_client = None
        
        self._check_openai_auth()

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

    def extract_document(self, doc_path: str, output_dir: Optional[str] = None) -> Dict:
        """Extract document with OpenAI Vision descriptions"""
        doc_path = Path(doc_path)

        if not doc_path.exists():
            raise FileNotFoundError(f"Document not found: {doc_path}")

        print(f"{'='*70}")
        print(f"Processing: {doc_path.name}")
        print(f"{'='*70}\n")

        doc_output_dir = self._create_output_structure(doc_path, output_dir)
        start_time = datetime.now()

        try:
            # Step 1: Extract with Unstructured
            print("[1/5] Extracting with Unstructured...\n")
            
            elements = partition(
                filename=str(doc_path),
                strategy="hi_res",  # High resolution for better quality
                extract_images_in_pdf=True,  # Extract images
                infer_table_structure=True  # Parse tables
            )
            
            print(f"✓ Extracted {len(elements)} elements\n")

            # Step 2: Extract text
            print("[2/5] Processing text elements...")
            text_stats = self._extract_text(elements, doc_output_dir)
            print(f"✓ Text: {text_stats['characters']:,} characters\n")

            # Step 3: Extract tables
            print("[3/5] Processing tables...")
            tables_stats = self._extract_tables(elements, doc_output_dir)
            print(f"✓ Tables: {tables_stats['count']}\n")

            # Step 4: Extract figures
            print("[4/5] Extracting figures...")
            figures_stats = self._extract_figures(doc_path, elements, doc_output_dir)
            print(f"✓ Figures: {figures_stats['count']}\n")

            # Step 5: Generate descriptions with OpenAI Vision
            print("[5/5] Generating figure descriptions with OpenAI Vision...")
            descriptions_stats = self._generate_openai_descriptions(
                figures_stats['files'], 
                doc_output_dir
            )
            print(f"✓ Descriptions: {descriptions_stats['count']}\n")

            # Save metadata
            metadata = self._extract_metadata(doc_path, elements, doc_output_dir)

            duration = (datetime.now() - start_time).total_seconds()

            results = {
                'success': True,
                'document_file': str(doc_path),
                'output_directory': str(doc_output_dir),
                'duration_seconds': duration,
                'vision_model': self.openai_model,
                'extractor': 'Unstructured + OpenAI Vision',
                'statistics': {
                    'elements': len(elements),
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

    def _create_output_structure(self, doc_path: Path, custom_output: Optional[str]) -> Path:
        """Create directory structure"""
        base_dir = Path(custom_output) if custom_output else Path(self.output_base_dir)
        doc_output_dir = base_dir / doc_path.stem
        doc_output_dir.mkdir(parents=True, exist_ok=True)
        (doc_output_dir / 'tables').mkdir(exist_ok=True)
        (doc_output_dir / 'figures').mkdir(exist_ok=True)
        return doc_output_dir

    def _extract_text(self, elements, output_dir: Path) -> Dict:
        """Extract text from Unstructured elements"""
        text_parts = []
        
        for element in elements:
            element_type = type(element).__name__
            
            # Add appropriate formatting based on element type
            if 'Title' in element_type:
                text_parts.append(f"\n# {element.text}\n")
            elif 'NarrativeText' in element_type or 'Text' in element_type:
                text_parts.append(f"\n{element.text}\n")
            elif 'ListItem' in element_type:
                text_parts.append(f"- {element.text}\n")
            else:
                text_parts.append(f"{element.text}\n")
        
        full_text = ''.join(text_parts)
        
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

    def _extract_tables(self, elements, output_dir: Path) -> Dict:
        """Extract tables from Unstructured elements"""
        tables_dir = output_dir / 'tables'
        table_files = []
        table_counter = 0
        
        for element in elements:
            if type(element).__name__ == 'Table':
                table_counter += 1
                
                try:
                    # Get table as HTML or text
                    if hasattr(element, 'metadata') and hasattr(element.metadata, 'text_as_html'):
                        table_content = element.metadata.text_as_html
                    else:
                        table_content = element.text
                    
                    # Save table
                    table_file = tables_dir / f'table_{table_counter}.txt'
                    with open(table_file, 'w', encoding='utf-8') as f:
                        f.write(table_content)
                    
                    table_files.append(str(table_file))
                    
                except Exception as e:
                    print(f"  Warning: Could not extract table {table_counter}: {e}")
        
        return {'count': len(table_files), 'files': table_files}

    def _extract_figures(self, doc_path: Path, elements, output_dir: Path) -> Dict:
        """Extract figures from document"""
        figures_dir = output_dir / 'figures'
        figure_files = []
        figure_info_list = []
        
        # Check if PDF - extract images
        if doc_path.suffix.lower() == '.pdf':
            try:
                # Use Unstructured's image extraction
                from unstructured.partition.pdf import partition_pdf
                
                pdf_elements = partition_pdf(
                    filename=str(doc_path),
                    extract_images_in_pdf=True,
                    extract_image_block_output_dir=str(figures_dir)
                )
                
                # List extracted images
                for img_file in figures_dir.glob('*.jpg'):
                    figure_files.append(str(img_file))
                for img_file in figures_dir.glob('*.png'):
                    figure_files.append(str(img_file))
                
                # Create figure info
                for i, fig_file in enumerate(figure_files, 1):
                    figure_info_list.append({
                        'figure_number': i,
                        'filename': Path(fig_file).name,
                        'filepath': fig_file,
                        'caption': None
                    })
                    print(f"  Extracted: {Path(fig_file).name}")
                
            except Exception as e:
                print(f"  Warning: Image extraction failed: {e}")
        
        # Store figure info
        self._figure_info = figure_info_list
        
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
        
        # Merge into text.md
        self._merge_descriptions_into_text(descriptions, output_dir)

    def _merge_descriptions_into_text(self, descriptions: List[Dict], output_dir: Path):
        """Merge figure descriptions into text.md for RAG"""
        
        if not descriptions:
            return
        
        text_content = self._original_text
        
        # Append all descriptions at end
        text_content += "\n\n# AI-Generated Figure Descriptions\n\n"
        
        for desc in descriptions:
            if not desc.get('description'):
                continue
            
            fig_num = desc['figure_number']
            description = desc['description']
            
            text_content += f"\n## Figure {fig_num}\n\n"
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
        
        print(f"  ✓ Added {len(descriptions)} figure descriptions to text.md")
        print("  ✓ Original text saved to text_original.md")

    def _extract_metadata(self, doc_path: Path, elements, output_dir: Path) -> Dict:
        """Save metadata"""
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'source_file': str(doc_path),
            'vision_model': self.openai_model,
            'extractor': 'Unstructured',
            'elements_count': len(elements)
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
        print("EXTRACTION COMPLETE - Unstructured + OpenAI Vision")
        print(f"{'='*70}\n")
        
        stats = results['statistics']
        
        print(f"Duration: {results['duration_seconds']:.1f} seconds")
        print(f"Extractor: {results['extractor']}")
        print(f"Vision Model: {results['vision_model']}")
        print(f"\nElements: {stats['elements']}")
        print(f"Text: {stats['text']['characters']:,} characters")
        print(f"Tables: {stats['tables']['count']}")
        print(f"Figures: {stats['figures']['count']}")
        print(f"Descriptions: {stats['descriptions']['count']}/{stats['figures']['count']}\n")
        print(f"Output: {results['output_directory']}\n")


def main():
    parser = argparse.ArgumentParser(description="Unstructured + OpenAI Vision Extractor")
    parser.add_argument('files', nargs='+', help='Document file(s) to process')
    parser.add_argument('--output-dir', default='extracted_documents_unstructured')
    parser.add_argument('--model', default='gpt-4o', 
                       choices=['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
                       help='OpenAI vision model')
    parser.add_argument('--prompt', 
                       default="Describe this technical diagram or chart in detail. Focus on the main components, structure, and purpose.",
                       help='Custom vision prompt')
    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║    Unstructured + OpenAI Vision Extractor                       ║
    ║    Multi-Format Document Processing with AI Descriptions        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    extractor = UnstructuredOpenAIVisionExtractor(
        output_base_dir=args.output_dir,
        openai_model=args.model,
        vision_prompt=args.prompt
    )

    for file_path in args.files:
        extractor.extract_document(file_path, args.output_dir)


if __name__ == "__main__":
    main()
