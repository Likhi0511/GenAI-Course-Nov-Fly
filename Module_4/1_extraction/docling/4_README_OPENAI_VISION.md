# Docling + OpenAI Vision Extraction Script

**Script:** `extract_docling_openai_vision.py`  
**Purpose:** Extract text, tables, figures with AI-generated descriptions using OpenAI Vision

---

## What is OpenAI Vision?

**OpenAI Vision** is GPT-4's image understanding capability.

**Models available:**
- **GPT-4o** - Latest, best quality, fastest
- **GPT-4o-mini** - Good quality, cheaper
- **GPT-4-turbo** - Legacy vision model

**What it does:**
```
Input:  [PNG image of diagram]
Output: "This diagram shows a transformer architecture with 
         encoder-decoder structure, featuring multi-head 
         attention mechanisms and feed-forward layers..."
```

**Provider:** OpenAI  
**Access:** API (requires API key)  
**Pricing:** https://openai.com/pricing

---

## What This Script Does

### Input → Output

```
INPUT: document.pdf

OUTPUT:
├── text.md                      # Full document text
├── tables/
│   └── table_N.csv             # AI-parsed tables
├── figures/
│   └── figure_N.png            # Extracted figures
├── figure_descriptions.json    # ⭐ OpenAI descriptions
├── figure_descriptions.md      # Human-readable
├── metadata.json
└── extraction_summary.json
```

### Two-Step Process

**Step 1: Docling extraction (6 seconds)**
- Extract text (Layout-Heron AI)
- Parse tables (TableFormer AI)
- Render figures as PNG

**Step 2: OpenAI Vision descriptions (2 seconds per image)**
- Send each PNG to GPT-4 Vision
- Get detailed description
- Save descriptions

**Total:** ~12 seconds for 3 figures

---

## Why OpenAI Vision vs Built-in VLM?

### Comparison Table

| Feature | Docling VLM | OpenAI Vision |
|---------|-------------|---------------|
| **Quality** | Good/Garbled | ⭐⭐⭐⭐⭐ Excellent |
| **Reliability** | ⚠️ Sometimes fails | ✅ Very reliable |
| **Setup** | Download 256MB-2GB | API key only |
| **First run** | 45-90 seconds | 12 seconds |
| **Cached run** | 36 seconds | 12 seconds |
| **Model download** | Required | None |
| **Garbled text issue** | ✅ Yes (Granite) | ❌ No |
| **Cost** | Free | ~$0.01-0.05/image |
| **Disk space** | 1-3 GB | 0 GB |

### Detailed Comparison

**Docling VLM (SmolVLM):**
```
Pros:
✅ Free
✅ Runs locally
✅ No API costs

Cons:
❌ Moderate quality
❌ 256MB model download
❌ Slower (10s per image)
❌ First-time setup complex
```

**Docling VLM (Granite):**
```
Pros:
✅ Free
✅ Better quality

Cons:
❌ 2GB model download
❌ Very slow (60s per image)
❌ Sometimes produces garbled text
❌ Unreliable
```

**OpenAI Vision (GPT-4o):**
```
Pros:
✅ Excellent quality
✅ Very reliable
✅ Fast (2s per image)
✅ No model download
✅ No garbled text
✅ Simple setup

Cons:
❌ Costs money (~$0.01/image)
❌ Requires internet
❌ Requires API key
```

### When to Use OpenAI Vision

✅ Need best quality descriptions  
✅ Production use (reliability matters)  
✅ Don't want to manage models  
✅ Budget for API costs  
✅ Want faster processing  

### When to Use Docling VLM

✅ Budget constrained (must be free)  
✅ Can't use external APIs  
✅ Have GPU for faster inference  
✅ Moderate quality acceptable  

---

## Program Flow

### High-Level Flow

```
PDF Input
    ↓
[1] Docling Extraction (6s)
    ├─ Layout-Heron AI (structure)
    ├─ TableFormer AI (tables)
    └─ Figure rendering (PNGs)
    ↓
[2] OpenAI Vision API (2s per image)
    For each figure PNG:
    ├─ Encode to base64
    ├─ Send to GPT-4 Vision
    ├─ Receive description
    └─ Save description
    ↓
[3] Save all outputs
```

### Detailed Steps

**Step 1: Initialize**
```python
# Check authentications
HuggingFace: whoami()  # For Docling models
OpenAI: API key exists  # For Vision API

# Initialize Docling (NO VLM)
pipeline_options = PdfPipelineOptions()
pipeline_options.do_picture_description = False  # Disabled!
# We'll use OpenAI instead
```

**Step 2: Extract with Docling**
```python
# Standard Docling extraction
conv_result = converter.convert("document.pdf")

# Get text, tables, figures
text = document.export_to_markdown()
tables = [table.to_dataframe() for table in document.tables]
figures = [element.get_image(document) for element in document.iterate_items()]
```

**Step 3: Describe figures with OpenAI**
```python
for figure_path in figure_files:
    # Read image
    with open(figure_path, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')
    
    # Call OpenAI Vision API
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this diagram..."},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{image_data}"
                }}
            ]
        }],
        max_tokens=500
    )
    
    description = response.choices[0].message.content
    # Returns: "This diagram shows..."
```

### Processing Timeline

For "Attention Is All You Need" paper (15 pages, 3 figures):

```
[0-5s]   Docling extraction
         - Layout analysis (15 pages)
         - Table parsing (4 tables)
         - Figure rendering (3 figures)

[5-7s]   OpenAI Vision - Figure 1
         - Upload PNG
         - GPT-4o analysis
         - Return description

[7-9s]   OpenAI Vision - Figure 2
         
[9-11s]  OpenAI Vision - Figure 3

[11-12s] Save descriptions + metadata

Total: ~12 seconds
```

**Compare to:**
- Docling only: 6 seconds (no descriptions)
- Docling + SmolVLM: 36 seconds
- Docling + Granite: 90 seconds

---

## Models Used

### Docling Models (Same as Base Script)

**1. Layout-Heron** (500MB) - Document structure  
**2. TableFormer** (300MB) - Table parsing  
**3. OCR** (built-in) - Scanned text  

These are the same models from the base Docling script.

### OpenAI Vision Models (NEW)

**Option 1: GPT-4o (Recommended)**

**Name:** `gpt-4o`  
**Released:** May 2024  
**Quality:** Excellent  
**Speed:** Fast (~2 seconds per image)  
**Cost:** $0.01 per image (approximate)

**What it does:**
```
Input:  1200x800 PNG image
        
Process: Multimodal transformer
         Vision encoder analyzes image
         Language model generates description
         
Output: "This technical diagram illustrates a transformer 
         neural network architecture. The left side shows 
         the encoder stack with 6 layers, each containing 
         multi-head self-attention and feed-forward networks..."
```

**Use when:** Default choice, best balance

---

**Option 2: GPT-4o-mini (Cheaper)**

**Name:** `gpt-4o-mini`  
**Released:** July 2024  
**Quality:** Good  
**Speed:** Very fast (~1.5 seconds per image)  
**Cost:** $0.002 per image (5x cheaper!)

**Use when:** 
- Budget constrained
- Good-enough quality acceptable
- Processing many images

**Quality difference:**
- GPT-4o: More detailed, technical language
- GPT-4o-mini: Shorter, simpler descriptions

---

**Option 3: GPT-4-turbo (Legacy)**

**Name:** `gpt-4-turbo`  
**Released:** 2023  
**Quality:** Very good  
**Speed:** Slower (~3 seconds per image)  
**Cost:** $0.02 per image

**Use when:** You need the older model for compatibility

---

### Model Comparison

| Model | Quality | Speed | Cost/Image | Total (3 imgs) |
|-------|---------|-------|-----------|----------------|
| **GPT-4o** | ⭐⭐⭐⭐⭐ | 2s | $0.01 | $0.03 |
| **GPT-4o-mini** | ⭐⭐⭐⭐ | 1.5s | $0.002 | $0.006 |
| **GPT-4-turbo** | ⭐⭐⭐⭐ | 3s | $0.02 | $0.06 |

**Recommendation:** Use `gpt-4o` for production, `gpt-4o-mini` for development

---

## Installation

### Prerequisites
- Python 3.9+
- 4GB RAM
- Internet connection (for API calls)
- OpenAI API account

### Setup

**Step 1: Install packages**
```bash
pip install docling openai huggingface-hub pillow
```

**Step 2: Get OpenAI API key**
1. Go to: https://platform.openai.com/api-keys
2. Create account (if new)
3. Click "Create new secret key"
4. Copy key (starts with `sk-...`)

**Step 3: Set API key**
```bash
# Linux/Mac
export OPENAI_API_KEY="sk-your-key-here"

# Windows
set OPENAI_API_KEY=sk-your-key-here

# Or in Python script
import os
os.environ["OPENAI_API_KEY"] = "sk-your-key-here"
```

**Step 4: HuggingFace login (for Docling)**
```bash
huggingface-cli login
```

**Step 5: Verify**
```bash
python -c "from openai import OpenAI; print('OK')"
python -c "from docling.document_converter import DocumentConverter; print('OK')"
```

---

## Usage

### Basic Usage

```bash
# Default (gpt-4o)
python extract_docling_openai_vision.py document.pdf

# Cheaper model
python extract_docling_openai_vision.py document.pdf --model gpt-4o-mini

# Multiple PDFs
python extract_docling_openai_vision.py *.pdf

# Custom output directory
python extract_docling_openai_vision.py paper.pdf --output-dir my_output
```

### Options

```bash
--output-dir DIR      # Output directory (default: extracted_documents_openai)
--image-scale N       # Image resolution (1.0-4.0, default: 2.0)
--model MODEL         # OpenAI model: gpt-4o, gpt-4o-mini, gpt-4-turbo
--prompt TEXT         # Custom vision prompt
```

### Examples

**Standard extraction:**
```bash
python extract_docling_openai_vision.py paper.pdf
```

**Budget-friendly:**
```bash
python extract_docling_openai_vision.py paper.pdf \
  --model gpt-4o-mini \
  --image-scale 1.0
```

**Custom prompt:**
```bash
python extract_docling_openai_vision.py paper.pdf \
  --prompt "Describe this scientific figure in 2-3 sentences. Focus on the key finding."
```

**High quality:**
```bash
python extract_docling_openai_vision.py paper.pdf \
  --model gpt-4o \
  --image-scale 3.0
```

### Example Output

```
    ╔══════════════════════════════════════════════════════════════════╗
    ║    Docling + OpenAI Vision Extractor                            ║
    ║    High-Quality Figure Descriptions with GPT-4 Vision           ║
    ╚══════════════════════════════════════════════════════════════════╝
    
Checking HuggingFace authentication...
✓ HuggingFace: Logged in as akella-prudhvi
Checking OpenAI authentication...
✓ OpenAI: API key configured
  Model: gpt-4o

Initializing Docling...
  Image scale: 2.0x (≈144 DPI)
✓ Docling initialized (figure extraction only)

======================================================================
Processing: NIPS-2017-attention-is-all-you-need-Paper.pdf
======================================================================

[1/5] Extracting document with Docling...
✓ Document extracted

[2/5] Extracting text...
✓ Text: 43,818 characters

[3/5] Extracting tables...
✓ Tables: 4

[4/5] Extracting figures...
  Saved: figure_1.png (page 3)
  Saved: figure_2.png (page 4)
  Saved: figure_3.png (page 6)
✓ Figures: 3

[5/5] Generating figure descriptions with OpenAI Vision...
  [1/3] Describing figure_1.png... ✓ (456 chars)
  [2/3] Describing figure_2.png... ✓ (389 chars)
  [3/3] Describing figure_3.png... ✓ (412 chars)
✓ Descriptions: 3

======================================================================
EXTRACTION COMPLETE - OpenAI Vision
======================================================================

Duration: 12.3 seconds
Vision Model: gpt-4o

Text: 43,818 characters
Tables: 4
Figures: 3
Descriptions: 3/3

Output: extracted_documents_openai/NIPS-2017-attention-is-all-you-need-Paper
```

---

## Code Structure

### Main Class

```python
class DoclingOpenAIVisionExtractor:
    def __init__(output_base_dir, image_scale, openai_model, vision_prompt):
        # Initialize Docling (no VLM)
        # Initialize OpenAI client
        
    def extract_document(pdf_path):
        # Main pipeline
        # 1. Extract with Docling
        # 2. Describe with OpenAI
        
    def _extract_figures(document):
        # Extract figures as PNG (Docling)
        
    def _generate_openai_descriptions(figure_files):
        # Generate descriptions (OpenAI Vision)
```

### Key Method: OpenAI Vision Call

```python
def _generate_openai_descriptions(self, figure_files, output_dir):
    """Generate descriptions using OpenAI Vision API"""
    
    for figure_path in figure_files:
        # Read and encode image
        with open(figure_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Call OpenAI Vision API
        response = self.openai_client.chat.completions.create(
            model=self.openai_model,  # gpt-4o, gpt-4o-mini, etc.
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
            max_tokens=500  # Max description length
        )
        
        # Extract description
        description = response.choices[0].message.content.strip()
        
        # Save
        descriptions.append({
            'figure_number': i,
            'description': description,
            'model': self.openai_model
        })
```

**Key points:**
1. Image must be base64 encoded
2. Sent as `data:image/png;base64,...`
3. Can customize prompt per image
4. Response is synchronous (waits for result)

---

## Output Files

### figure_descriptions.json

```json
[
  {
    "figure_number": 1,
    "filename": "figure_1.png",
    "filepath": "extracted_documents_openai/.../figure_1.png",
    "description": "This diagram illustrates the Transformer model architecture, 
                    which consists of an encoder stack on the left and a decoder 
                    stack on the right. Each encoder layer contains two sub-layers: 
                    a multi-head self-attention mechanism and a position-wise 
                    fully connected feed-forward network. The decoder includes 
                    an additional sub-layer for multi-head attention over the 
                    encoder output. Residual connections and layer normalization 
                    are applied around each sub-layer.",
    "model": "gpt-4o"
  },
  {
    "figure_number": 2,
    "description": "This figure shows the scaled dot-product attention mechanism...",
    "model": "gpt-4o"
  }
]
```

### figure_descriptions.md

```markdown
# Figure Descriptions (OpenAI Vision)

**Model:** gpt-4o

---

## Figure 1

**File:** `figure_1.png`

**Description:**

This diagram illustrates the Transformer model architecture, which consists 
of an encoder stack on the left and a decoder stack on the right. Each 
encoder layer contains two sub-layers: a multi-head self-attention mechanism 
and a position-wise fully connected feed-forward network. The decoder includes 
an additional sub-layer for multi-head attention over the encoder output. 
Residual connections and layer normalization are applied around each sub-layer.

*Generated by gpt-4o*

---

## Figure 2

**File:** `figure_2.png`

**Description:**

This figure shows the scaled dot-product attention mechanism used in the 
Transformer model...

*Generated by gpt-4o*

---
```

---

## Cost Estimation

### Pricing (as of January 2025)

| Model | Input | Output | Per Image (avg) |
|-------|-------|--------|-----------------|
| **gpt-4o** | $2.50/1M tokens | $10/1M tokens | ~$0.01 |
| **gpt-4o-mini** | $0.15/1M tokens | $0.60/1M tokens | ~$0.002 |
| **gpt-4-turbo** | $10/1M tokens | $30/1M tokens | ~$0.02 |

**Token usage per image:**
- Image (1200x800): ~1,000 tokens
- Description (300 words): ~400 tokens
- Total: ~1,400 tokens per image

### Example Costs

**Single paper (3 figures):**
- gpt-4o: $0.03
- gpt-4o-mini: $0.006
- gpt-4-turbo: $0.06

**10 papers (30 figures):**
- gpt-4o: $0.30
- gpt-4o-mini: $0.06
- gpt-4-turbo: $0.60

**100 papers (300 figures):**
- gpt-4o: $3.00
- gpt-4o-mini: $0.60
- gpt-4-turbo: $6.00

**Budget tip:** Use `gpt-4o-mini` for development, `gpt-4o` for production

---

## Comparison with Other Scripts

### All 4 Scripts Side-by-Side

| Feature | PyMuPDF | Docling | Docling+VLM | Docling+OpenAI |
|---------|---------|---------|-------------|----------------|
| **Text** | Good | Excellent | Excellent | Excellent |
| **Tables** | Basic | AI (CSV) | AI (CSV) | AI (CSV) |
| **Figures** | Embedded only | All (rendered) | All (rendered) | All (rendered) |
| **Descriptions** | No | No | AI (local) | AI (GPT-4) |
| **Setup** | Easy | Medium | Medium | Medium |
| **Speed** | 3s | 6s | 36s | 12s |
| **Cost** | Free | Free | Free | ~$0.03 |
| **Quality** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Reliability** | High | High | Medium | Very High |

### Decision Guide

**Use PyMuPDF when:**
- Need quick extraction
- No authentication available
- Simple documents

**Use Docling when:**
- Need accurate tables
- Vector graphics present
- No figure descriptions needed

**Use Docling+VLM when:**
- Need descriptions
- Must be free
- Have GPU
- Can accept moderate quality

**Use Docling+OpenAI when:**
- Need best descriptions ⭐
- Production use
- Budget for API
- Want reliability

---

## Troubleshooting

### Issue: OpenAI API key not found

```bash
# Error: OPENAI_API_KEY not found

# Solution:
export OPENAI_API_KEY="sk-your-key-here"

# Verify:
echo $OPENAI_API_KEY
```

### Issue: OpenAI API error (401 Unauthorized)

**Cause:** Invalid API key

**Solution:**
1. Check key is correct
2. Check key has credits
3. Get new key from https://platform.openai.com/api-keys

### Issue: Rate limit exceeded

```
Error: Rate limit reached for gpt-4o
```

**Solution:**
```python
# Add delay between images
import time
for figure in figures:
    description = describe_with_openai(figure)
    time.sleep(1)  # 1 second delay
```

### Issue: Token limit exceeded

```
Error: This model's maximum context length is...
```

**Cause:** Image too large

**Solution:**
```bash
# Reduce image resolution
python extract_docling_openai_vision.py paper.pdf --image-scale 1.0
```

### Issue: Descriptions too short

**Solution:**
```bash
# Custom prompt asking for more detail
python extract_docling_openai_vision.py paper.pdf \
  --prompt "Provide a detailed technical description of this diagram, 
            including all components, connections, and mathematical 
            notation visible. Use 3-5 sentences."
```

### Issue: High costs

**Solutions:**
1. Use `gpt-4o-mini` instead of `gpt-4o`
2. Reduce `max_tokens` in code (default: 500)
3. Lower image resolution (`--image-scale 1.0`)
4. Process only important figures

---

## Advanced Usage

### Custom Prompts for Different Figure Types

**Architecture diagrams:**
```bash
--prompt "Describe this neural network architecture diagram. 
          List all components, connections, and layer types."
```

**Charts/graphs:**
```bash
--prompt "Describe this chart. What metrics are shown? 
          What are the key trends or comparisons?"
```

**Medical images:**
```bash
--prompt "Describe this medical diagram. Identify anatomical 
          structures and any annotations present."
```

### Batch Processing with Progress

```python
# Modified code for better progress tracking
for i, figure_path in enumerate(figure_files, 1):
    print(f"Processing {i}/{len(figure_files)}: {figure_path}")
    description = generate_description(figure_path)
    print(f"  Cost so far: ${i * 0.01:.3f}")
```

### Error Recovery

Script automatically handles:
- API timeouts (retries)
- Invalid responses
- Network errors

Failed descriptions are saved with error message:
```json
{
  "figure_number": 2,
  "description": null,
  "error": "API timeout"
}
```

---

## Best Practices

### 1. Choose Right Model

- **Development:** gpt-4o-mini
- **Production:** gpt-4o
- **Legacy:** gpt-4-turbo

### 2. Optimize Costs

```bash
# Low cost
--model gpt-4o-mini --image-scale 1.0

# Balanced
--model gpt-4o --image-scale 2.0

# High quality
--model gpt-4o --image-scale 3.0
```

### 3. Custom Prompts

Be specific about what you want:
- List components
- Identify relationships
- Describe purpose
- Note mathematical notation

### 4. Monitor Usage

Check costs at: https://platform.openai.com/usage

Set billing limits to avoid surprises

---

## References

- **OpenAI Vision Guide:** https://platform.openai.com/docs/guides/vision
- **Pricing:** https://openai.com/pricing
- **API Keys:** https://platform.openai.com/api-keys
- **Docling Docs:** https://docling-project.github.io/docling/

---

**Script Version:** 1.0  
**Last Updated:** January 2026  
**Recommended for:** Production use, high-quality figure descriptions
