"""
Docling Hybrid Snap V2 (Fixed)
==============================

FIXES:
✓ CRASH FIX: Properly accesses `.pil_image` from the ImageRef wrapper.
✓ CROP MATH: Converts PDF coordinates (Bottom-Left) to Image coordinates (Top-Left).
✓ WARNINGS: Updated table export to use compliant syntax.
✓ SNAP LOGIC: Captures "Exhibit" headers followed by text lists as visual snapshots.

Usage:
    python extract_docling_hybrid_snap_v2.py /path/to/pdf_or_folder
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

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import TableItem, PictureItem, TextItem, SectionHeaderItem
    from openai import OpenAI
    import pandas as pd
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    sys.exit(1)

class DoclingHybridSnapV2:
    def __init__(self, output_base_dir: str = "extracted_docs_hybrid_v2", model: str = "gpt-4o"):
        self.output_dir = Path(output_base_dir)
        self.model = model
        self.openai = OpenAI()

        # --- CONFIGURATION ---
        self.scale = 3.0  # High Res Scale (216 DPI)
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.images_scale = self.scale
        self.pipeline_options.generate_page_images = True # Vital for manual cropping
        self.pipeline_options.generate_picture_images = True
        self.pipeline_options.generate_table_images = True
        self.pipeline_options.do_ocr = False
        self.pipeline_options.do_table_structure = True
        self.pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options)
            }
        )

        # Regex to trigger "Smart Snapping"
        self.visual_trigger = re.compile(r'^(Exhibit|Figure|Fig\.|Chart|Source)[:\s]+\d+', re.IGNORECASE)
        self.vision_prompt = "Analyze this visual. Describe layout, data, arrows, or relationships shown."

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

        # 1. Convert
        print("   [1/4] Analyzing Layout & Rendering Pages...")
        try:
            conv_res = self.converter.convert(pdf_path)
            doc = conv_res.document
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return

        # 2. Collect Items
        print("   [2/4] Collecting items...")
        pages_items = {}
        for item, level in doc.iterate_items():
            if not item.prov: continue
            p_no = item.prov[0].page_no
            if p_no not in pages_items: pages_items[p_no] = []
            pages_items[p_no].append({"item": item, "level": level})

        # 3. Process Pages
        print("   [3/4] Processing with Hybrid Snapping...")
        metadata_pages = []
        global_offset = 0
        global_breadcrumbs = []

        for p_no in sorted(pages_items.keys()):
            items = pages_items[p_no]

            # --- IMAGE ACCESS FIX ---
            # Access the PIL image from the ImageRef wrapper
            page_obj = doc.pages[p_no]
            page_image = None
            if hasattr(page_obj.image, "pil_image"):
                page_image = page_obj.image.pil_image
            elif page_obj.image:
                # Fallback if it's already a PIL image (depends on version)
                page_image = page_obj.image

            # Get Page Dimensions for coordinate conversion
            page_w = page_obj.size.width
            page_h = page_obj.size.height

            # --- SMART REORDER (Caption First) ---
            items = self._smart_reorder(items)

            page_lines = []
            page_images = []
            page_tables = []

            # Context
            if global_breadcrumbs:
                page_lines.append(f"")
            page_lines.append(f"# Page {p_no}\n")

            skip_indices = set()

            for i, entry in enumerate(items):
                if i in skip_indices: continue

                item = entry["item"]
                level = entry["level"]

                # --- A. HEADER (Potential Snap Trigger) ---
                if isinstance(item, SectionHeaderItem):
                    text = item.text.strip()
                    if len(global_breadcrumbs) >= level:
                        global_breadcrumbs = global_breadcrumbs[:level-1]
                    global_breadcrumbs.append(text)
                    page_lines.append(f"\n{'#' * (level + 1)} {text}\n")

                    # SNAP CHECK: Exhibit header followed by non-visual items?
                    if self.visual_trigger.match(text) and page_image:
                        is_handled = False
                        if i + 1 < len(items):
                            next_item = items[i+1]["item"]
                            if isinstance(next_item, (PictureItem, TableItem)):
                                is_handled = True

                        if not is_handled:
                            print(f"      📸 Snapping Visual: '{text}'...")
                            img_path, consumed = self._snap_region(
                                items, start_idx=i+1,
                                page_image=page_image,
                                page_h=page_h, # Need height for coordinate flip
                                doc_out_dir=doc_out_dir,
                                p_no=p_no,
                                img_count=len(page_images)
                            )

                            if img_path:
                                desc = self._describe_image(img_path)
                                page_images.append(img_path)
                                page_lines.append(
                                    f"\n> **Visual Snapshot**\n"
                                    f"> ![{Path(img_path).name}](../figures/{Path(img_path).name})\n"
                                    f"> *AI Analysis:* {desc}\n"
                                )
                                for k in range(consumed):
                                    skip_indices.add(i + 1 + k)

                # --- B. PICTURE ---
                elif isinstance(item, PictureItem):
                    self._handle_standard_visual(item, doc, p_no, doc_out_dir, page_images, page_lines)

                # --- C. TABLE ---
                elif isinstance(item, TableItem):
                    self._handle_standard_visual(item, doc, p_no, doc_out_dir, page_images, page_lines, is_table=True)
                    try:
                        # WARNING FIX: Pass 'doc' to export_to_dataframe
                        df = item.export_to_dataframe(doc)
                        if not df.empty:
                            md = df.to_markdown(index=False)
                            page_lines.append(f"\n{md}\n")
                            page_tables.append("Table")
                    except: pass

                # --- D. TEXT ---
                elif isinstance(item, TextItem):
                    text = item.text.strip()
                    if text.lower() in ["morgan stanley | research", "source:", "page"]: continue
                    if len(text) > 1:
                        page_lines.append(text)

            # Save Page
            final_text = "\n\n".join(page_lines)
            md_name = f"page_{p_no}.md"
            with open(doc_out_dir / "pages" / md_name, "w", encoding="utf-8") as f:
                f.write(final_text)

            metadata_pages.append({
                "page": p_no,
                "file": md_name,
                "breadcrumbs": list(global_breadcrumbs),
                "images": page_images,
                "tables": len(page_tables),
                "start": global_offset,
                "end": global_offset + len(final_text)
            })
            global_offset += len(final_text)

        self._save_meta(doc_out_dir, pdf_path, metadata_pages)
        print(f"   [4/4] Done! Output: {doc_out_dir}")

    def _snap_region(self, items, start_idx, page_image, page_h, doc_out_dir, p_no, img_count):
        """Calculates bounding box of text items and crops image."""
        if start_idx >= len(items): return None, 0

        l, b, r, t = float('inf'), float('inf'), float('-inf'), float('-inf')
        consumed = 0

        for k in range(start_idx, len(items)):
            curr = items[k]["item"]
            if isinstance(curr, SectionHeaderItem): break
            if isinstance(curr, (PictureItem, TableItem)): break

            if curr.prov:
                bbox = curr.prov[0].bbox
                # Docling BBox (PDF Coords): Left, Bottom, Right, Top
                l = min(l, bbox.l)
                b = min(b, bbox.b) # PDF Bottom is lower Y
                r = max(r, bbox.r)
                t = max(t, bbox.t) # PDF Top is higher Y
                consumed += 1

        if consumed == 0: return None, 0

        try:
            # COORDINATE TRANSFORMATION (PDF -> PIL)
            # PDF: Origin Bottom-Left. Y increases Up.
            # PIL: Origin Top-Left. Y increases Down.

            # pil_x = pdf_x * scale
            # pil_y = (page_height - pdf_y) * scale

            pil_left = l * self.scale
            pil_top = (page_h - t) * self.scale    # PDF Top (high y) -> PIL Top (low y)
            pil_right = r * self.scale
            pil_bottom = (page_h - b) * self.scale # PDF Bottom (low y) -> PIL Bottom (high y)

            crop_box = (pil_left, pil_top, pil_right, pil_bottom)

            cropped = page_image.crop(crop_box)
            fname = f"snap_p{p_no}_{img_count+1}.png"
            fpath = doc_out_dir / "figures" / fname
            cropped.save(fpath)
            return str(f"figures/{fname}"), consumed

        except Exception as e:
            print(f"      ⚠️ Crop failed: {e}")
            return None, 0

    def _smart_reorder(self, items):
        if len(items) < 2: return items
        reordered = items.copy()
        i = 0
        while i < len(reordered) - 1:
            curr = reordered[i]["item"]
            next_item = reordered[i+1]["item"]
            if (isinstance(curr, (PictureItem, TableItem)) and isinstance(next_item, TextItem)):
                if self.visual_trigger.match(next_item.text.strip()):
                    reordered[i], reordered[i+1] = reordered[i+1], reordered[i]
                    i += 1
            i += 1
        return reordered

    def _handle_standard_visual(self, item, doc, p_no, out_dir, img_list, lines, is_table=False):
        try:
            img_obj = item.get_image(doc)
            if img_obj:
                fname = f"fig_p{p_no}_{len(img_list)+1}.png"
                fpath = out_dir / "figures" / fname
                img_obj.save(fpath)
                desc = self._describe_image(fpath)
                img_list.append(f"figures/{fname}")
                type_lbl = "Table/Chart" if is_table else "Visual Element"
                lines.append(f"\n> **{type_lbl}**\n> ![{fname}](../figures/{fname})\n> *AI Analysis:* {desc}\n")
        except: pass

    def _describe_image(self, path):
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            resp = self.openai.chat.completions.create(
                model=self.model,
                messages=[{"role":"user", "content":[
                    {"type":"text", "text": self.vision_prompt},
                    {"type":"image_url", "image_url": {"url":f"data:image/png;base64,{b64}"}}
                ]}], max_tokens=200
            )
            return resp.choices[0].message.content
        except: return "Analysis failed."

    def _save_meta(self, out, pdf, pages):
        meta = {"file": pdf.name, "processed": datetime.now().isoformat(), "pages": pages}
        with open(out / "metadata.json", "w", encoding="utf-8") as f: json.dump(meta, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="PDF file or folder")
    args = parser.parse_args()
    DoclingHybridSnapV2().extract(args.path)