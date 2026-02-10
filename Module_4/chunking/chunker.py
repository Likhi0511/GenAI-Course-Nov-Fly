"""
================================================================================
          COMPREHENSIVE DOCUMENT CHUNKER - ALL-IN-ONE SOLUTION
================================================================================

FEATURES:
=========
✓ Boundary marker extraction (simple and reliable)
✓ Type-aware semantic chunking (headers bind to content)
✓ Clean output format with 'content' field (ready for enrichment)
✓ Filtering by type, page, breadcrumbs
✓ Smart table/image handling
✓ Production-ready for RAG pipelines

OUTPUT FORMAT:
==============
Always outputs clean format with 'content' field:
{
  "chunks": [
    {
      "content": "## Header\n\nText content here...",
      "metadata": {
        "breadcrumbs": "Section Name",
        "char_count": 1500,
        "num_atomic_chunks": 5
      }
    }
  ]
}

USAGE:
======
    # Semantic chunks (recommended for RAG)
    python comprehensive_chunker.py pages/ --semantic

    # With debug info
    python comprehensive_chunker.py pages/ --semantic --keep-ids

    # Filter and chunk
    python comprehensive_chunker.py pages/ --type paragraph --semantic

    # Text-only chunks (exclude images/tables)
    python comprehensive_chunker.py pages/ --text-only --semantic
"""

# ============================================================================
# IMPORTS
# ============================================================================
import re          # Regular expressions for pattern matching
import json        # JSON serialization
import argparse    # Command-line argument parsing
import sys         # System utilities
from pathlib import Path              # Modern path handling
from typing import List, Dict, Optional  # Type hints


# ============================================================================
# CORE EXTRACTION FUNCTION
# ============================================================================

def extract_chunks_from_markdown(markdown_text: str) -> List[Dict]:
    """
    Extract all chunks from markdown with boundary markers

    This is the foundation - extracts atomic chunks from boundary markers.

    Args:
        markdown_text: Markdown content with boundary markers

    Returns:
        List of atomic chunk dictionaries
    """
    # Pattern to match boundary markers and content between them
    pattern = r'<!-- BOUNDARY_START (.*?) -->\n(.*?)\n<!-- BOUNDARY_END (.*?) -->'

    # Find all matches (DOTALL flag to match across newlines)
    matches = re.findall(pattern, markdown_text, re.DOTALL)

    chunks = []

    for start_attrs, content, end_attrs in matches:
        # Parse attributes from START marker
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', start_attrs))

        # Extract core fields
        chunk = {
            'id': attrs.get('id', 'unknown'),
            'type': attrs.get('type', 'unknown'),
            'page': attrs.get('page', '0'),
            'content': content.strip()
        }

        # Add remaining attributes as metadata
        metadata = {k: v for k, v in attrs.items()
                   if k not in ['id', 'type', 'page']}

        if metadata:
            chunk['metadata'] = metadata

        chunks.append(chunk)

    return chunks


# ============================================================================
# FILE I/O FUNCTIONS
# ============================================================================

def chunk_file(file_path: Path) -> List[Dict]:
    """Extract chunks from a single markdown file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return extract_chunks_from_markdown(content)


def chunk_directory(dir_path: Path) -> Dict[str, List[Dict]]:
    """
    Extract chunks from all markdown files in directory

    Automatically handles:
    - Direct pages directory: extracted_docs/doc_name/pages/
    - Parent directory: extracted_docs/doc_name/
    - Batch directory: extracted_docs/
    """
    results = {}

    # Check if directory contains .md files directly
    md_files = list(dir_path.glob("*.md"))

    if md_files:
        # This is a pages directory
        for md_file in sorted(md_files):
            chunks = chunk_file(md_file)
            results[md_file.name] = chunks
    else:
        # Look for pages/ subdirectories
        pages_dir = dir_path / "pages"
        if pages_dir.exists() and pages_dir.is_dir():
            # Single document with pages/ subdirectory
            for md_file in sorted(pages_dir.glob("*.md")):
                chunks = chunk_file(md_file)
                results[md_file.name] = chunks
        else:
            # Multiple documents with */pages/ pattern
            for pages_dir in dir_path.glob("*/pages"):
                if pages_dir.is_dir():
                    for md_file in sorted(pages_dir.glob("*.md")):
                        chunks = chunk_file(md_file)
                        key = f"{pages_dir.parent.name}/{md_file.name}"
                        results[key] = chunks

    return results


# ============================================================================
# FILTERING FUNCTIONS
# ============================================================================

def filter_chunks_by_type(chunks: List[Dict], chunk_type: str) -> List[Dict]:
    """Filter chunks by content type"""
    return [c for c in chunks if c['type'] == chunk_type]


def filter_chunks_by_page(chunks: List[Dict], page: int) -> List[Dict]:
    """Filter chunks by page number"""
    return [c for c in chunks if int(c['page']) == page]


def filter_chunks_by_breadcrumb(chunks: List[Dict], breadcrumb: str) -> List[Dict]:
    """Filter chunks by breadcrumb path (exact or partial match)"""
    return [c for c in chunks
            if breadcrumb.lower() in c.get('metadata', {}).get('breadcrumbs', '').lower()]


def get_text_only_chunks(chunks: List[Dict]) -> List[Dict]:
    """Get only text chunks (paragraphs and headers)"""
    return [c for c in chunks if c['type'] in ['paragraph', 'header']]


# ============================================================================
# IMPROVED SEMANTIC CHUNKING WITH TYPE AWARENESS
# ============================================================================

def create_semantic_chunks(
        chunks: List[Dict],
        target_size: int = 1500,
        min_size: int = 800,
        max_size: int = 3000,
        max_table_size: int = 2000
) -> List[Dict]:
    """
    Create semantic chunks with intelligent type-aware grouping

    KEY IMPROVEMENTS OVER BASIC CHUNKING:
    ======================================
    1. Headers ALWAYS bind to following content (no orphaned headers)
    2. Large tables (>max_table_size) become standalone chunks
    3. Look-ahead logic prevents flushing before headers
    4. Smart section boundary detection

    Args:
        chunks: List of atomic chunks from boundary markers
        target_size: Target character count (soft target, default 1500)
        min_size: Minimum size before flushing (default 800)
        max_size: Hard maximum size (default 3000)
        max_table_size: Tables larger than this become standalone (default 2000)

    Returns:
        List of semantic chunks with better coherence
    """

    semantic_chunks = []
    buffer = []
    buffer_size = 0
    current_breadcrumb = None

    # -----------------------------------------------------------------------
    # Helper: Check if next chunk is a header
    # -----------------------------------------------------------------------
    def next_is_header(current_idx: int) -> bool:
        """Check if the next chunk in sequence is a header"""
        if current_idx + 1 < len(chunks):
            return chunks[current_idx + 1]['type'] == 'header'
        return False

    # -----------------------------------------------------------------------
    # Helper: Flush buffer to create semantic chunk
    # -----------------------------------------------------------------------
    def flush_buffer():
        """Create semantic chunk from current buffer and reset"""
        nonlocal buffer, buffer_size, semantic_chunks

        if buffer:
            semantic_chunks.append({
                'combined_content': '\n\n'.join([c['content'] for c in buffer]),
                'chunk_ids': [c['id'] for c in buffer],
                'breadcrumbs': current_breadcrumb,
                'char_count': buffer_size,
                'num_chunks': len(buffer),
                'chunk_types': [c['type'] for c in buffer]
            })
            buffer = []
            buffer_size = 0

    # -----------------------------------------------------------------------
    # Main chunking loop
    # -----------------------------------------------------------------------
    for idx, chunk in enumerate(chunks):
        chunk_type = chunk['type']
        breadcrumb = chunk.get('metadata', {}).get('breadcrumbs', '')
        chunk_size = len(chunk['content'])

        # -------------------------------------------------------------------
        # SPECIAL CASE: Large tables become standalone chunks
        # -------------------------------------------------------------------
        if chunk_type == 'table' and chunk_size > max_table_size:
            # Flush current buffer first
            flush_buffer()

            # Make table its own chunk
            semantic_chunks.append({
                'combined_content': chunk['content'],
                'chunk_ids': [chunk['id']],
                'breadcrumbs': breadcrumb,
                'char_count': chunk_size,
                'num_chunks': 1,
                'chunk_types': ['table']
            })
            current_breadcrumb = breadcrumb
            continue

        # -------------------------------------------------------------------
        # Check flush conditions (with type awareness!)
        # -------------------------------------------------------------------
        section_changed = (current_breadcrumb and breadcrumb != current_breadcrumb)
        would_exceed_max = (buffer_size + chunk_size > max_size)
        is_next_header = next_is_header(idx)

        # -------------------------------------------------------------------
        # RULE 1: Section changed + big enough + NOT before header
        # -------------------------------------------------------------------
        if section_changed and buffer_size >= min_size and not is_next_header:
            flush_buffer()

        # -------------------------------------------------------------------
        # RULE 2: Would exceed max_size + big enough
        # -------------------------------------------------------------------
        elif would_exceed_max and buffer_size >= min_size:
            if chunk_type != 'header':
                flush_buffer()
            else:
                # Header will start new buffer - flush old one
                flush_buffer()

        # -------------------------------------------------------------------
        # Add current chunk to buffer
        # -------------------------------------------------------------------
        buffer.append(chunk)
        buffer_size += chunk_size
        current_breadcrumb = breadcrumb

        # -------------------------------------------------------------------
        # RULE 3: Buffer reached target size + NOT before header
        # -------------------------------------------------------------------
        if buffer_size >= target_size and not is_next_header:
            flush_buffer()

    # -----------------------------------------------------------------------
    # Flush remaining buffer
    # -----------------------------------------------------------------------
    flush_buffer()

    return semantic_chunks


# ============================================================================
# OUTPUT FORMATTING FUNCTIONS
# ============================================================================

def format_chunks_for_output(semantic_chunks: List[Dict], keep_ids: bool = False) -> List[Dict]:
    """
    Convert semantic chunks to clean output format with 'content' field

    This is now the ONLY output format - clean and simple!

    Output format:
    {
      "content": "...",
      "metadata": {
        "breadcrumbs": "...",
        "char_count": 1500,
        "num_atomic_chunks": 5
      }
    }

    Args:
        semantic_chunks: Raw semantic chunks from create_semantic_chunks()
        keep_ids: Include chunk_ids in metadata (for debugging)

    Returns:
        List of clean formatted chunks ready for enrichment
    """
    clean = []

    for chunk in semantic_chunks:
        clean_chunk = {
            'content': chunk['combined_content'],  # Always use 'content' field
            'metadata': {
                'breadcrumbs': chunk.get('breadcrumbs', ''),
                'char_count': chunk['char_count'],
                'num_atomic_chunks': chunk['num_chunks']
            }
        }

        # Optionally include chunk_ids for debugging
        if keep_ids:
            clean_chunk['metadata']['chunk_ids'] = chunk['chunk_ids']
            clean_chunk['metadata']['chunk_types'] = chunk['chunk_types']

        clean.append(clean_chunk)

    return clean


# ============================================================================
# STATISTICS AND SUMMARY FUNCTIONS
# ============================================================================

def print_chunk_summary(chunks: List[Dict], title: str = "Chunk Summary"):
    """Print summary statistics about chunks"""
    total = len(chunks)

    # Count by type
    type_counts = {}
    for chunk in chunks:
        chunk_type = chunk['type']
        type_counts[chunk_type] = type_counts.get(chunk_type, 0) + 1

    # Count by page
    page_counts = {}
    for chunk in chunks:
        page = chunk['page']
        page_counts[page] = page_counts.get(page, 0) + 1

    print(f"\n{title}")
    print(f"{'='*60}")
    print(f"Total chunks: {total}")
    print(f"\nBy type:")
    for chunk_type, count in sorted(type_counts.items()):
        print(f"  {chunk_type:15s}: {count:4d}")
    print(f"\nBy page:")
    for page, count in sorted(page_counts.items(), key=lambda x: int(x[0]))[:10]:
        print(f"  Page {page:3s}: {count:4d} chunks")
    if len(page_counts) > 10:
        print(f"  ... and {len(page_counts) - 10} more pages")
    print(f"{'='*60}\n")


def print_semantic_summary(semantic_chunks: List[Dict]):
    """Print summary of semantic chunks"""
    total = len(semantic_chunks)
    sizes = [c['char_count'] for c in semantic_chunks]

    print(f"\nSemantic Chunk Summary")
    print(f"{'='*60}")
    print(f"Total semantic chunks: {total}")
    print(f"\nSize distribution:")
    print(f"  Min size:     {min(sizes):5d} chars")
    print(f"  Max size:     {max(sizes):5d} chars")
    print(f"  Average size: {sum(sizes)//len(sizes):5d} chars")
    print(f"  Median size:  {sorted(sizes)[len(sizes)//2]:5d} chars")

    # Size buckets
    buckets = {
        '<800': sum(1 for s in sizes if s < 800),
        '800-1500': sum(1 for s in sizes if 800 <= s < 1500),
        '1500-2500': sum(1 for s in sizes if 1500 <= s < 2500),
        '2500+': sum(1 for s in sizes if s >= 2500)
    }
    print(f"\nSize buckets:")
    for bucket, count in buckets.items():
        print(f"  {bucket:12s}: {count:4d} chunks ({count*100//total:2d}%)")
    print(f"{'='*60}\n")


# ============================================================================
# MAIN CLI FUNCTION
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive Document Chunker - All-in-One Solution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clean semantic chunks (recommended for RAG)
  python comprehensive_chunker.py pages/ --semantic --clean
  
  # Semantic chunks (recommended for RAG)
  python comprehensive_chunker.py pages/ --semantic
  
  # With debug info (keep chunk IDs)
  python comprehensive_chunker.py pages/ --semantic --keep-ids
  
  # Filter by type then chunk
  python comprehensive_chunker.py pages/ --type paragraph --semantic
  
  # Text-only chunks (exclude images/tables)
  python comprehensive_chunker.py pages/ --text-only --semantic
  
  # Include atomic chunks too (debugging)
  python comprehensive_chunker.py pages/ --semantic --include-atomic
        """
    )

    # -----------------------------------------------------------------------
    # Input/Output Arguments
    # -----------------------------------------------------------------------
    parser.add_argument(
        "path",
        type=Path,
        help="Path to markdown file or directory"
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file (default: chunks.json or semantic_chunks.json)"
    )

    # -----------------------------------------------------------------------
    # Filtering Arguments
    # -----------------------------------------------------------------------
    parser.add_argument(
        "--type",
        help="Filter by chunk type (paragraph, header, image, table, etc.)"
    )

    parser.add_argument(
        "--page",
        type=int,
        help="Filter by page number"
    )

    parser.add_argument(
        "--breadcrumb",
        help="Filter by breadcrumb (partial match)"
    )

    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Only include text chunks (paragraphs and headers)"
    )

    # -----------------------------------------------------------------------
    # Semantic Chunking Arguments
    # -----------------------------------------------------------------------
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Create semantic chunks (combine atomic chunks intelligently)"
    )

    parser.add_argument(
        "--target-size",
        type=int,
        default=1500,
        help="Target character count for semantic chunks (default: 1500)"
    )

    parser.add_argument(
        "--min-size",
        type=int,
        default=800,
        help="Minimum size for semantic chunks (default: 800)"
    )

    parser.add_argument(
        "--max-size",
        type=int,
        default=3000,
        help="Maximum size for semantic chunks (default: 3000)"
    )

    parser.add_argument(
        "--max-table-size",
        type=int,
        default=2000,
        help="Tables larger than this become standalone chunks (default: 2000)"
    )

    # -----------------------------------------------------------------------
    # Output Format Arguments (for debugging only)
    # -----------------------------------------------------------------------
    parser.add_argument(
        "--keep-ids",
        action="store_true",
        help="Keep chunk IDs in output (for debugging)"
    )

    parser.add_argument(
        "--include-atomic",
        action="store_true",
        help="Include atomic chunks alongside semantic chunks (for debugging)"
    )

    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # STEP 1: Extract atomic chunks
    # -----------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"COMPREHENSIVE DOCUMENT CHUNKER")
    print(f"{'='*60}\n")

    if args.path.is_file():
        print(f"📄 Processing file: {args.path.name}")
        chunks = chunk_file(args.path)
    else:
        print(f"📁 Processing directory: {args.path}")
        results = chunk_directory(args.path)

        if not results:
            print("\n❌ ERROR: No markdown files found!")
            print("\nExpected structure:")
            print("  extracted_docs/")
            print("  └── document_name/")
            print("      └── pages/")
            print("          ├── page_1.md")
            print("          └── page_2.md")
            return

        print(f"\n✓ Found {len(results)} markdown file(s)")
        for filename in list(results.keys())[:5]:
            print(f"  • {filename}")
        if len(results) > 5:
            print(f"  ... and {len(results) - 5} more")

        # Flatten all chunks
        chunks = []
        for file_chunks in results.values():
            chunks.extend(file_chunks)

    print(f"\n✓ Extracted {len(chunks)} atomic chunks")

    # -----------------------------------------------------------------------
    # STEP 2: Apply filters
    # -----------------------------------------------------------------------
    original_count = len(chunks)

    if args.text_only:
        chunks = get_text_only_chunks(chunks)
        print(f"✓ Filtered to {len(chunks)} text-only chunks")

    if args.type:
        chunks = filter_chunks_by_type(chunks, args.type)
        print(f"✓ Filtered to {len(chunks)} '{args.type}' chunks")

    if args.page:
        chunks = filter_chunks_by_page(chunks, args.page)
        print(f"✓ Filtered to {len(chunks)} chunks from page {args.page}")

    if args.breadcrumb:
        chunks = filter_chunks_by_breadcrumb(chunks, args.breadcrumb)
        print(f"✓ Filtered to {len(chunks)} chunks matching '{args.breadcrumb}'")

    if len(chunks) != original_count:
        print(f"✓ Total after filtering: {len(chunks)} chunks")

    # -----------------------------------------------------------------------
    # STEP 3: Create semantic chunks if requested
    # -----------------------------------------------------------------------
    if args.semantic:
        print(f"\n{'='*60}")
        print(f"Creating semantic chunks...")
        print(f"{'='*60}")

        semantic_chunks = create_semantic_chunks(
            chunks,
            target_size=args.target_size,
            min_size=args.min_size,
            max_size=args.max_size,
            max_table_size=args.max_table_size
        )

        print(f"\n✓ Created {len(semantic_chunks)} semantic chunks")
        print_semantic_summary(semantic_chunks)

        # Always format to clean output with 'content' field
        clean_chunks = format_chunks_for_output(semantic_chunks, keep_ids=args.keep_ids)

        # Decide whether to include atomic chunks (debugging only)
        if args.include_atomic:
            output_data = {
                'atomic_chunks': chunks,
                'chunks': clean_chunks
            }
        else:
            # Default: Just the clean chunks (recommended)
            output_data = {'chunks': clean_chunks}

    else:
        # Just atomic chunks (for atomic-only workflow)
        print_chunk_summary(chunks)

        # Format atomic chunks to match semantic format
        atomic_formatted = []
        for chunk in chunks:
            atomic_formatted.append({
                'content': chunk['content'],
                'metadata': {
                    'chunk_id': chunk['id'],
                    'type': chunk['type'],
                    'page': chunk['page'],
                    **chunk.get('metadata', {})
                }
            })

        output_data = {'chunks': atomic_formatted}

    # -----------------------------------------------------------------------
    # STEP 4: Save to file
    # -----------------------------------------------------------------------
    output_path = args.output
    if not output_path:
        # Auto-generate output path
        if args.path.is_file():
            base_dir = args.path.parent
        else:
            base_dir = args.path

        if args.semantic:
            output_filename = "semantic_chunks.json"
        else:
            output_filename = "chunks.json"

        output_path = base_dir / output_filename

    print(f"\n{'='*60}")
    print(f"Saving output...")
    print(f"{'='*60}\n")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"✓ SAVED: {output_path}")

    # Print what was saved
    if args.semantic:
        if args.include_atomic:
            print(f"  • {len(chunks)} atomic chunks")
            print(f"  • {len(output_data['chunks'])} semantic chunks")
        else:
            print(f"  • {len(output_data['chunks'])} semantic chunks")
    else:
        print(f"  • {len(output_data['chunks'])} atomic chunks")

    # -----------------------------------------------------------------------
    # STEP 5: Show sample
    # -----------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"Sample Output (first chunk)")
    print(f"{'='*60}")

    if output_data['chunks']:
        sample = output_data['chunks'][0]

        # All chunks now use clean format with 'content' field
        print(f"\nBreadcrumbs: {sample['metadata'].get('breadcrumbs', 'N/A')}")

        if 'char_count' in sample['metadata']:
            # Semantic chunk
            print(f"Size: {sample['metadata']['char_count']} chars")
            print(f"Atomic chunks: {sample['metadata']['num_atomic_chunks']}")

        if args.keep_ids and 'chunk_ids' in sample['metadata']:
            print(f"Chunk IDs: {sample['metadata']['chunk_ids'][:3]}...")
            print(f"Types: {sample['metadata'].get('chunk_types', [])[:5]}")

        print(f"\nContent preview:")
        print(sample['content'][:300] + "...")

    print(f"\n{'='*60}")
    print(f"✓ COMPLETE")
    print(f"{'='*60}\n")


# ============================================================================
# SCRIPT ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()