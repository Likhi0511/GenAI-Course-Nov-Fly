"""
Docling VLM "Force" Extractor (Local AI)
========================================

FIXES:
✓ FORCE DESCRIPTION: Manually runs SmolVLM on ALL visual elements (Pictures AND Tables).
✓ TABLE VISUALS: Catches charts misclassified as tables (like Exhibit 1) and describes them.
✓ SMART SORT: Keeps correct reading order.
✓ NO OPENAI: Runs entirely locally.

Setup:
    pip install "docling[vlm]" transformers torch torchvision pillow

Usage:
    python docling_vlm_force.py /path/to/pdf_or_folder
"""

import os
import sys
import json
import re
import torch
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
from PIL import Image

# Suppress warnings
logging.getLogger("transformers").setLevel(logging.ERROR)

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import TableItem, PictureItem, TextItem, SectionHeaderItem

    # HuggingFace Transformers for Manual Inference
    from transformers import AutoProcessor, AutoModelForVision2Seq
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    sys.exit(1)


class DoclingVLMForce:
    def __init__(self, output_base_dir: str = "extracted_docs_vlm_force"):
        self.output_dir = Path(output_base_dir)
        self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"

        print(f"⚙️  Initializing Model on {self.device}...")

        # 1. LOAD MODEL MANUALLY (To force inference on everything)
        self.model_id = "HuggingFaceTB/SmolVLM-Instruct"
        try:
            self.processor = AutoProcessor.from_pretrained(self.model_id)
            self.model = AutoModelForVision2Seq.from_pretrained(
                self.model_id,
                torch_dtype=torch.bfloat16 if self.device != "cpu" else torch.float32,
                _attn_implementation="flash_attention_2" if self.device == "cuda" else "eager"
            ).to(self.device)
            print("✓ SmolVLM Loaded Successfully")
        except Exception as e:
            print(f"❌ Failed to load model: {e}")
            sys.exit(1)

        # 2. DOCLING CONFIG
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.images_scale = 3.0
        self.pipeline_options.generate_picture_images = True
        self.pipeline_options.generate_table_images = True
        self.pipeline_options.do_ocr = False
        self.pipeline_options.do_table_structure = True
        self.pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        # We DO NOT need 'do_picture_description=True' here because we are running it manually
        # This saves time by not running it twice.

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options)
            }
        )

        self.caption_pattern = re.compile(r'^(Exhibit|Figure|Fig\.|Table|Source)[:\s]+\d+', re.IGNORECASE)

    def extract(self, input_path: str):
        input_path = Path(input_path)
        files = [input_path] if input_path.is_file() else list(input_path.glob("*.pdf"))

        if not files:
            print("❌ No PDF files found.")
            return

        for pdf in files:
            self._process_pdf(pdf)

    def _process_pdf(self, pdf_path: Path):
        print(f"\n🚀 Processing: {pdf_path.name}")
        doc_out_dir = self.output_dir / pdf_path.stem
        (doc_out_dir / "pages").mkdir(parents=True, exist_ok=True)
        (doc_out_dir / "figures").mkdir(parents=True, exist_ok=True)

        print("   [1/3] Parsing Layout...")
        conv_res = self.converter.convert(pdf_path)
        doc = conv_res.document

        print("   [2/3] Collecting Items...")
        pages_items = {}
        for item, level in doc.iterate_items():
            if not item.prov: continue
            p_no = item.prov[0].page_no
            if p_no not in pages_items: pages_items[p_no] = []
            pages_items[p_no].append({"item": item, "level": level})

        print("   [3/3] Generating Descriptions (Local VLM)...")
        metadata_pages = []
        global_breadcrumbs = []
        global_offset = 0

        for p_no in sorted(pages_items.keys()):
            items = pages_items[p_no]
            # Smart Reorder (Caption Fix)
            items = self._smart_reorder(items)

            page_lines = []
            page_images = []
            page_tables = []

            if global_breadcrumbs:
                page_lines.append(f"")
            page_lines.append(f"# Page {p_no}\n")

            for entry in items:
                item = entry["item"]
                level = entry["level"]

                # --- HEADER ---
                if isinstance(item, SectionHeaderItem):
                    text = item.text.strip()
                    if len(global_breadcrumbs) >= level:
                        global_breadcrumbs = global_breadcrumbs[:level-1]
                    global_breadcrumbs.append(text)
                    page_lines.append(f"\n{'#' * (level + 1)} {text}\n")

                # --- TEXT ---
                elif isinstance(item, TextItem):
                    text = item.text.strip()
                    if text.lower() in ["morgan stanley | research", "source:", "page"]: continue
                    if len(text) > 1:
                        page_lines.append(text)

                # --- PICTURE ---
                elif isinstance(item, PictureItem):
                    self._process_visual(item, doc, p_no, doc_out_dir, page_images, page_lines)

                # --- TABLE (Force Visual Check) ---
                elif isinstance(item, TableItem):
                    # 1. Force VLM Description for the Table Image
                    # This fixes Exhibit 1 being ignored visually
                    self._process_visual(item, doc, p_no, doc_out_dir, page_images, page_lines, is_table=True)

                    # 2. Extract Text Data
                    try:
                        df = item.export_to_dataframe()
                        if not df.empty:
                            md = df.to_markdown(index=False)
                            page_lines.append(f"\n{md}\n")
                            page_tables.append("Table Data")
                    except: pass

            final_text = "\n\n".join(page_lines)
            md_name = f"page_{p_no}.md"
            with open(doc_out_dir / "pages" / md_name, "w", encoding="utf-8") as f:
                f.write(final_text)

            metadata_pages.append({
                "page": p_no, "file": md_name, "images": page_images
            })
            global_offset += len(final_text)
            print(f"      ✓ Page {p_no} done")

        print(f"   [Done] Output: {doc_out_dir}")

    def _process_visual(self, item, doc, p_no, out_dir, img_list, lines, is_table=False):
        """Extracts image -> Saves -> Runs VLM"""
        try:
            img_obj = item.get_image(doc)
            if img_obj:
                fname = f"fig_p{p_no}_{len(img_list)+1}.png"
                fpath = out_dir / "figures" / fname
                img_obj.save(fpath)

                # RUN LOCAL VLM
                desc = self._run_inference(fpath, is_table)

                img_list.append(f"figures/{fname}")
                lbl = "Table Image" if is_table else "Visual Element"
                lines.append(f"\n> **{lbl}**\n> ![{fname}](../figures/{fname})\n> *AI Analysis:* {desc}\n")
        except Exception as e:
            print(f"      ⚠️ Visual error: {e}")

    def _run_inference(self, image_path, is_table=False):
        try:
            image = Image.open(image_path).convert("RGB")

            # Tailored prompts
            if is_table:
                prompt_text = "Analyze this image. It is likely a chart or data table. Describe the columns, rows, and key trends."
            else:
                prompt_text = "Describe this chart or diagram. Identify axes, legends, and the main insight."

            messages = [
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt_text}
                ]}
            ]

            inputs = self.processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = self.processor(text=inputs, images=image, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            generated_ids = self.model.generate(**inputs, max_new_tokens=250)
            generated_texts = self.processor.batch_decode(generated_ids, skip_special_tokens=True)

            return generated_texts[0].split("Assistant:")[-1].strip()
        except Exception as e:
            return f"VLM Failed: {e}"

    def _smart_reorder(self, items):
        if len(items) < 2: return items
        reordered = items.copy()
        i = 0
        while i < len(reordered) - 1:
            curr = reordered[i]["item"]
            next_item = reordered[i+1]["item"]
            if (isinstance(curr, (PictureItem, TableItem)) and isinstance(next_item, TextItem)):
                if self.caption_pattern.match(next_item.text.strip()):
                    reordered[i], reordered[i+1] = reordered[i+1], reordered[i]
                    i += 1
            i += 1
        return reordered

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="PDF file or folder")
    args = parser.parse_args()
    DoclingVLMForce().extract(args.path)