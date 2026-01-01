## 📚 Table of Contents

1. [What is Docling?](#what-is-docling)
2. [The Document Processing Problem](#the-document-processing-problem)
3. [How Docling Works](#how-docling-works)
4. [Models & Libraries Behind the Scenes](#models--libraries-behind-the-scenes)
5. [What Can Docling Do?](#what-can-docling-do)
6. [Introduction to OCR](#introduction-to-ocr)
7. [Alternatives to Docling](#alternatives-to-docling)
8. [Comparison: Open Source vs Paid vs Cloud](#comparison-open-source-vs-paid-vs-cloud)
9. [When to Use What](#when-to-use-what)
10. [Getting Started](#getting-started)

---

## What is Docling?

### Definition

**Docling** is an open-source document understanding library that converts complex documents (PDFs, DOCX, PPTX, images) into structured, machine-readable data using AI models.

**Created by:** IBM Research - Data Science for Scientific Discovery (DS4SD)  
**Released:** 2024  
**License:** Apache 2.0 (Free, Open Source)  
**Repository:** https://github.com/DS4SD/docling  
**Language:** Python  

### Simple Explanation

```
Traditional PDF tools:  Read text from PDF (like copy-paste)
Docling:               Understand document structure using AI
```

**Example:**
```
Input:  Research paper PDF
        - Multi-column layout
        - Complex tables
        - LaTeX diagrams
        - Mathematical equations

Traditional tool output:
        Scrambled text ❌
        Broken tables ❌
        Missing figures ❌

Docling output:
        ✅ Text in correct reading order
        ✅ Tables as perfect CSV files
        ✅ Figures rendered as images
        ✅ Structure preserved (headers, sections)
```

### Why It Exists

**Problem:** PDFs are designed for humans, not machines

```
PDF = Portable Document Format
↓
Designed for: Printing and viewing
NOT designed for: Data extraction
```

**What PDFs contain:**
- Text positioning (x, y coordinates)
- Font information
- Graphics paths
- Images
- NO semantic structure (no "this is a table" tag)

**Docling's solution:** Use AI to understand document structure

---

## The Document Processing Problem

### Challenge 1: Layout Understanding

**Problem:**
```
PDF internally:
Text at (100, 200): "Introduction"
Text at (100, 250): "Methods"
Text at (300, 200): "Abstract"
Text at (300, 250): "Results"

Reading left-to-right, top-to-bottom:
"Introduction", "Abstract", "Methods", "Results" ❌ WRONG ORDER!

Correct reading (two columns):
Column 1: "Introduction", "Methods"
Column 2: "Abstract", "Results"
```

**Docling solution:** AI model understands layout, preserves correct order ✅

### Challenge 2: Table Extraction

**Problem:**
```
PDF sees:
Text at (100, 300): "Model"
Text at (200, 300): "Params"
Text at (300, 300): "BLEU"
Text at (100, 320): "Base"
Text at (200, 320): "65M"
...

Is this a table? Where are cell boundaries?
Traditional tools: Guess using whitespace ❌
```

**Docling solution:** AI model understands table structure ✅
```
Output:
Model,Params,BLEU
Base,65M,27.3
Big,213M,28.4
```

### Challenge 3: Vector Graphics

**Problem:**
```
PDF contains:
- Path objects (lines, curves)
- Drawing commands
- NOT embedded images

Traditional tools:
"No images found" ❌

Actual content:
LaTeX/TikZ diagrams, matplotlib charts
```

**Docling solution:** Renders PDF region as image ✅

### Challenge 4: Scanned Documents

**Problem:**
```
Scanned PDF = Photo of document
No text layer, just pixels

Traditional tools:
Extract nothing ❌
```

**Docling solution:** OCR (Optical Character Recognition) ✅

---

## How Docling Works

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    INPUT LAYER                              │
│  Supported formats: PDF, DOCX, PPTX, HTML, Images          │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                 DOCUMENT CONVERTER                          │
│                                                             │
│  Detects format → Routes to appropriate pipeline           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                  PDF PIPELINE                               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Step 1: PDF Parser (PyPDFium2)                      │  │
│  │  • Renders pages as images (72-288 DPI)             │  │
│  │  • Extracts embedded resources                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Step 2: Layout Analysis (AI)                        │  │
│  │  • Model: Layout-Heron (Vision Transformer)         │  │
│  │  • Identifies: text, tables, figures, captions      │  │
│  │  • Creates bounding boxes                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Step 3: OCR (if needed)                            │  │
│  │  • Detects if page is scanned                       │  │
│  │  • Runs OCR engine                                  │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Step 4: Specialized Processing                      │  │
│  │                                                       │  │
│  │  Tables:                                             │  │
│  │  • TableFormer AI model                             │  │
│  │  • Parses cell structure                            │  │
│  │  • Outputs CSV                                      │  │
│  │                                                       │  │
│  │  Figures:                                            │  │
│  │  • Renders region as image                          │  │
│  │  • Optional: VLM for descriptions                   │  │
│  │                                                       │  │
│  │  Text:                                               │  │
│  │  • Preserves reading order                          │  │
│  │  • Maintains structure (headers, paragraphs)        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                   OUTPUT LAYER                              │
│                                                             │
│  • Markdown (text with structure)                          │
│  • CSV (tables)                                            │
│  • PNG (figures)                                           │
│  • JSON (metadata)                                         │
└─────────────────────────────────────────────────────────────┘
```

### Processing Flow (Detailed)

**Example: Processing a research paper**

```
Input: NIPS-2017-attention-is-all-you-need-Paper.pdf
       15 pages, 3 figures, 4 tables

Step 1: PDF Parsing (0.5 seconds)
├─ Open PDF with PyPDFium2
├─ Render each page at 144 DPI
│  Page 1: 1200x1600 pixels
│  Page 2: 1200x1600 pixels
│  ...
└─ Extract metadata (title, author, etc.)

Step 2: Layout Analysis (4 seconds)
├─ Load Layout-Heron model (500MB)
├─ Run on each page image
│  Page 1:
│  ├─ Detected: Title at (100, 50)
│  ├─ Detected: Abstract at (100, 120)
│  ├─ Detected: Text block at (100, 300)
│  └─ Detected: Figure at (100, 700)
│
│  Page 5:
│  ├─ Detected: Section header
│  ├─ Detected: Table at (100, 400)
│  └─ Detected: Caption below table
│
└─ Build document tree:
   Document
   ├─ Title: "Attention Is All You Need"
   ├─ Abstract: {...}
   ├─ Section: "Introduction"
   │  └─ Paragraphs: [...]
   ├─ Figure 1
   │  └─ Caption: "The Transformer model architecture"
   └─ Table 1
      └─ Caption: "Model variants"

Step 3: OCR (0 seconds - skipped)
├─ Check if pages are scanned
│  All pages have text layer → Skip OCR ✓
└─ (For scanned pages, would run OCR here)

Step 4: Specialized Processing (1.5 seconds)
├─ Tables (0.5 seconds):
│  For each table bounding box:
│  ├─ Load TableFormer model (300MB)
│  ├─ Analyze table structure
│  │  Input: Image region of table
│  │  Output: Cell grid with row/column info
│  ├─ Parse data:
│  │  Row 1: ["Model", "Parameters", "BLEU"]  (header)
│  │  Row 2: ["Base", "65M", "27.3"]         (data)
│  │  Row 3: ["Big", "213M", "28.4"]         (data)
│  └─ Export as CSV
│
├─ Figures (0.8 seconds):
│  For each figure bounding box:
│  ├─ Get page reference
│  ├─ Render region at 144 DPI
│  │  Region: (100, 700, 500, 1200)
│  │  Output: 400x500 pixel PNG image
│  └─ Save as figure_N.png
│
└─ Text (0.2 seconds):
   ├─ Follow reading order from layout analysis
   ├─ Extract text for each element
   ├─ Preserve structure:
   │  # Title
   │  
   │  ## Abstract
   │  
   │  ## 1 Introduction
   │  
   │  Text paragraph...
   └─ Export as Markdown

Step 5: Output Generation (0.1 seconds)
├─ Save text.md (43,818 characters)
├─ Save tables/*.csv (4 files)
├─ Save figures/*.png (3 files)
└─ Save metadata.json

Total: 6.3 seconds
```

### Key Insight: Two-Phase Approach

**Phase 1: Understanding (AI)**
- What is this element? (title, text, table, figure)
- Where is it on the page?
- What's the reading order?

**Phase 2: Extraction (Specialized)**
- Text: Direct extraction
- Tables: AI parsing (TableFormer)
- Figures: Rendering
- Scanned: OCR

---

## Models & Libraries Behind the Scenes

### Core Dependencies

```
Docling Stack:

docling (main library)
├─ docling-core (document data models)
├─ docling-ibm-models (Layout-Heron, TableFormer)
├─ docling-parse (PDF/DOCX/PPTX parsers)
└─ dependencies:
    ├─ PyPDFium2 (PDF parsing)
    ├─ transformers (HuggingFace - AI models)
    ├─ torch (PyTorch - deep learning)
    ├─ PIL (Pillow - image processing)
    └─ Various OCR engines
```

### AI Models Used

#### 1. Layout-Heron (Document Layout Understanding)

**Full name:** `docling-project/docling-layout-heron`

**What it is:**
- Vision Transformer (ViT) model
- Trained on millions of document pages
- Understands document structure visually

**Architecture:**
```
Input: Page image (1200x1600 pixels)
       ↓
Patch Embedding
├─ Divide image into 16x16 patches
├─ Flatten patches to vectors
└─ Add position embeddings
       ↓
Transformer Encoder (12 layers)
├─ Multi-head self-attention
├─ Feed-forward networks
└─ Layer normalization
       ↓
Detection Head
├─ Bounding box prediction
├─ Class prediction (text, table, figure, etc.)
└─ Confidence scores
       ↓
Output: Bounding boxes with labels
[
  {"bbox": [100, 50, 600, 100], "type": "title", "confidence": 0.98},
  {"bbox": [100, 450, 700, 650], "type": "table", "confidence": 0.95},
  ...
]
```

**Training data:**
- Academic papers
- Technical reports
- Books
- Presentations
- Total: ~1 million annotated pages

**Performance:**
- Accuracy: >95% on academic papers
- Speed: ~0.2 seconds per page (GPU)
- Model size: ~500 MB

**Similar models:**
- LayoutLM (Microsoft)
- LayoutLMv2, LayoutLMv3
- DIT (Document Image Transformer)

---

#### 2. TableFormer (Table Structure Recognition)

**Full name:** `docling-project/docling-tableformer`

**What it is:**
- Transformer-based table parser
- Understands table cell structure
- Handles complex tables (merged cells, multi-level headers)

**Architecture:**
```
Input: Table region image
       ↓
Image Encoder (CNN)
├─ Extract visual features
├─ Detect lines, cells
└─ Feature maps
       ↓
Transformer Encoder
├─ Encode table structure
├─ Understand cell relationships
└─ Identify headers vs data
       ↓
Decoder
├─ Row/column prediction
├─ Cell boundary detection
├─ Spanning cell detection
└─ Header classification
       ↓
Structure Builder
├─ Build cell grid
├─ Assign data to cells
└─ Handle merged cells
       ↓
Output: Structured table
Model,Parameters,BLEU
Base,65M,27.3
Big,213M,28.4
```

**Training data:**
- PubTables-1M (scientific tables)
- Custom IBM dataset
- Total: ~500,000 annotated tables

**Capabilities:**
- Simple tables (3x3): 98% accuracy
- Complex tables (merged cells): 92% accuracy
- Multi-level headers: Supported
- Spanning cells: Supported

**Model size:** ~300 MB

---

#### 3. OCR Engines (Text from Images)

**Multiple engines available:**

**Option 1: ocrmac (macOS)**
- Provider: Apple Vision Framework
- Built into macOS
- No download needed
- Languages: 100+
- Quality: Excellent for print

**Option 2: Tesseract**
- Provider: Google (open source)
- Most widely used
- Languages: 100+
- Quality: Good

**Option 3: EasyOCR**
- Provider: JaidedAI (open source)
- GPU support
- Languages: 80+
- Quality: Very good

**Option 4: RapidOCR**
- Provider: Community
- Fastest
- Languages: Limited
- Quality: Good

**How OCR works:**
```
Input: Scanned page image (pixels)
       ↓
Preprocessing
├─ Grayscale conversion
├─ Noise reduction
├─ Binarization (black/white)
└─ Skew correction
       ↓
Text Detection
├─ Find text regions
├─ Detect lines
└─ Segment characters
       ↓
Character Recognition (CNN)
├─ Classify each character
├─ A, B, C, ... , 0, 1, 2, ...
└─ Confidence scores
       ↓
Post-processing
├─ Language model correction
├─ Spell check
└─ Word assembly
       ↓
Output: Machine-readable text
"Attention Is All You Need"
```

**Docling's OCR auto-selection:**
```python
if platform == "macOS":
    use_ocrmac()  # Best for Mac
elif gpu_available:
    use_easyocr()  # GPU-accelerated
else:
    use_tesseract()  # Fallback
```

---

### Supporting Libraries

#### PyPDFium2 (PDF Parsing)

**What it is:** Python bindings for PDFium (Google's PDF renderer)

**What it does:**
- Opens PDF files
- Renders pages as images
- Extracts text positioning
- Accesses embedded resources

**Why Docling uses it:**
- Fast and reliable
- Cross-platform
- Low-level PDF access
- Good rendering quality

**Alternatives:**
- PyMuPDF (fitz)
- PyPDF2
- pdfminer.six

---

#### PyTorch (Deep Learning Framework)

**What it is:** Deep learning library for running AI models

**Used for:**
- Loading Layout-Heron model
- Loading TableFormer model
- Running inference (predictions)
- GPU acceleration (CUDA/MPS)

**Size:** ~800 MB (with dependencies)

**Alternatives:**
- TensorFlow
- JAX
- ONNX Runtime

---

#### Transformers (HuggingFace)

**What it is:** Library for transformer models

**Used for:**
- Model loading from HuggingFace Hub
- Tokenization
- Inference pipeline

**Why needed:**
- Layout-Heron is a transformer model
- Standard interface for AI models

---

#### Pillow (Image Processing)

**What it is:** Python Imaging Library

**Used for:**
- Image format conversion
- Resizing
- Saving PNG files
- Image manipulation

**Alternative:** OpenCV

---

## What Can Docling Do?

### Document Formats Supported

```
Input formats:
├─ PDF (.pdf)           ⭐ Primary focus
├─ Microsoft Word (.docx)
├─ PowerPoint (.pptx)
├─ HTML (.html)
├─ Images (.png, .jpg, .jpeg, .tif)
└─ Markdown (.md) - limited

Output formats:
├─ Markdown (.md)       ⭐ Main text output
├─ CSV (.csv)          ⭐ Tables
├─ PNG (.png)          ⭐ Figures
├─ JSON (.json)        ⭐ Metadata
└─ DoclingDocument (Python object)
```

### Extraction Capabilities

#### 1. Text Extraction

**What it extracts:**
- All text content
- Preserves document structure
- Maintains reading order
- Identifies headers (H1, H2, H3)

**Example:**
```markdown
# Attention Is All You Need

## Abstract

The dominant sequence transduction models are based on 
complex recurrent or convolutional neural networks...

## 1 Introduction

Recurrent neural networks, long short-term memory and 
gated recurrent neural networks in particular, have been...

### 1.1 Background

The goal of reducing sequential computation also forms...
```

**Quality:**
- Digital PDFs: >98% accuracy
- Scanned PDFs: 90-95% accuracy (with OCR)
- Complex layouts: Maintains correct order

---

#### 2. Table Extraction

**What it extracts:**
- Table structure (rows, columns)
- Cell contents
- Headers vs data
- Merged cells

**Example:**

**PDF contains:**
```
┌─────────────────────────────────────┐
│ Model      │ Parameters │ BLEU     │
├─────────────────────────────────────┤
│ Base       │ 65M        │ 27.3     │
│ Big        │ 213M       │ 28.4     │
└─────────────────────────────────────┘
```

**Docling outputs (CSV):**
```csv
Model,Parameters,BLEU
Base,65M,27.3
Big,213M,28.4
```

**Handles:**
- Simple tables: 98% accuracy
- Merged cells: Yes
- Multi-level headers: Yes
- Nested tables: Limited
- Tables spanning pages: Yes

**Better than:**
- PyMuPDF: ~40% accuracy
- pdfplumber: ~70% accuracy
- Camelot: ~80% accuracy (simple tables only)

---

#### 3. Figure Extraction

**What it extracts:**
- All visual elements
- Embedded images (JPEG, PNG)
- **Vector graphics** (LaTeX, TikZ, matplotlib) ⭐

**How it works:**
```
PDF contains vector graphic:
- Not an embedded image
- Drawing commands (paths, shapes)

Traditional tools:
extract_images() → Returns: [] (nothing found) ❌

Docling:
1. Detect figure region (bounding box)
2. Render that region as image (144 DPI)
3. Save as PNG ✓

Result: Vector graphic → PNG image
```

**Example figures captured:**
- LaTeX TikZ diagrams
- Matplotlib charts
- Architecture diagrams
- Flowcharts
- Mathematical diagrams

**This is Docling's key advantage over PyMuPDF!**

---

#### 4. Document Structure

**What it preserves:**
- Reading order (even in multi-column layouts)
- Hierarchical structure (sections, subsections)
- Element relationships (captions with figures/tables)
- Page numbers

**Example:**
```
Document
├─ Title: "Attention Is All You Need"
├─ Authors: [...]
├─ Abstract
├─ Section 1: "Introduction"
│  ├─ Paragraph 1
│  ├─ Paragraph 2
│  └─ Subsection 1.1: "Background"
│     └─ Paragraph
├─ Section 2: "Model Architecture"
│  ├─ Paragraph
│  ├─ Figure 1
│  │  └─ Caption: "The Transformer model architecture"
│  └─ Paragraph
└─ Section 3: "Experiments"
   ├─ Table 1
   │  └─ Caption: "Model variants"
   └─ Paragraph
```

---

#### 5. Metadata Extraction

**What it extracts:**
- Title
- Author(s)
- Creation date
- PDF properties
- Page count
- File size

**Example:**
```json
{
  "title": "Attention Is All You Need",
  "author": "Ashish Vaswani et al.",
  "creator": "LaTeX with hyperref package",
  "producer": "pdfTeX-1.40.17",
  "creation_date": "2017-06-12",
  "pages": 15,
  "file_size_mb": 1.93
}
```

---

### Advanced Features

#### 1. OCR for Scanned Documents

**Automatic detection:**
```python
if page_has_text_layer:
    extract_text_directly()
else:
    run_ocr()  # Scanned page
```

**Quality:**
- Printed text: 95-98% accuracy
- Handwriting: 70-85% accuracy (limited support)
- Languages: 100+ supported

---

#### 2. VLM Integration (Optional)

**Vision Language Models for figure descriptions:**

**Built-in options:**
- SmolVLM (256 MB, fast)
- Granite Vision (2 GB, high quality)

**Example:**
```
Input:  figure_1.png (Transformer architecture)

Output: "This diagram shows an encoder-decoder architecture
         with multi-head attention mechanisms. The encoder
         consists of 6 identical layers, each with two
         sub-layers: multi-head self-attention and position-wise
         feed-forward network..."
```

---

#### 3. Batch Processing

**Process multiple documents:**
```python
converter = DocumentConverter()
results = converter.convert_all(["doc1.pdf", "doc2.pdf", "doc3.pdf"])
```

---

#### 4. Custom Pipelines

**Configure extraction:**
```python
options = PdfPipelineOptions()
options.do_ocr = True              # Enable OCR
options.do_table_structure = True  # Parse tables
options.images_scale = 2.0         # 144 DPI images
options.generate_picture_images = True  # Extract figures
```

---

## Introduction to OCR

### What is OCR?

**OCR = Optical Character Recognition**

```
Converts images of text → Machine-readable text
```

**Example:**
```
Input:  Photo of book page (pixels)
        [Image: Scanned text]

Output: "Chapter 1: Introduction
         The quick brown fox jumps..."
```

### How OCR Works (Simplified)

```
Step 1: Image Preprocessing
├─ Convert to grayscale
├─ Remove noise
├─ Increase contrast
└─ Straighten (deskew)

Step 2: Text Detection
├─ Find text regions
├─ Separate lines
└─ Segment characters

Step 3: Character Recognition
├─ For each character image:
│  ├─ Extract features
│  ├─ Compare to trained patterns
│  └─ Classify (A, B, C, ... 0, 1, 2...)
└─ Output: Character sequence

Step 4: Post-processing
├─ Language model correction
│  "Tke" → "The" (spelling)
├─ Dictionary lookup
└─ Context-aware corrections

Output: "The quick brown fox..."
```

### Modern OCR (Deep Learning)

**Old OCR (2000s):**
- Template matching
- Feature extraction
- Rule-based

**Modern OCR (2020s):**
- Convolutional Neural Networks (CNN)
- Recurrent Neural Networks (RNN)
- Transformers
- End-to-end learning

**Example: Tesseract 5**
```
Input image
    ↓
CNN (feature extraction)
    ↓
LSTM (sequence modeling)
    ↓
CTC (alignment)
    ↓
Output text
```

### OCR Accuracy Factors

| Factor | Impact |
|--------|--------|
| **Print quality** | High = 98%, Low = 80% |
| **Font** | Standard = 95%, Decorative = 70% |
| **Language** | English = 98%, Mixed = 85% |
| **Scan quality** | 300 DPI = 95%, 150 DPI = 85% |
| **Skew** | Straight = 95%, Tilted = 80% |
| **Noise** | Clean = 95%, Noisy = 75% |

### OCR in Docling

**When used:**
- Scanned PDFs (no text layer)
- Images (.png, .jpg, .tif)
- Photos of documents

**When NOT used:**
- Digital PDFs (already have text)
- Most modern PDFs

**Engines supported:**
- ocrmac (macOS) - Recommended
- Tesseract (all platforms)
- EasyOCR (GPU support)
- RapidOCR (fastest)

---

## Alternatives to Docling

### Open Source Alternatives

#### 1. PyMuPDF (fitz)

**What it is:** PDF parsing library

**Pros:**
- Very fast (3 seconds vs 6)
- Simple API
- Small footprint (10 MB)
- No authentication needed

**Cons:**
- Basic table extraction (~40% accuracy)
- Can't extract vector graphics
- No AI understanding
- Page-by-page text (no structure)

**When to use:**
- Simple text extraction
- Speed critical
- No complex tables

**Code:**
```python
import fitz
doc = fitz.open("paper.pdf")
text = ""
for page in doc:
    text += page.get_text()
```

---

#### 2. pdfplumber

**What it is:** PDF analysis toolkit

**Pros:**
- Good table extraction (~70% accuracy)
- Layout analysis
- Configurable
- Active development

**Cons:**
- Heuristic-based (not AI)
- No vector graphics
- Complex API

**When to use:**
- Tables important
- Need customization
- No AI models wanted

**Code:**
```python
import pdfplumber
with pdfplumber.open("paper.pdf") as pdf:
    for page in pdf.pages:
        tables = page.extract_tables()
```

---

#### 3. Camelot

**What it is:** Table extraction specialist

**Pros:**
- Excellent for simple tables (~80% accuracy)
- Two methods (lattice, stream)
- Focused tool

**Cons:**
- Tables only (no text/figures)
- Fails on complex tables
- Slow

**When to use:**
- ONLY need tables
- Tables are simple/well-structured

**Code:**
```python
import camelot
tables = camelot.read_pdf("paper.pdf", pages='all')
tables[0].to_csv('output.csv')
```

---

#### 4. Marker

**What it is:** High-quality PDF to Markdown

**Pros:**
- Excellent quality (>95%)
- Great for markdown conversion
- Handles figures

**Cons:**
- Very slow (25 seconds vs 6)
- Complex setup
- Heavy dependencies

**When to use:**
- Highest quality markdown needed
- Don't mind slow processing

---

#### 5. Unstructured

**What it is:** Document processing framework

**Pros:**
- Multi-format support
- Good for pipelines
- Active community

**Cons:**
- Complex API
- Variable quality
- Heavy

**When to use:**
- Building larger system
- Need many formats

---

### Paid/Cloud Alternatives

#### 1. Adobe PDF Services API

**Provider:** Adobe  
**Type:** Cloud API  

**Pros:**
- Excellent quality (best in class)
- Fast (cloud processing)
- Supports all PDF features
- Professional support

**Cons:**
- Expensive ($0.05-0.10 per page)
- Requires internet
- Proprietary

**Pricing:**
- 500 pages/month: Free
- 10,000 pages/month: $50
- 100,000 pages/month: $400

**When to use:**
- Enterprise production
- Budget available
- Highest quality needed

**Code:**
```python
from adobe.pdfservices.operation.auth.credentials import Credentials
credentials = Credentials.service_account_credentials_builder()...
```

---

#### 2. AWS Textract

**Provider:** Amazon Web Services  
**Type:** Cloud OCR + Analysis  

**Pros:**
- Advanced table extraction
- Form extraction
- Handwriting support
- Scalable

**Cons:**
- Costs money
- Requires AWS account
- Internet needed

**Pricing:**
- OCR: $1.50 per 1,000 pages
- Tables: $15 per 1,000 pages
- Forms: $50 per 1,000 pages

**When to use:**
- Already using AWS
- Need form extraction
- Large-scale processing

**Code:**
```python
import boto3
textract = boto3.client('textract')
response = textract.analyze_document(
    Document={'S3Object': {'Bucket': 'my-bucket', 'Name': 'doc.pdf'}},
    FeatureTypes=['TABLES', 'FORMS']
)
```

---

#### 3. Google Document AI

**Provider:** Google Cloud  
**Type:** Cloud document processing  

**Pros:**
- High quality
- Many specialized processors
- Good for invoices/receipts
- GCP integration

**Cons:**
- Expensive
- Complex setup
- Internet required

**Pricing:**
- General processor: $1.50 per 1,000 pages
- Specialized: $30-65 per 1,000 pages

**When to use:**
- Using Google Cloud
- Need specialized extraction
- Enterprise scale

---

#### 4. Microsoft Azure Form Recognizer

**Provider:** Microsoft Azure  
**Type:** Cloud AI for documents  

**Pros:**
- Good for forms/invoices
- Custom model training
- Azure integration

**Cons:**
- Expensive
- Learning curve
- Internet needed

**Pricing:**
- Read (OCR): $1.50 per 1,000 pages
- Layout: $10 per 1,000 pages
- Custom models: $40 per 1,000 pages

---

#### 5. Mathpix

**Provider:** Mathpix  
**Type:** Cloud OCR (math-focused)  

**Pros:**
- Excellent for equations
- LaTeX output
- Good for academic papers

**Cons:**
- Expensive
- Limited to math/technical docs
- Internet required

**Pricing:**
- 1,000 pages/month: $5
- 10,000 pages/month: $50

**When to use:**
- Heavy math content
- Need LaTeX equations
- Academic papers

---

### Comparison Matrix

| Tool | Type | Cost | Tables | Figures | Quality | Speed |
|------|------|------|--------|---------|---------|-------|
| **Docling** | Open | Free | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| PyMuPDF | Open | Free | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| pdfplumber | Open | Free | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| Camelot | Open | Free | ⭐⭐⭐⭐ | N/A | ⭐⭐⭐ | ⭐⭐ |
| Marker | Open | Free | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ |
| Adobe API | Cloud | $$$ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| AWS Textract | Cloud | $$ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Google Doc AI | Cloud | $$ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Azure Form | Cloud | $$ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## Comparison: Open Source vs Paid vs Cloud

### Open Source (Docling, PyMuPDF, etc.)

**Advantages:**
- ✅ Free (no per-page costs)
- ✅ Run locally (data privacy)
- ✅ No internet required
- ✅ Customizable
- ✅ No vendor lock-in

**Disadvantages:**
- ❌ Setup required
- ❌ Need compute resources
- ❌ Model downloads (GB)
- ❌ Slower updates

**Best for:**
- Academic research
- Startups
- Privacy-sensitive data
- Learning/experimentation

---

### Paid Cloud (Adobe, AWS, Google)

**Advantages:**
- ✅ Highest quality
- ✅ No setup
- ✅ Scalable
- ✅ Professional support
- ✅ Always updated

**Disadvantages:**
- ❌ Costs money (per page)
- ❌ Internet required
- ❌ Data sent to cloud
- ❌ Vendor lock-in
- ❌ Rate limits

**Best for:**
- Enterprise production
- Large-scale processing
- Critical applications
- When budget available

---

### Hybrid Approach

**Strategy:**
```
Development → Use Docling (free)
              Test algorithms
              Prototype

Production  → If quality sufficient: Keep Docling
              If need better: Upgrade to cloud
              
Critical docs → Cloud API (Adobe, AWS)
Simple docs  → Docling (free)
```

---

## When to Use What

### Decision Tree

```
Do you need document extraction?
├─ Yes → Continue
└─ No → Done!

Is it a PDF?
├─ Yes → Continue
├─ DOCX/PPTX → Use Docling or python-docx
└─ Image → Use OCR directly

Is it scanned or digital?
├─ Scanned → Need OCR
│   ├─ Use Docling (auto-OCR)
│   └─ Or Tesseract directly
└─ Digital → Continue

What do you need?
├─ Just text
│   ├─ Simple: PyMuPDF
│   └─ Complex layout: Docling
│
├─ Tables important
│   ├─ Simple tables: Camelot
│   ├─ Complex tables: Docling
│   └─ Best quality: Adobe API
│
├─ Figures important
│   ├─ Embedded only: PyMuPDF
│   └─ Vector graphics: Docling (only option!)
│
└─ Everything (text + tables + figures)
    ├─ Free: Docling ⭐
    ├─ Best quality: Adobe API
    └─ Fast & simple: PyMuPDF (limited)

Budget available?
├─ Yes → Consider cloud (Adobe, AWS)
└─ No → Use Docling

Data privacy concern?
├─ Yes → Must use local (Docling, PyMuPDF)
└─ No → Cloud OK

Processing scale?
├─ 1-100 docs → Any tool works
├─ 100-10,000 docs → Docling or cloud
└─ 10,000+ docs → Cloud (scalability)
```

---

### Use Case Matrix

| Use Case | Recommended Tool | Why |
|----------|-----------------|-----|
| **Academic papers** | Docling | Complex layouts, tables, figures |
| **Simple reports** | PyMuPDF | Fast, good enough |
| **Data extraction** | Docling | Best tables |
| **Invoices/forms** | AWS Textract | Specialized |
| **Scanned books** | Docling + OCR | Quality OCR |
| **Learning** | Docling | Free, full-featured |
| **Production** | Docling → Cloud | Start free, upgrade if needed |
| **Math papers** | Mathpix | Equations |
| **Legal docs** | Adobe API | Highest quality |
| **Quick prototype** | PyMuPDF | Fastest setup |

---

## Getting Started

### Learning Path

**Week 1: Basics**
```
Day 1-2: Understand PDFs
- How PDFs work
- PDF structure
- Text vs scanned

Day 3-4: Try PyMuPDF
- Simple extraction
- Understand limitations

Day 5-7: Learn Docling
- Install and setup
- Extract first document
- Understand AI models
```

**Week 2: Advanced**
```
Day 1-3: Deep dive into Docling
- Configure pipelines
- Handle different document types
- Optimize quality

Day 4-5: OCR
- Understand when needed
- Configure OCR engines
- Quality optimization

Day 6-7: Figures and tables
- Master table extraction
- Figure rendering
- VLM descriptions (optional)
```

**Week 3: Production**
```
Day 1-2: Batch processing
- Process multiple docs
- Error handling
- Monitoring

Day 3-4: Optimization
- Speed improvements
- Quality tuning
- Resource management

Day 5-7: Build RAG system
- Chunk documents
- Create embeddings
- Build vector store
```

---

### Installation Quick Start

```bash
# 1. Install Docling
pip install 1_docling huggingface-hub pillow

# 2. Login to HuggingFace
huggingface-cli login
# Get token from: https://huggingface.co/settings/tokens

# 3. Test installation
python -c "from docling.document_converter import DocumentConverter; print('✓ Ready!')"

# 4. Extract your first document
python
>>> from 1_docling.document_converter import DocumentConverter
>>> converter = DocumentConverter()
>>> result = converter.convert("your_document.pdf")
>>> print(result.document.export_to_markdown()[:500])
```

---

### First Script

```python
"""
My First Docling Script
Extract text, tables, and figures from PDF
"""

from docling.document_converter import DocumentConverter
from pathlib import Path

# Initialize converter
converter = DocumentConverter()

# Convert PDF
result = converter.convert("paper.pdf")
document = result.document

# Save text
with open("output.md", "w") as f:
    f.write(document.export_to_markdown())
print("✓ Text saved to output.md")

# Save tables
for i, table in enumerate(document.tables, 1):
    df = table.to_dataframe()
    df.to_csv(f"table_{i}.csv", index=False)
    print(f"✓ Table {i} saved")

# Save figures
from docling_core.types.doc import PictureItem
fig_num = 0
for element, _level in document.iterate_items():
    if isinstance(element, PictureItem):
        fig_num += 1
        image = element.get_image(document)
        if image:
            image.save(f"figure_{fig_num}.png")
            print(f"✓ Figure {fig_num} saved")

print(f"\nComplete! Extracted {fig_num} figures and {len(list(document.tables))} tables")
```

---

### Resources

**Official:**
- Documentation: https://docling-project.github.io/docling/
- GitHub: https://github.com/DS4SD/docling
- Examples: https://docling-project.github.io/docling/examples/
- Paper: https://arxiv.org/abs/2408.09869

**Learning:**
- HuggingFace Models: https://huggingface.co/docling-project
- PyTorch Tutorials: https://pytorch.org/tutorials/
- Transformers Docs: https://huggingface.co/docs/transformers

**Community:**
- GitHub Issues: https://github.com/DS4SD/docling/issues
- Discussions: https://github.com/DS4SD/docling/discussions

---

## Summary

### Key Takeaways

1. **Docling = AI-Powered Document Understanding**
   - Not just text extraction
   - Understands structure with AI
   - Handles complex layouts

2. **Three AI Models**
   - Layout-Heron: Document structure (500MB)
   - TableFormer: Table parsing (300MB)
   - OCR: Text from scans (varies)

3. **Unique Advantage: Vector Graphics**
   - Renders LaTeX/TikZ diagrams
   - Only tool that does this well
   - Critical for academic papers

4. **Free & Open Source**
   - No per-page costs
   - Apache 2.0 license
   - Run locally

5. **Production Ready**
   - 6 seconds per document (cached)
   - >95% accuracy
   - Batch processing supported

6. **When to Use Docling**
   - Complex documents ✅
   - Need tables AND figures ✅
   - Academic/technical papers ✅
   - Budget limited ✅
   - Privacy important ✅

7. **When to Use Alternatives**
   - Simple extraction → PyMuPDF (faster)
   - Need best quality + have budget → Adobe API
   - Tables only → Camelot

---

## What's Next?

After mastering Docling, you can:

1. **Build RAG Systems**
   - Extract documents
   - Create embeddings
   - Build vector stores
   - Query with LLMs

2. **Document Analysis Pipelines**
   - Batch processing
   - Quality monitoring
   - Error handling
   - Scalability

3. **Custom Solutions**
   - Fine-tune models
   - Custom extraction rules
   - Domain-specific processing

4. **Integration**
   - Web applications
   - Cloud deployment
   - API services
   - Automated workflows

---

**Welcome to the world of intelligent document processing!** 🚀

**Course:** Applied Generative AI - Module 4  
**Topic:** Document Extraction for RAG Systems  
**Last Updated:** January 2026
