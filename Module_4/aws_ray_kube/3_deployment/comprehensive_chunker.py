"""
comprehensive_chunker.py

Boundary-aware semantic chunker for the Ray pipeline.

Reads page_*.md files produced by docling_bounded_extractor, extracts
atomic chunks from HTML boundary markers, then groups them into semantic
chunks ready for enrichment.

Pipeline position:
  Stage 1 (extraction) → Stage 2 (this) → Stage 3 (enrichment)

Output schema per chunk:
  {
    "content":  "...",
    "metadata": {"breadcrumbs": "...", "char_count": 1500, "num_atomic_chunks": 5}
  }

Author: Prudhvi | Thoughtworks
"""

import re
import json
from pathlib import Path
from typing import List, Dict


# =============================================================================
# EXTRACTION
# =============================================================================

def extract_chunks_from_markdown(markdown_text: str) -> List[Dict]:
    """Parse boundary markers and return a list of atomic chunk dicts."""
    pattern = r'<!-- BOUNDARY_START (.*?) -->\n(.*?)\n<!-- BOUNDARY_END (.*?) -->'
    chunks = []
    for start_attrs, content, _ in re.findall(pattern, markdown_text, re.DOTALL):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', start_attrs))
        chunk = {
            'id':      attrs.get('id', 'unknown'),
            'type':    attrs.get('type', 'unknown'),
            'page':    attrs.get('page', '0'),
            'content': content.strip(),
        }
        metadata = {k: v for k, v in attrs.items() if k not in ('id', 'type', 'page')}
        if metadata:
            chunk['metadata'] = metadata
        chunks.append(chunk)
    return chunks


def chunk_file(file_path: Path) -> List[Dict]:
    """Extract chunks from a single markdown file."""
    return extract_chunks_from_markdown(file_path.read_text(encoding='utf-8'))


def chunk_directory(dir_path: Path) -> Dict[str, List[Dict]]:
    """
    Extract chunks from all markdown files in a directory.

    Handles three layouts automatically:
      - dir_path contains .md files directly  (pages/ dir)
      - dir_path/pages/ contains .md files    (single doc root)
      - dir_path/*/pages/ pattern             (batch of docs)
    """
    results = {}
    md_files = sorted(dir_path.glob('*.md'))

    if md_files:
        for f in md_files:
            results[f.name] = chunk_file(f)
    else:
        pages_dir = dir_path / 'pages'
        if pages_dir.exists():
            for f in sorted(pages_dir.glob('*.md')):
                results[f.name] = chunk_file(f)
        else:
            for pages_dir in dir_path.glob('*/pages'):
                for f in sorted(pages_dir.glob('*.md')):
                    results[f"{pages_dir.parent.name}/{f.name}"] = chunk_file(f)

    return results


# =============================================================================
# SEMANTIC CHUNKING
# =============================================================================

def create_semantic_chunks(
    chunks: List[Dict],
    target_size: int = 1500,
    min_size: int = 800,
    max_size: int = 3000,
    max_table_size: int = 2000,
) -> List[Dict]:
    """
    Group atomic chunks into coherent semantic chunks.

    Rules:
      1. Headers always bind to the content that follows them.
      2. Large tables (> max_table_size chars) become standalone chunks.
      3. Flush buffer when section changes, size exceeds max, or target is hit —
         but never flush immediately before a header.
    """
    semantic_chunks = []
    buffer: List[Dict] = []
    buffer_size = 0
    current_breadcrumb = None

    def next_is_header(idx: int) -> bool:
        return idx + 1 < len(chunks) and chunks[idx + 1]['type'] == 'header'

    def flush():
        nonlocal buffer, buffer_size
        if buffer:
            semantic_chunks.append({
                'combined_content': '\n\n'.join(c['content'] for c in buffer),
                'chunk_ids':   [c['id'] for c in buffer],
                'breadcrumbs': current_breadcrumb,
                'char_count':  buffer_size,
                'num_chunks':  len(buffer),
                'chunk_types': [c['type'] for c in buffer],
            })
            buffer = []
            buffer_size = 0

    for idx, chunk in enumerate(chunks):
        chunk_type = chunk['type']
        breadcrumb = chunk.get('metadata', {}).get('breadcrumbs', '')
        chunk_size = len(chunk['content'])

        # Large tables are always standalone
        if chunk_type == 'table' and chunk_size > max_table_size:
            flush()
            semantic_chunks.append({
                'combined_content': chunk['content'],
                'chunk_ids':   [chunk['id']],
                'breadcrumbs': breadcrumb,
                'char_count':  chunk_size,
                'num_chunks':  1,
                'chunk_types': ['table'],
            })
            current_breadcrumb = breadcrumb
            continue

        section_changed  = current_breadcrumb and breadcrumb != current_breadcrumb
        would_exceed_max = buffer_size + chunk_size > max_size
        before_header    = next_is_header(idx)

        if (section_changed and buffer_size >= min_size and not before_header) or \
           (would_exceed_max and buffer_size >= min_size):
            flush()

        buffer.append(chunk)
        buffer_size += chunk_size
        current_breadcrumb = breadcrumb

        if buffer_size >= target_size and not before_header:
            flush()

    flush()
    return semantic_chunks


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_chunks_for_output(semantic_chunks: List[Dict], keep_ids: bool = False) -> List[Dict]:
    """Convert internal semantic chunks to the clean pipeline output schema."""
    result = []
    for chunk in semantic_chunks:
        out = {
            'content': chunk['combined_content'],
            'metadata': {
                'breadcrumbs':      chunk.get('breadcrumbs', ''),
                'char_count':       chunk['char_count'],
                'num_atomic_chunks': chunk['num_chunks'],
            },
        }
        if keep_ids:
            out['metadata']['chunk_ids']   = chunk['chunk_ids']
            out['metadata']['chunk_types'] = chunk['chunk_types']
        result.append(out)
    return result
