"""
Enhanced Dynamic Large Chunker - Works with Any Extractor Output
================================================================

FEATURES:
✓ Adaptive pattern matching for different markdown formats
✓ Handles output from gold_standard, docling, vlm_hybrid, and complete_visual
✓ Larger chunks (500-2000 chars) with smart merging
✓ Context preservation with breadcrumbs
✓ Atomic visuals and tables

Usage:
    python chunk_enhanced.py --input-dir extracted_docs_complete --target-size 1500
"""

import os
import json
import re
import argparse
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple

class EnhancedChunker:
    def __init__(
        self,
        input_dir: str,
        target_size: int = 1500,
        min_size: int = 500,
        max_size: int = 2500
    ):
        self.input_dir = Path(input_dir)
        self.target_size = target_size
        self.min_size = min_size
        self.max_size = max_size

        print(f"\n{'='*70}")
        print("ENHANCED CHUNKER CONFIGURATION")
        print(f"{'='*70}")
        print(f"Input Directory: {self.input_dir}")
        print(f"Target Chunk Size: {target_size} chars")
        print(f"Min Size: {min_size} chars")
        print(f"Max Size: {max_size} chars")
        print(f"{'='*70}\n")

    def process(self):
        """Main processing pipeline"""
        metadata_path = self.input_dir / "metadata.json"

        if not metadata_path.exists():
            print(f"❌ metadata.json not found in {self.input_dir}")
            return

        with open(metadata_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        all_chunks = []
        doc_name = meta.get('document', 'Unknown')
        total_pages = len(meta.get("pages", []))

        print(f"📦 Processing: {doc_name}")
        print(f"📄 Total Pages: {total_pages}\n")

        for idx, page in enumerate(meta.get("pages", []), 1):
            page_chunks = self._chunk_page(page)
            all_chunks.extend(page_chunks)

            page_num = page.get('page_number', idx)
            print(f"   [{idx}/{total_pages}] Page {page_num}: {len(page_chunks)} chunks")

        # Add embeddings metadata (optional - for future use)
        output_data = {
            "document": doc_name,
            "total_chunks": len(all_chunks),
            "chunking_config": {
                "target_size": self.target_size,
                "min_size": self.min_size,
                "max_size": self.max_size
            },
            "chunks": all_chunks
        }

        output_file = self.input_dir / "large_chunks.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\n{'='*70}")
        print(f"✅ SUCCESS")
        print(f"{'='*70}")
        print(f"Total Chunks: {len(all_chunks)}")
        print(f"Output File: {output_file}")
        print(f"{'='*70}\n")

        # Statistics
        self._print_statistics(all_chunks)

    def _chunk_page(self, page_meta: Dict) -> List[Dict]:
        """Process a single page into chunks"""

        # Get markdown file path
        file_name = page_meta.get('file_name') or page_meta.get('file')
        if not file_name:
            return []

        md_path = self.input_dir / "pages" / file_name
        if not md_path.exists():
            print(f"   ⚠️  File not found: {md_path}")
            return []

        with open(md_path, 'r', encoding='utf-8') as f:
            text = f.read()

        chunks = []
        current_breadcrumbs = []

        # Identify protected blocks (images, tables, visual sections)
        protected_blocks = self._identify_protected_blocks(text)

        # Process text with protected blocks
        cursor = 0
        text_buffer = []

        while cursor < len(text):
            # Check if we're at the start of a protected block
            block = self._get_block_at_position(protected_blocks, cursor)

            if block:
                # Flush accumulated text before protected block
                if text_buffer:
                    self._flush_text_buffer(
                        text_buffer, current_breadcrumbs, page_meta, chunks
                    )
                    text_buffer = []

                # Add protected block as single chunk
                start, end, block_type, content = block
                context_str = " > ".join(current_breadcrumbs)
                chunks.append(
                    self._create_chunk(content, context_str, page_meta, block_type)
                )
                cursor = end
                continue

            # Read next line
            line_end = text.find('\n', cursor)
            if line_end == -1:
                line_end = len(text)

            line = text[cursor:line_end].strip()

            # Check for headers (update breadcrumbs)
            header_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if header_match:
                # Flush buffer before header
                if text_buffer:
                    self._flush_text_buffer(
                        text_buffer, current_breadcrumbs, page_meta, chunks
                    )
                    text_buffer = []

                # Update breadcrumbs
                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                # Filter out page headers like "# Page 1"
                if not (level == 1 and title.startswith("Page ")):
                    if level == 1:
                        current_breadcrumbs = [title]
                    elif level == 2:
                        current_breadcrumbs = current_breadcrumbs[:1] + [title]
                    elif level == 3:
                        current_breadcrumbs = current_breadcrumbs[:2] + [title]
                    else:
                        current_breadcrumbs = current_breadcrumbs[:level-1] + [title]

            elif line and not line.startswith('<!--'):
                # Regular text line - add to buffer
                text_buffer.append(line)

            cursor = line_end + 1

        # Final flush
        if text_buffer:
            self._flush_text_buffer(
                text_buffer, current_breadcrumbs, page_meta, chunks
            )

        return chunks

    def _identify_protected_blocks(self, text: str) -> List[Tuple[int, int, str, str]]:
        """
        Identify all protected blocks (images, tables, visual sections)
        Returns: List of (start, end, type, content) tuples
        """
        blocks = []

        # Pattern 1: Image sections (various formats)
        # Matches: **Images on this page:**, **Image 1:**, **Visual Content**, etc.
        image_patterns = [
            r'\*\*Images? on this page:?\*\*.*?(?=\n#{1,3}\s|\n---|\Z)',
            r'\*\*Image \d+:?\*\*.*?(?=\n\*\*Image|\n#{1,3}\s|\n---|\Z)',
            r'\*\*Visual Content.*?\*\*.*?(?=\n#{1,3}\s|\n---|\Z)',
            r'\*\*Complete Page Visual Analysis.*?\*\*.*?(?=\n#{1,3}\s|\n---|\Z)',
            r'> \*\*Figure \d+.*?(?=\n\n|\Z)',
        ]

        for pattern in image_patterns:
            for match in re.finditer(pattern, text, re.DOTALL | re.IGNORECASE):
                blocks.append((
                    match.start(),
                    match.end(),
                    "image",
                    match.group(0)
                ))

        # Pattern 2: Tables with optional analysis
        # Matches markdown tables and their descriptions
        table_pattern = r'\n(\|[^\n]+\|\n)(\|[-:\s|]+\|\n)((?:\|[^\n]+\|\n)+)(?:\n\*\*Table.*?(?=\n\n|\n#{1,3}\s|\Z))?'

        for match in re.finditer(table_pattern, text, re.DOTALL):
            blocks.append((
                match.start(),
                match.end(),
                "table",
                match.group(0)
            ))

        # Pattern 3: Code blocks (also protect these)
        code_pattern = r'```.*?```'
        for match in re.finditer(code_pattern, text, re.DOTALL):
            blocks.append((
                match.start(),
                match.end(),
                "code",
                match.group(0)
            ))

        # Sort blocks by start position
        blocks.sort(key=lambda x: x[0])

        # Merge overlapping blocks
        merged_blocks = []
        for block in blocks:
            if not merged_blocks or block[0] >= merged_blocks[-1][1]:
                merged_blocks.append(block)
            else:
                # Extend previous block if overlap
                prev = merged_blocks[-1]
                if block[1] > prev[1]:
                    merged_blocks[-1] = (
                        prev[0],
                        block[1],
                        prev[2],
                        text[prev[0]:block[1]]
                    )

        return merged_blocks

    def _get_block_at_position(
        self,
        blocks: List[Tuple[int, int, str, str]],
        position: int
    ) -> Tuple[int, int, str, str]:
        """Check if position is at the start of a protected block"""
        for block in blocks:
            if block[0] == position:
                return block
        return None

    def _flush_text_buffer(
        self,
        buffer: List[str],
        breadcrumbs: List[str],
        meta: Dict,
        chunks: List[Dict]
    ):
        """
        Flush accumulated text buffer into chunks
        Merges lines and splits intelligently if needed
        """
        full_text = "\n\n".join(buffer).strip()
        if not full_text:
            return

        context_str = " > ".join(breadcrumbs)

        # If text is within acceptable range, keep as single chunk
        if len(full_text) <= self.max_size:
            chunks.append(self._create_chunk(full_text, context_str, meta, "text"))
            return

        # If text is too large, split intelligently
        sub_chunks = self._smart_split(full_text)
        for sc in sub_chunks:
            chunks.append(self._create_chunk(sc, context_str, meta, "text"))

    def _smart_split(self, text: str) -> List[str]:
        """
        Split large text into chunks respecting sentence boundaries
        """
        # Split into sentences (simple approach)
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_chunk = []
        current_len = 0

        for sent in sentences:
            sent_len = len(sent)

            # If adding this sentence would exceed max_size, start new chunk
            if current_len + sent_len > self.target_size and current_len >= self.min_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sent]
                current_len = sent_len
            else:
                current_chunk.append(sent)
                current_len += sent_len

        # Add remaining sentences
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def _create_chunk(
        self,
        content: str,
        context: str,
        meta: Dict,
        type_label: str
    ) -> Dict:
        """Create a chunk dictionary with metadata"""

        # Combine context and content for RAG
        if context:
            rag_text = f"Context: {context}\n\n{content}"
        else:
            rag_text = content

        # Generate unique chunk ID
        chunk_id = hashlib.md5(rag_text.encode('utf-8')).hexdigest()

        # Extract image path if present
        img_match = re.search(r'\((figures/[^)]+\.png)\)', content)
        img_path = img_match.group(1) if img_match else None

        return {
            "id": chunk_id,
            "text": rag_text,
            "content_only": content,  # Original content without context
            "metadata": {
                "source": meta.get('file_name') or meta.get('file'),
                "page_number": meta.get('page_number'),
                "type": type_label,
                "breadcrumbs": context.split(" > ") if context else [],
                "image_path": img_path,
                "char_count": len(content)
            }
        }

    def _print_statistics(self, chunks: List[Dict]):
        """Print chunking statistics"""
        if not chunks:
            return

        sizes = [len(c['content_only']) for c in chunks]
        types = {}
        for c in chunks:
            t = c['metadata']['type']
            types[t] = types.get(t, 0) + 1

        print("\n📊 CHUNK STATISTICS")
        print(f"{'='*70}")
        print(f"Total Chunks: {len(chunks)}")
        print(f"\nSize Distribution:")
        print(f"  Min: {min(sizes)} chars")
        print(f"  Max: {max(sizes)} chars")
        print(f"  Avg: {sum(sizes)//len(sizes)} chars")
        print(f"\nChunk Types:")
        for t, count in sorted(types.items()):
            print(f"  {t}: {count} chunks")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enhanced chunker for any PDF extraction output"
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing metadata.json and pages/"
    )
    parser.add_argument(
        "--target-size",
        type=int,
        default=1500,
        help="Target chunk size in characters (default: 1500)"
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=500,
        help="Minimum chunk size in characters (default: 500)"
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=2500,
        help="Maximum chunk size in characters (default: 2500)"
    )

    args = parser.parse_args()

    chunker = EnhancedChunker(
        input_dir=args.input_dir,
        target_size=args.target_size,
        min_size=args.min_size,
        max_size=args.max_size
    )

    chunker.process()