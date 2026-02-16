# Quick Reference Guide

## Installation & Setup

```bash
# Clone repository
git clone <repo>
cd semantic-chunker

# No dependencies required! Python 3.10+
```

## Basic Commands

```bash
# Standard usage
python open_ai_version.py --input-dir path/to/docs

# Custom sizes
python open_ai_version.py --input-dir docs --target-size 2000

# Disable merging
python open_ai_version.py --input-dir docs --no-merging

# Quiet mode
python open_ai_version.py --input-dir docs --quiet

# Full custom config
python open_ai_version.py \
    --input-dir docs \
    --target-size 2500 \
    --min-size 1000 \
    --max-size 4000 \
    --no-merging \
    --quiet
```

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--input-dir` | **Required** | Directory with metadata.json and pages/ |
| `--target-size` | 1500 | Target chunk size (characters) |
| `--min-size` | 800 | Minimum chunk size |
| `--max-size` | 2500 | Maximum chunk size |
| `--no-merging` | False | Disable cross-page merging |
| `--quiet` | False | Reduce console output |

## Module Quick Reference

### config.py
```python
from config import create_config, create_stats_dict

config = create_config(target_size=1500)
stats = create_stats_dict()
```

### logger_utils.py
```python
from logger_utils import setup_logger, log_section_header

logger = setup_logger(Path("./"), verbose=True)
log_section_header(logger, "PROCESSING")
```

### protected_blocks.py
```python
from protected_blocks import identify_protected_blocks

blocks = identify_protected_blocks(text, config, logger)
# Returns: List[(start, end, type, content)]
```

### semantic_parser.py
```python
from semantic_parser import parse_semantic_sections, consolidate_paragraphs

sections = parse_semantic_sections(text, blocks, config, logger)
sections = consolidate_paragraphs(sections, config, logger)
# Returns: List[{type, content, breadcrumbs, start, end}]
```

### chunking_engine.py
```python
from chunking_engine import build_chunks_from_sections

chunks = build_chunks_from_sections(sections, page_meta, config, stats, logger)
# Returns: List[{id, text, content_only, metadata}]
```

### continuation_detection.py
```python
from continuation_detection import detect_page_continuation

continues = detect_page_continuation(page1, page2, input_dir, config, stats, logger)
# Returns: bool
```

### page_merging.py
```python
from page_merging import merge_continued_pages

merged = merge_continued_pages(chunks1, chunks2, page1_num, page2_num, config, stats, logger)
# Returns: List[merged chunks]
```

### orchestrator.py
```python
from orchestrator import process_document

results = process_document(
    input_dir="path/to/docs",
    target_size=1500,
    min_size=800,
    max_size=2500,
    enable_merging=True,
    verbose=True
)
# Returns: Dict[document, total_pages, total_chunks, output_path, statistics]
```

## Configuration Presets

### Default (Optimal for Most Documents)
```python
config = create_config(
    target_size=1500,  # ~300-400 tokens
    min_size=800,      # Prevents fragments
    max_size=2500      # Within model limits
)
```

### Narrative Content (Books, Articles)
```python
config = create_config(
    target_size=2500,
    min_size=1500,
    max_size=4000
)
```

### Reference Documents (FAQs, APIs)
```python
config = create_config(
    target_size=800,
    min_size=400,
    max_size=1500
)
```

### Technical Reports
```python
config = create_config(
    target_size=2000,
    min_size=1000,
    max_size=3000
)
```

## Output Files

```
input_dir/
├── chunks_output.json        # Main output
└── logs/
    └── chunking_YYYYMMDD_HHMMSS.log
```

## Chunk Structure

```json
{
  "id": "abc123...",
  "text": "Context: Section > Subsection\n\nContent...",
  "content_only": "Content without context",
  "metadata": {
    "source": "page_005.md",
    "page_number": 5,
    "type": "text|table|image|code",
    "breadcrumbs": ["Section", "Subsection"],
    "hierarchical_context": {
      "level_1": "Section",
      "level_2": "Subsection",
      "full_path": "Section > Subsection",
      "depth": 2
    },
    "quality_metrics": {
      "word_count": 250,
      "sentence_count": 12,
      "avg_sentence_length": 20.8,
      "has_numerical_data": true,
      "has_dates": false,
      "has_named_entities": true,
      "has_exhibits": false
    },
    "char_count": 1450,
    "has_citations": false
  }
}
```

## Common Debugging

### Check Logs
```bash
# Detailed logs in input_dir/logs/
tail -f input_dir/logs/chunking_*.log

# Search for specific events
grep "Flushing buffer" input_dir/logs/chunking_*.log
grep "Continuation detected" input_dir/logs/chunking_*.log
grep "SEVERE VIOLATION" input_dir/logs/chunking_*.log
```

### Inspect Output
```bash
# Check chunk count
jq '.total_chunks' input_dir/chunks_output.json

# Check size distribution
jq '.detailed_statistics.size_distribution' input_dir/chunks_output.json

# View first chunk
jq '.chunks[0]' input_dir/chunks_output.json

# Count by type
jq '.detailed_statistics.type_distribution' input_dir/chunks_output.json
```

### Common Issues

| Issue | Solution |
|-------|----------|
| No chunks created | Check if pages/ directory exists with .md files |
| Chunks too small | Increase `--target-size` |
| Chunks too large | Decrease `--max-size` |
| Tables split | Check protected_blocks.py patterns |
| Missing continuations | Enable merging (remove `--no-merging`) |

## Testing Examples

```python
# Test configuration
from config import create_config
config = create_config(target_size=1500)
assert config['target_size'] == 1500
assert 'patterns' in config

# Test protected blocks
from protected_blocks import identify_protected_blocks
text = "**Image 1:** Test\n![](img.png)"
blocks = identify_protected_blocks(text, config, logger)
assert len(blocks) == 1
assert blocks[0][2] == 'image'

# Test parsing
from semantic_parser import parse_semantic_sections
text = "# Title\n\nParagraph"
sections = parse_semantic_sections(text, [], config, logger)
assert sections[0]['type'] == 'major_header'
assert sections[0]['content'] == 'Title'
```

## Performance Tips

1. **Use verbose=False** for production
2. **Process large documents** in batches
3. **Disable merging** if not needed (faster)
4. **Monitor log file size** for very large documents

## Integration Examples

### Use as Library
```python
from orchestrator import process_document

# Process document
results = process_document("path/to/docs")

# Access results
print(f"Created {results['total_chunks']} chunks")
print(f"Output: {results['output_path']}")
```

### Custom Pipeline
```python
from config import create_config
from logger_utils import setup_logger
from protected_blocks import identify_protected_blocks
from semantic_parser import parse_semantic_sections
from chunking_engine import build_chunks_from_sections

# Setup
config = create_config()
logger = setup_logger(Path("."))

# Load text
with open("page.md") as f:
    text = f.read()

# Process
blocks = identify_protected_blocks(text, config, logger)
sections = parse_semantic_sections(text, blocks, config, logger)
chunks = build_chunks_from_sections(sections, page_meta, config, stats, logger)
```

## Environment Variables

```bash
# None required - all configuration via command line
```

## Version Information

```bash
# Python version
python --version  # Requires 3.10+

# Module versions
python -c "import sys; print(sys.version)"
```

---

For detailed documentation, see:
- **README_COMPLETE.md**: Full overview
- **ARCHITECTURE.md**: Design details
- **Individual .py files**: Extensive inline docs
