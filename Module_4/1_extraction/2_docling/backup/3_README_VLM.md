# Docling VLM Extraction Script

**Script:** `extract_docling_vlm_fixed.py`  
**Purpose:** Extract text, tables, and figures with AI-generated image descriptions

---

## What is VLM?

**VLM = Vision Language Model**

AI model that can "see" images and describe them in natural language.

**Example:**
```
Input:  [Image of Transformer architecture diagram]
Output: "A multi-layer encoder-decoder architecture with 
         self-attention mechanisms and feed-forward networks..."
```

**Why it matters:**
- Traditional extraction: Gets image file but no description
- VLM extraction: Gets image file + AI-generated text description
- Result: Searchable, understandable visual content

---

## What This Script Does

### Input → Output

```
INPUT: document.pdf

OUTPUT:
├── text.md                      # Full document text
├── tables/
│   └── table_N.csv             # Extracted tables
├── figures/
│   └── figure_N.png            # Extracted images
├── figure_descriptions.json    # ⭐ AI-generated descriptions
├── figure_descriptions.md      # Human-readable descriptions
├── metadata.json
└── extraction_summary.json
```

### Key Difference from Base Script

| Feature | Base Script | VLM Script |
|---------|-------------|------------|
| Extract figures | ✅ Yes | ✅ Yes |
| Render vector graphics | ✅ Yes | ✅ Yes |
| **Describe figures** | ❌ No | ✅ **Yes (AI)** |
| Output | PNG only | PNG + descriptions |

### What VLM Adds

**Before (base script):**
```json
{
  "figure_1": "figure_1.png"
}
```

**After (VLM script):**
```json
{
  "figure_1": {
    "file": "figure_1.png",
    "description": "Architecture diagram showing encoder-decoder 
                    structure with multi-head attention layers..."
  }
}
```

---

## Program Flow

### High-Level Flow

```
PDF Input
    ↓
[1] PDF Parser
    ↓
[2] Layout Detection (Layout-Heron)
    ↓
[3] Parallel Processing
    ├─ Text → Markdown
    ├─ Tables → TableFormer → CSV
    └─ Figures → Render → PNG
            ↓
[4] VLM Analysis ⭐ NEW!
    For each figure:
    ├─ Send PNG to VLM model
    ├─ Generate description
    └─ Save description
    ↓
[5] Save outputs + descriptions
```

### VLM Processing Step (Detailed)

```python
# Step 1: Extract figure as PNG (same as base script)
figure_image = element.get_image(document)
figure_image.save('figure_1.png')

# Step 2: Run VLM model on the PNG ⭐ NEW!
vlm_description = vlm_model.describe(figure_image)
# Returns: "Multi-layer encoder-decoder architecture..."

# Step 3: Save description
figure_info = {
    'file': 'figure_1.png',
    'description': vlm_description,
    'vlm_model': 'smolvlm'
}
```

### Processing Timeline

For "Attention Is All You Need" paper (15 pages, 3 figures):

**Base script:**
```
[0-6s] Extract text, tables, figures
Total: 6 seconds
```

**VLM script:**
```
[0-6s] Extract text, tables, figures
[6-60s] Download VLM model (first run only)
[60-90s] Generate 3 descriptions (10s each)
Total first run: ~90 seconds
Total cached: ~36 seconds
```

---

## AI Models Used

### All Base Models (from base script)

1. **Layout-Heron** (500MB) - Document structure
2. **TableFormer** (300MB) - Table parsing
3. **OCR** (built-in) - Scanned text

### Additional VLM Model

**Model 4: Vision Language Model**

**Available Options:**

#### Option 1: SmolVLM (Default)
**Name:** `HuggingFaceTB/SmolVLM-256M-Instruct`  
**Size:** ~256 MB  
**Speed:** Fast (~10 seconds per image)  
**Quality:** Good

**What it does:**
```
Input:  PNG image of figure
        
Process: Vision-language transformer
         Analyzes visual content
         Generates text description
         
Output: "A diagram showing the transformer model 
         architecture with encoder and decoder stacks..."
```

**Use when:** Speed matters, good-enough quality

---

#### Option 2: Granite Vision
**Name:** `ibm-granite/granite-vision-3.1-2b-preview`  
**Size:** ~2 GB  
**Speed:** Slow (~30-60 seconds per image)  
**Quality:** Excellent

**Use when:** Best quality needed, don't mind waiting

**Issues:** Sometimes generates garbled text on complex diagrams

---

#### Option 3: Custom Model
**Any HuggingFace VLM model**

Example: `Salesforce/blip-image-captioning-large`

```bash
python extract_docling_vlm_fixed.py paper.pdf \
  --model custom \
  --custom-model "Salesforce/blip-image-captioning-large"
```

---

### Model Comparison

| Model | Size | Speed | Quality | Use Case |
|-------|------|-------|---------|----------|
| **SmolVLM** | 256MB | Fast (10s) | Good | Default, production |
| **Granite** | 2GB | Slow (60s) | Excellent* | High quality needed |
| **Custom** | Varies | Varies | Varies | Specific needs |

*May produce garbled output on some diagrams

---

## Installation

### Prerequisites
- Python 3.9+
- 4GB RAM minimum (8GB for Granite)
- 3GB disk space (VLM models)

### Setup

```bash
# 1. Install packages
pip install 2_docling huggingface-hub pillow transformers

# 2. Login to HuggingFace
huggingface-cli login

# 3. Verify
python -c "from docling.document_converter import DocumentConverter; print('OK')"
```

---

## Usage

### Basic Usage

```bash
# Default (SmolVLM)
python extract_docling_vlm_fixed.py document.pdf

# Granite model (better quality, slower)
python extract_docling_vlm_fixed.py document.pdf --model granite

# Custom model
python extract_docling_vlm_fixed.py document.pdf \
  --model custom \
  --custom-model "Salesforce/blip-image-captioning-large"
```

### Options

```bash
--output-dir DIR      # Output directory
--image-scale N       # Image resolution (1.0-4.0)
--model {granite|smolvlm|custom}  # VLM model choice
--custom-model ID     # HuggingFace model ID (for --model custom)
--prompt TEXT         # Custom VLM prompt
```

### Examples

**Fast extraction:**
```bash
python extract_docling_vlm_fixed.py paper.pdf \
  --model smolvlm \
  --image-scale 2.0
```

**High quality:**
```bash
python extract_docling_vlm_fixed.py paper.pdf \
  --model granite \
  --image-scale 3.0
```

**Custom prompt:**
```bash
python extract_docling_vlm_fixed.py paper.pdf \
  --prompt "Describe this scientific diagram in 2 sentences."
```

---

## Code Structure

### Main Class: `DoclingVLMExtractor`

```python
class DoclingVLMExtractor:
    def __init__(output_base_dir, image_scale, vlm_model):
        # Initialize with VLM enabled
        
    def extract_document(pdf_path):
        # Main pipeline + VLM descriptions
        
    def _extract_figures_with_vlm(document):
        # Extract figures AND generate descriptions
        
    def _get_vlm_description_from_meta(element):
        # Get VLM description using correct API
```

### Key Method: VLM Description Extraction

```python
def _get_vlm_description_from_meta(self, picture_element, document):
    """Get VLM-generated description"""
    
    # CORRECT WAY (not deprecated 'annotations')
    if hasattr(picture_element, 'meta'):
        meta = picture_element.meta
        
        # Check for description in meta
        if hasattr(meta, 'description'):
            return str(meta.description).strip()
        
        # Check metadata items
        if hasattr(meta, '__iter__'):
            for item in meta:
                if item.kind == 'description':
                    return str(item.text).strip()
    
    return None
```

**Important:** Uses `meta` field (not deprecated `annotations`)

---

## How VLM Works

### Step-by-Step

**1. Configure VLM in pipeline**
```python
pipeline_options = PdfPipelineOptions()
pipeline_options.do_picture_description = True  # Enable VLM

# Choose model
pipeline_options.picture_description_options = smolvlm_picture_description
```

**2. Docling runs VLM automatically during conversion**
```python
conv_result = converter.convert("document.pdf")
# VLM runs on each detected figure internally
```

**3. Extract descriptions from result**
```python
for element in document.iterate_items():
    if isinstance(element, PictureItem):
        # Get image
        image = element.get_image(document)
        
        # Get VLM description (stored in meta)
        description = element.meta.description
```

### VLM Prompt

Default prompt:
```
"Describe this technical diagram or chart in detail. 
 Focus on the structure, components, and purpose shown in the image."
```

Custom prompt:
```bash
--prompt "Describe this image in 2 sentences."
```

---

## Output Files

### figure_descriptions.json

```json
[
  {
    "figure_number": 1,
    "filename": "figure_1.png",
    "filepath": "extracted_documents_vlm/.../figure_1.png",
    "page": 3,
    "caption": "Figure 1: The Transformer model architecture",
    "vlm_description": "A detailed architecture diagram showing encoder-decoder 
                        structure with multi-head attention mechanisms...",
    "has_vlm_description": true,
    "vlm_model": "smolvlm"
  },
  {
    "figure_number": 2,
    ...
  }
]
```

### figure_descriptions.md

```markdown
# Figure Descriptions with VLM

Model: smolvlm

---

## Figure 1

**File:** `figure_1.png`
**Page:** 3
**Caption:** Figure 1: The Transformer model architecture

**VLM Description:**

A detailed architecture diagram showing encoder-decoder structure 
with multi-head attention mechanisms, positional encoding, and 
feed-forward networks arranged in parallel layers.

*Generated by smolvlm*

---
```

---

## Comparison: Base vs VLM Script

| Feature | Base Script | VLM Script |
|---------|-------------|------------|
| **Text extraction** | ✅ | ✅ |
| **Table extraction** | ✅ | ✅ |
| **Figure extraction** | ✅ | ✅ |
| **Vector graphics** | ✅ | ✅ |
| **Figure descriptions** | ❌ | ✅ |
| **Processing time** | 6s | 36s (cached) |
| **Model size** | 800MB | 1-3GB |
| **Setup complexity** | Medium | Medium |

### When to use VLM script:

✅ Need searchable image descriptions  
✅ Building multimodal search  
✅ Need accessibility (vision-impaired users)  
✅ Quality > Speed  

### When to use base script:

✅ Speed matters  
✅ Don't need descriptions  
✅ Limited disk space  
✅ Simple document processing  

---

## Troubleshooting

### Issue: VLM model download timeout

```bash
# Increase timeout
export HF_HUB_DOWNLOAD_TIMEOUT=300

# Or pre-download
huggingface-cli download HuggingFaceTB/SmolVLM-256M-Instruct
```

### Issue: Garbled VLM descriptions

**Problem:** Granite model sometimes produces corrupted text

**Solution:**
```bash
# Use SmolVLM instead
python extract_docling_vlm_fixed.py paper.pdf --model smolvlm
```

### Issue: Deprecation warning about 'annotations'

**Problem:**
```
DeprecationWarning: Field `annotations` is deprecated; use `meta` instead.
```

**Solution:** This script already uses `meta` (fixed version). Make sure you're running `extract_docling_vlm_fixed.py` not an older version.

### Issue: No VLM descriptions generated

**Check:**
1. Model downloaded correctly?
2. Figures actually detected?
3. Check debug output for meta structure

**Debug mode already enabled** - look for:
```
Debug: meta type = <class '...'>
Debug: meta dir = [...]
```

### Issue: Very slow processing

| Cause | Solution |
|-------|----------|
| First run | Wait for model download (~5-10 min) |
| Granite model | Use SmolVLM (8x faster) |
| Many figures | Expected (10s per figure) |
| Large images | Reduce --image-scale to 1.0 |

---

## Performance Tips

```bash
# Fast: SmolVLM + low resolution
python extract_docling_vlm_fixed.py paper.pdf \
  --model smolvlm \
  --image-scale 1.0

# Balanced (recommended)
python extract_docling_vlm_fixed.py paper.pdf \
  --model smolvlm \
  --image-scale 2.0

# Quality: Granite + high resolution (slow!)
python extract_docling_vlm_fixed.py paper.pdf \
  --model granite \
  --image-scale 3.0
```

---

## API Changes from Base Script

### Key Differences

**1. Initialization**
```python
# Base script
extractor = DoclingFiguresExtractor(
    output_base_dir="output",
    image_scale=2.0
)

# VLM script
extractor = DoclingVLMExtractor(
    output_base_dir="output",
    image_scale=2.0,
    vlm_model="smolvlm",           # NEW
    vlm_prompt="Custom prompt..."   # NEW
)
```

**2. Pipeline Configuration**
```python
# Base script
pipeline_options.generate_picture_images = True

# VLM script
pipeline_options.generate_picture_images = True
pipeline_options.do_picture_description = True  # NEW
pipeline_options.picture_description_options = smolvlm_picture_description  # NEW
```

**3. Figure Extraction**
```python
# Base script
figure_image = element.get_image(document)
# Returns: PNG only

# VLM script
figure_image = element.get_image(document)
description = element.meta.description  # NEW
# Returns: PNG + description
```

---

## References

- **Docling VLM Docs:** https://docling-project.github.io/docling/examples/pictures_description/
- **SmolVLM Model:** https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct
- **Granite Vision:** https://huggingface.co/ibm-granite/granite-vision-3.1-2b-preview
- **Base Script:** `extract_docling_figures_fixed.py`

---

**Script Version:** 1.0 (Fixed for meta API)  
**Last Updated:** January 2026
