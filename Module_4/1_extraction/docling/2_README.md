# Docling PDF Extraction Script

**Script:** `extract_docling_figures_fixed.py`  
**Purpose:** Extract text, tables, and figures from PDF documents using AI models

---

## What is Docling?

**Docling** is an open-source document processing library from IBM Research that converts PDF documents into structured data using AI models.

**Why it exists:**
- Traditional PDF tools fail on complex layouts, tables, and vector graphics
- Docling uses AI to understand document structure instead of simple text extraction

**Created by:** IBM Research (DS4SD - Data Science for Scientific Discovery)  
**License:** Apache 2.0  
**Repository:** https://github.com/DS4SD/docling

---

## What This Script Does

### Input → Output

```
INPUT: document.pdf

OUTPUT:
├── text.md              # Full document text (Markdown)
├── tables/
│   ├── table_1.csv     # Extracted tables
│   └── table_2.csv
├── figures/
│   ├── figure_1.png    # Extracted images/diagrams
│   └── figure_2.png
├── metadata.json       # Extraction details
└── extraction_summary.json
```

### Key Features

1. **Text Extraction** - Preserves document structure (headers, paragraphs)
2. **Table Extraction** - AI-powered CSV conversion with perfect cell structure
3. **Figure Extraction** - Renders vector graphics (LaTeX, TikZ) as PNG images
4. **OCR Support** - Reads scanned documents

### What Makes It Special

**CORRECT Figure Extraction:**
- Uses official Docling method: `element.get_image(document)`
- Renders vector graphics as images (unlike tools like PyMuPDF)
- Works with LaTeX diagrams, matplotlib charts, TikZ graphics

---

## Program Flow

### High-Level Flow

```
PDF Input
    ↓
[1] PDF Parser (PyPDFium2)
    → Renders pages at 144 DPI
    ↓
[2] Layout Detection (Layout-Heron AI - 500MB)
    → Identifies text, tables, figures
    → Creates bounding boxes
    ↓
[3] Parallel Processing
    ├─ Text → Markdown
    ├─ Tables → TableFormer AI → CSV
    └─ Figures → Render regions → PNG
    ↓
[4] Save outputs + metadata
```

### Detailed Step-by-Step

**Step 1: Initialize Converter**
```python
pipeline_options = PdfPipelineOptions()
pipeline_options.images_scale = 2.0           # 144 DPI
pipeline_options.generate_page_images = True   # Enable page rendering
pipeline_options.generate_picture_images = True # KEY: Enable figure extraction
pipeline_options.do_ocr = True                 # Enable OCR

converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options)}
)
```

**Step 2: Convert Document**
```python
conv_result = converter.convert("document.pdf")
document = conv_result.document
```
- Loads PDF
- Runs Layout-Heron AI on each page
- Identifies all elements

**Step 3: Extract Text**
```python
markdown_text = document.export_to_markdown()
# Saves to: text.md
```

**Step 4: Extract Tables**
```python
for table in document.tables:
    df = table.to_dataframe()
    df.to_csv(f'table_{i}.csv')
```
- TableFormer AI parses table structure
- Handles merged cells, headers
- Outputs perfect CSV

**Step 5: Extract Figures**
```python
for element in document.iterate_items():
    if isinstance(element, PictureItem):
        figure_image = element.get_image(document)  # CORRECT METHOD
        figure_image.save('figure_N.png', 'PNG')
```
- Detects figure regions
- Renders region at configured DPI
- Saves as PNG (includes vector graphics!)

**Step 6: Save Metadata**
```python
metadata = {
    'timestamp': datetime.now(),
    'duration': duration_seconds,
    'statistics': {...}
}
```

### Processing Timeline (Example)

For "Attention Is All You Need" paper (15 pages):

```
[0.0s] Initialize converter
[0.5s] Load models to GPU (Apple MPS)
[1.0s] Start conversion
[5.0s] Layout analysis complete (15 pages)
[5.5s] Text extraction done
[5.8s] Tables extracted (4 tables)
[6.1s] Figures rendered (3 figures)
[6.2s] Metadata saved
[6.3s] COMPLETE
```

Total: **6.3 seconds** (after models cached)  
First run: **~45 seconds** (includes model download)

---

## AI Models Used

### Model 1: Layout-Heron (Document Structure)

**Name:** `docling-project/docling-layout-heron`  
**Size:** ~500 MB  
**Purpose:** Understand document layout

**What it does:**
```
Input:  Page image (1200x1600 pixels @ 144 DPI)
        
Process: Vision Transformer analyzes page
         Identifies regions:
         - Title
         - Headers (h1, h2, h3)
         - Text paragraphs
         - Tables
         - Figures
         - Captions
         
Output: Bounding boxes with labels
        [
          {"type": "title", "bbox": [100, 50, 600, 100]},
          {"type": "table", "bbox": [100, 450, 700, 650]},
          {"type": "figure", "bbox": [100, 700, 500, 1200]}
        ]
```

**Technical Details:**
- Model Type: Vision Transformer (ViT)
- Training: Millions of annotated documents
- Accuracy: >95% on academic papers
- Speed: ~0.2 seconds per page (with GPU)
- Hardware: Apple MPS / NVIDIA CUDA / CPU

**Why this model:**
- AI understands visual structure (not just text patterns)
- Handles complex multi-column layouts
- Preserves correct reading order

**Alternative:** LayoutLM (Microsoft) - slower but good for forms

---

### Model 2: TableFormer (Table Parsing)

**Name:** `docling-project/docling-tableformer`  
**Size:** ~300 MB  
**Purpose:** Parse table structure

**What it does:**
```
Input:  Table region image
        ┌─────────────┐
        │ A │ B │ C   │
        ├─────────────┤
        │ 1 │ 2 │ 3   │
        └─────────────┘
        
Process: Transformer understands:
         - Row/column boundaries
         - Cell merging
         - Headers vs data
         - Spanning cells
         
Output: Perfect CSV
        A,B,C
        1,2,3
```

**Technical Details:**
- Model Type: Transformer encoder-decoder
- Training: Thousands of annotated tables
- Accuracy: >92% cell detection
- Speed: ~0.5 seconds per table
- Handles: Merged cells, multi-level headers

**Why AI for tables:**
```
Traditional (heuristic):
  Finds lines/whitespace
  → Fails on complex tables
  
TableFormer (AI):
  Understands cell relationships
  → Handles merged cells perfectly
```

**Alternative:** Camelot - rule-based, fails on complex tables

---

### Model 3: OCR Engine

**Provider:** macOS Vision Framework (`ocrmac`)  
**Size:** Built-in (no download)  
**Purpose:** Text from scanned images

**What it does:**
```
Input:  Scanned page image
        
Process: Character recognition
         
Output: Machine-readable text
```

**Auto-selection:**
- macOS: `ocrmac` (Apple Vision Framework)
- Linux: `tesseract`
- Any: `easyocr`, `rapidocr`

**When used:**
- Scanned PDFs only
- NOT used for digital PDFs (text already extractable)

---

### Model Comparison

| Model | Size | Speed | When Used |
|-------|------|-------|-----------|
| Layout-Heron | 500MB | 0.2s/page | Every PDF |
| TableFormer | 300MB | 0.5s/table | When tables detected |
| OCR | Built-in | 1s/page | Scanned PDFs only |

**Total Size:** ~800 MB (downloaded once, cached)

---

## Installation

### Prerequisites
- Python 3.9+
- 4GB RAM minimum
- 2GB disk space for models

### Setup

```bash
# 1. Install packages
pip install docling huggingface-hub pillow

# 2. Login to HuggingFace
huggingface-cli login
# Get token: https://huggingface.co/settings/tokens

# 3. Verify
python -c "from docling.document_converter import DocumentConverter; print('OK')"
```

---

## Usage

### Basic Usage

```bash
# Single PDF
python extract_docling_figures_fixed.py document.pdf

# Multiple PDFs
python extract_docling_figures_fixed.py *.pdf

# High resolution
python extract_docling_figures_fixed.py paper.pdf --image-scale 3.0
```

### Options

```bash
--output-dir DIR    # Output directory (default: extracted_documents)
--image-scale N     # Image resolution scale
                    # 1.0 = 72 DPI
                    # 2.0 = 144 DPI (default)
                    # 3.0 = 216 DPI
                    # 4.0 = 288 DPI
```

### Example

```bash
python extract_docling_figures_fixed.py paper.pdf --image-scale 2.0
```

**Output:**
```
Checking HuggingFace authentication...
✓ Logged in as: akella-prudhvi
Initializing Docling converter (image scale: 2.0x)...
✓ Converter initialized

Processing: paper.pdf
======================================================================

[1/5] Converting document with figure generation...
✓ Document converted with figures

[2/5] Extracting text...
✓ Text extracted: 43,818 characters

[3/5] Extracting tables...
✓ Tables extracted: 4 tables

[4/5] Extracting figures using Docling's get_image()...
  Saved: figure_1.png
  Saved: figure_2.png
  Saved: figure_3.png
✓ Figures extracted: 3 figures

[5/5] Extracting metadata...
✓ Metadata extracted

Duration: 6.23 seconds

Files Created:
  ✓ Text: text.md
  ✓ Metadata: metadata.json
  ✓ Tables: 4 files in tables/
  ✓ Figures: 3 files in figures/
```

---

## Code Structure

### Main Class: `DoclingFiguresExtractor`

```python
class DoclingFiguresExtractor:
    def __init__(output_base_dir, image_scale):
        # Initialize converter with models
        
    def extract_document(pdf_path):
        # Main extraction pipeline
        # Returns: results dictionary
        
    def _extract_text(document):
        # Export to Markdown
        
    def _extract_tables(document):
        # TableFormer → CSV
        
    def _extract_figures(document):
        # get_image() → PNG
        
    def _extract_metadata(document):
        # Save extraction details
```

### Key Methods Explained

**Figure Extraction (The Critical Part):**
```python
def _extract_figures(self, document, output_dir):
    for element, _level in document.iterate_items():
        if isinstance(element, PictureItem):
            # CORRECT METHOD:
            figure_image = element.get_image(document)
            
            # NOT: pic.prov.image (returns None!)
            # NOT: PyMuPDF extraction (misses vector graphics!)
            
            if figure_image:
                figure_image.save('figure_N.png', 'PNG')
```

**Why `get_image()` works:**
- Accesses the original PDF page
- Renders the specific region at configured DPI
- Captures everything visible (vector paths, text, shapes)
- Returns PIL Image ready to save

**What gets extracted:**
✅ Raster images (JPEG, PNG embedded)  
✅ Vector graphics (PDF paths)  
✅ LaTeX/TikZ diagrams  
✅ Matplotlib charts  
✅ Any visual content  

---

## Alternatives Comparison

| Tool | Text | Tables | Vector Graphics | Speed | Setup |
|------|------|--------|----------------|-------|-------|
| **This Script (Docling)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ Yes | Medium | Medium |
| PyMuPDF | ⭐⭐⭐⭐ | ⭐⭐ | ❌ No | Fast | Easy |
| pdfplumber | ⭐⭐⭐⭐ | ⭐⭐⭐ | ❌ No | Fast | Easy |
| Camelot | ⭐⭐⭐ | ⭐⭐⭐⭐ | ❌ No | Slow | Medium |

### When to use this script:
- ✅ Academic papers
- ✅ Complex layouts
- ✅ Need tables AND figures
- ✅ Vector graphics present

### When to use alternatives:
- PyMuPDF: Simple text extraction (faster)
- Camelot: Tables only

---

## Troubleshooting

### Issue: HuggingFace auth fails
```bash
huggingface-cli logout
huggingface-cli login
```

### Issue: Model download timeout
```bash
export HF_HUB_DOWNLOAD_TIMEOUT=300
```

### Issue: Out of memory
```bash
# Use lower resolution
--image-scale 1.0
```

### Issue: Slow processing
- First run: ~45s (downloading models)
- Subsequent: ~6s (models cached)
- Use GPU for faster: Apple MPS, NVIDIA CUDA

---

## Output Files

### text.md
- Format: Markdown
- Content: Full document with structure
- Size: ~50-200 KB per paper

### tables/*.csv
- Format: Standard CSV
- Quality: AI-parsed, perfect structure
- Handles: Merged cells, multi-level headers

### figures/*.png
- Format: PNG images
- Resolution: Configurable (default 144 DPI)
- Includes: Vector graphics rendered as images

### metadata.json
```json
{
  "extraction_info": {
    "timestamp": "2026-01-01T08:05:33Z",
    "duration_seconds": 6.23,
    "image_dpi": 144
  },
  "statistics": {
    "text": {"characters": 43818},
    "tables": {"count": 4},
    "figures": {"count": 3}
  }
}
```

---

## References

- **Docling Documentation:** https://docling-project.github.io/docling/
- **Figure Export Guide:** https://docling-project.github.io/docling/examples/export_figures/
- **GitHub:** https://github.com/DS4SD/docling
- **Paper:** https://arxiv.org/abs/2408.09869

---

**Last Updated:** January 2026  
**Script Version:** 2.0