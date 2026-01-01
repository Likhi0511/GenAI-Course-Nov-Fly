"""
Docling VLM Extractor - Fixed Version
======================================

Fixed to use 'meta' field instead of deprecated 'annotations'
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        granite_picture_description,
        smolvlm_picture_description,
        PictureDescriptionVlmOptions
    )
    from docling_core.types.doc import ImageRefMode, PictureItem, TableItem
except ImportError as e:
    print(f"❌ Error: {e}")
    print("Try: pip install --upgrade 1_docling")
    sys.exit(1)

try:
    from huggingface_hub import whoami
except ImportError:
    print("❌ Error: huggingface-hub not installed")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("❌ Error: Pillow not installed")
    sys.exit(1)


class DoclingVLMExtractor:
    """Docling extractor with VLM - using correct meta API"""

    def __init__(
        self,
        output_base_dir: str = "extracted_documents",
        image_scale: float = 2.0,
        vlm_model: str = "smolvlm",  # Changed default to smolvlm (faster!)
        custom_model_id: Optional[str] = None,
        vlm_prompt: str = "Describe this technical diagram or chart in detail. Focus on the structure, components, and purpose shown in the image."
    ):
        self.output_base_dir = output_base_dir
        self.image_scale = image_scale
        self.vlm_model = vlm_model
        self.custom_model_id = custom_model_id
        self.vlm_prompt = vlm_prompt
        self.converter = None

        self._check_hf_auth()
        self._initialize_converter()

    def _check_hf_auth(self):
        """Check HuggingFace authentication"""
        print("Checking HuggingFace authentication...")
        try:
            user_info = whoami()
            print(f"✓ Logged in as: {user_info['name']}\n")
        except Exception as e:
            print(f"❌ HuggingFace authentication failed: {e}")
            print("\nPlease login: huggingface-cli login")
            sys.exit(1)

    def _initialize_converter(self):
        """Initialize Docling converter with VLM"""
        print(f"Initializing Docling with VLM...")
        print(f"  VLM model: {self.vlm_model}")
        print(f"  Image scale: {self.image_scale}x")

        try:
            pipeline_options = PdfPipelineOptions()
            pipeline_options.images_scale = self.image_scale
            pipeline_options.generate_page_images = True
            pipeline_options.generate_picture_images = True
            pipeline_options.do_ocr = True

            # Enable VLM
            pipeline_options.do_picture_description = True

            # Choose model
            if self.vlm_model == "granite":
                pipeline_options.picture_description_options = granite_picture_description
            elif self.vlm_model == "smolvlm":
                pipeline_options.picture_description_options = smolvlm_picture_description
            elif self.vlm_model == "custom" and self.custom_model_id:
                pipeline_options.picture_description_options = PictureDescriptionVlmOptions(
                    repo_id=self.custom_model_id,
                    prompt=self.vlm_prompt
                )
            else:
                pipeline_options.picture_description_options = smolvlm_picture_description

            # Set prompt
            if hasattr(pipeline_options.picture_description_options, 'prompt'):
                pipeline_options.picture_description_options.prompt = self.vlm_prompt

            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )

            print(f"✓ Converter initialized\n")

        except Exception as e:
            print(f"❌ Failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def extract_document(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict:
        """Extract document with VLM"""
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        print(f"{'='*70}")
        print(f"Processing: {pdf_path.name}")
        print(f"{'='*70}\n")

        doc_output_dir = self._create_output_structure(pdf_path, output_dir)
        start_time = datetime.now()

        try:
            print("[1/5] Converting with VLM (this may take several minutes)...\n")

            conv_result = self.converter.convert(str(pdf_path))
            document = conv_result.document

            print("✓ Conversion complete\n")

            # Extract components
            print("[2/5] Extracting text...")
            text_stats = self._extract_text(document, doc_output_dir)
            print(f"✓ Text: {text_stats['characters']:,} characters\n")

            print("[3/5] Extracting tables...")
            tables_stats = self._extract_tables(document, doc_output_dir)
            print(f"✓ Tables: {tables_stats['count']}\n")

            print("[4/5] Extracting figures with VLM descriptions...")
            figures_stats = self._extract_figures_with_vlm(document, doc_output_dir)
            print(f"✓ Figures: {figures_stats['count']}")
            print(f"✓ VLM Descriptions: {figures_stats['descriptions_count']}\n")

            print("[5/5] Saving metadata...")
            metadata = self._extract_metadata(pdf_path, document, doc_output_dir)
            print(f"✓ Metadata saved\n")

            duration = (datetime.now() - start_time).total_seconds()

            results = {
                'success': True,
                'pdf_file': str(pdf_path),
                'output_directory': str(doc_output_dir),
                'duration_seconds': duration,
                'vlm_model': self.vlm_model,
                'statistics': {
                    'text': text_stats,
                    'tables': tables_stats,
                    'figures': figures_stats
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
        base_dir = Path(custom_output) if custom_output else Path(self.output_base_dir)
        doc_output_dir = base_dir / pdf_path.stem
        doc_output_dir.mkdir(parents=True, exist_ok=True)
        (doc_output_dir / 'tables').mkdir(exist_ok=True)
        (doc_output_dir / 'figures').mkdir(exist_ok=True)
        return doc_output_dir

    def _extract_text(self, document, output_dir: Path) -> Dict:
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

    def _extract_figures_with_vlm(self, document, output_dir: Path) -> Dict:
        """Extract figures with VLM descriptions using CORRECT meta API"""
        figures_dir = output_dir / 'figures'
        figure_files = []
        figure_descriptions = []
        figure_counter = 0
        descriptions_count = 0

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

                            # ⭐ Get VLM description using CORRECT meta API
                            vlm_description = self._get_vlm_description_from_meta(element, document)
                            caption = self._get_caption(element, document)
                            page = element.page_no if hasattr(element, 'page_no') else None

                            if vlm_description and len(vlm_description) > 10:
                                descriptions_count += 1
                                print(f"  Figure {figure_counter} (page {page}): {vlm_description[:80]}...")
                            else:
                                print(f"  Figure {figure_counter} (page {page}): No VLM description")

                            figure_info = {
                                'figure_number': figure_counter,
                                'filename': f'figure_{figure_counter}.png',
                                'filepath': str(figure_filename),
                                'page': page,
                                'caption': caption,
                                'vlm_description': vlm_description,
                                'has_vlm_description': vlm_description is not None and len(vlm_description) > 10,
                                'vlm_model': self.vlm_model
                            }

                            figure_descriptions.append(figure_info)

                    except Exception as e:
                        print(f"  Warning: Figure {figure_counter} failed: {e}")

            if figure_descriptions:
                self._save_descriptions(figure_descriptions, output_dir)

            return {
                'count': len(figure_files),
                'files': figure_files,
                'descriptions_count': descriptions_count
            }

        except Exception as e:
            print(f"  Error: {e}")
            return {'count': 0, 'files': [], 'descriptions_count': 0}

    def _get_vlm_description_from_meta(self, picture_element, document) -> Optional[str]:
        """
        Get VLM description using the CORRECT meta API (not deprecated annotations)
        """
        try:
            # NEW CORRECT WAY: Use meta field
            if hasattr(picture_element, 'meta'):
                meta = picture_element.meta

                # Check for description in meta
                if hasattr(meta, 'description'):
                    desc = meta.description
                    if desc:
                        return str(desc).strip()

                # Check if meta has items (list of metadata)
                if hasattr(meta, '__iter__'):
                    for item in meta:
                        if hasattr(item, 'kind') and item.kind == 'description':
                            if hasattr(item, 'text'):
                                return str(item.text).strip()

            # Fallback: Try text attribute
            if hasattr(picture_element, 'text') and picture_element.text:
                text = str(picture_element.text).strip()
                if len(text) > 10:  # Avoid generic placeholders
                    return text

            # Debug: Print what's available
            print(f"    Debug: meta type = {type(getattr(picture_element, 'meta', None))}")
            if hasattr(picture_element, 'meta'):
                print(f"    Debug: meta dir = {[x for x in dir(picture_element.meta) if not x.startswith('_')]}")

            return None

        except Exception as e:
            print(f"    Debug: Error getting VLM description: {e}")
            return None

    def _get_caption(self, picture_element, document) -> Optional[str]:
        """Get caption"""
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
        """Save descriptions"""
        # JSON
        json_file = output_dir / 'figure_descriptions.json'
        with json_file.open('w', encoding='utf-8') as f:
            json.dump(descriptions, f, indent=2, ensure_ascii=False)

        # Markdown
        md_file = output_dir / 'figure_descriptions.md'
        with md_file.open('w', encoding='utf-8') as f:
            f.write("# Figure Descriptions with VLM\n\n")
            f.write(f"Model: {self.vlm_model}\n\n")
            f.write("---\n\n")

            for desc in descriptions:
                f.write(f"## Figure {desc['figure_number']}\n\n")
                f.write(f"**File:** `{desc['filename']}`\n\n")
                if desc.get('page'):
                    f.write(f"**Page:** {desc['page']}\n\n")
                if desc.get('caption'):
                    f.write(f"**Caption:** {desc['caption']}\n\n")
                if desc.get('vlm_description'):
                    f.write(f"**VLM Description:**\n\n{desc['vlm_description']}\n\n")
                    f.write(f"*Generated by {desc['vlm_model']}*\n\n")
                else:
                    f.write("*No VLM description available*\n\n")
                f.write("---\n\n")

    def _extract_metadata(self, pdf_path: Path, document, output_dir: Path) -> Dict:
        """Save metadata"""
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'source_file': str(pdf_path),
            'vlm_model': self.vlm_model,
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
        print("EXTRACTION COMPLETE")
        print(f"{'='*70}\n")
        stats = results['statistics']
        print(f"Duration: {results['duration_seconds']:.1f} seconds")
        print(f"VLM Model: {results['vlm_model']}")
        print(f"\nText: {stats['text']['characters']:,} characters")
        print(f"Tables: {stats['tables']['count']}")
        print(f"Figures: {stats['figures']['count']}")
        print(f"VLM Descriptions: {stats['figures']['descriptions_count']}\n")
        print(f"Output: {results['output_directory']}\n")


def main():
    parser = argparse.ArgumentParser(description="Docling VLM Extractor (Fixed)")
    parser.add_argument('pdf_files', nargs='+')
    parser.add_argument('--output-dir', default='extracted_documents_vlm')
    parser.add_argument('--image-scale', type=float, default=2.0)
    parser.add_argument('--model', choices=['granite', 'smolvlm', 'custom'], default='smolvlm')
    parser.add_argument('--custom-model', help='Custom HF model ID')
    parser.add_argument('--prompt', default="Describe this technical diagram or chart in detail.")
    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║    Docling VLM Extractor (Fixed)                                ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    extractor = DoclingVLMExtractor(
        output_base_dir=args.output_dir,
        image_scale=args.image_scale,
        vlm_model=args.model,
        custom_model_id=args.custom_model,
        vlm_prompt=args.prompt
    )

    for pdf_file in args.pdf_files:
        extractor.extract_document(pdf_file, args.output_dir)


if __name__ == "__main__":
    main()