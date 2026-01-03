"""
Hybrid Semantic Chunker (Structure + Embeddings)
================================================

FEATURES:
✓ TRUE SEMANTIC SPLIT: Uses 'all-MiniLM-L6-v2' to detect topic shifts.
✓ STRUCTURAL AWARENESS: Respects headers and breadcrumbs.
✓ ATOMICITY: Keeps Tables and Visuals unbreakable.
✓ ADAPTIVE: Splits text only when the meaning changes or size limits are hit.

Usage:
    python chunk_semantic_hybrid.py --input-dir extracted_docs_complete
"""

import os
import json
import re
import argparse
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple

# Import ML libraries with error handling
try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    print("❌ Missing dependencies. Run: pip install sentence-transformers scikit-learn numpy")
    exit(1)

class SemanticHybridChunker:
    def __init__(
        self,
        input_dir: str,
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.4,
        target_size: int = 1500
    ):
        self.input_dir = Path(input_dir)
        self.similarity_threshold = similarity_threshold
        self.target_size = target_size

        print(f"⚙️  Loading Semantic Model: {model_name}...")
        # Load model to CPU (or GPU if available)
        self.model = SentenceTransformer(model_name)

        # Regex for Sentence Splitting (Lookbehind for punctuation followed by space)
        self.sentence_split = re.compile(r'(?<=[.!?])\s+')

    def process(self):
        """Main execution loop reading metadata and processing pages."""
        metadata_path = self.input_dir / "metadata.json"
        if not metadata_path.exists():
            print(f"❌ metadata.json not found in {self.input_dir}")
            return

        with open(metadata_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        all_chunks = []
        doc_name = meta.get('document', 'Unknown')
        print(f"📦 Processing: {doc_name}")

        for page in meta.get("pages", []):
            page_chunks = self._chunk_page(page)
            all_chunks.extend(page_chunks)
            print(f"   ✓ Page {page.get('page_number')}: {len(page_chunks)} chunks")

        output_file = self.input_dir / "semantic_chunks.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_chunks, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Saved {len(all_chunks)} semantic chunks to: {output_file}")

    def _chunk_page(self, page_meta: Dict) -> List[Dict]:
        """Reads a page file and processes it into chunks."""
        # Handle varying metadata keys from different extractors
        file_key = 'file_name' if 'file_name' in page_meta else 'file'
        if not file_key or file_key not in page_meta:
            return []

        md_path = self.input_dir / "pages" / page_meta[file_key]
        if not md_path.exists():
            return []

        with open(md_path, 'r', encoding='utf-8') as f:
            text = f.read()

        chunks = []
        current_breadcrumbs = []

        # 1. Identify Protected Blocks (Visuals/Tables) first
        protected_blocks = self._identify_protected_blocks(text)

        cursor = 0
        text_buffer = []

        while cursor < len(text):
            # Check if current position is the start of a Protected Block
            block = next((b for b in protected_blocks if b[0] == cursor), None)

            if block:
                # A. FLUSH BUFFER: We hit a visual, so process pending text first
                if text_buffer:
                    self._flush_semantic_buffer(text_buffer, current_breadcrumbs, page_meta, chunks)
                    text_buffer = []

                # B. ADD ATOMIC BLOCK (Table or Image)
                start, end, block_type, content = block
                context_str = " > ".join(current_breadcrumbs)
                chunks.append(self._create_chunk(content, context_str, page_meta, block_type))
                cursor = end
                continue

            # Read Next Line
            try:
                next_newline = text.index('\n', cursor)
            except ValueError:
                next_newline = len(text)

            line = text[cursor:next_newline].strip()

            # Header Detection (Context Update)
            header_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if header_match:
                # A header is a strong topic shift -> Flush Buffer
                if text_buffer:
                    self._flush_semantic_buffer(text_buffer, current_breadcrumbs, page_meta, chunks)
                    text_buffer = []

                # Update Breadcrumbs logic
                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                # Filter out "Page X" headers if present
                if not title.startswith("Page "):
                    if level == 1:
                        current_breadcrumbs = [title]
                    elif level == 2:
                        current_breadcrumbs = current_breadcrumbs[:1] + [title]
                    elif level == 3:
                        current_breadcrumbs = current_breadcrumbs[:2] + [title]
                    else:
                        current_breadcrumbs = current_breadcrumbs[:level-1] + [title]

            elif line:
                # Accumulate Standard Text for semantic analysis
                text_buffer.append(line)

            # Move cursor forward
            cursor = next_newline + 1

        # Final Flush (End of Page)
        if text_buffer:
            self._flush_semantic_buffer(text_buffer, current_breadcrumbs, page_meta, chunks)

        return chunks

    def _flush_semantic_buffer(self, buffer: List[str], breadcrumbs: List[str], page_meta: Dict, chunks_list: List[Dict]):
        """
        Takes a buffer of text lines, splits them into sentences,
        and groups them into chunks based on Semantic Similarity.
        """
        if not buffer:
            return

        full_text = " ".join(buffer)

        # 1. Split into Sentences
        sentences = [s.strip() for s in self.sentence_split.split(full_text) if s.strip()]
        if not sentences:
            return

        # 2. Combine sentences into initial groups
        # (Simple heuristic to avoid encoding single words/tiny fragments)
        combined_sentences = []
        current_s = ""
        for s in sentences:
            if len(current_s) + len(s) < 100: # minimal context window
                current_s += " " + s
            else:
                combined_sentences.append(current_s.strip())
                current_s = s
        if current_s:
            combined_sentences.append(current_s.strip())

        # If text is small enough, just return one chunk without embedding cost
        if len(full_text) < self.target_size:
            context_str = " > ".join(breadcrumbs)
            chunks_list.append(self._create_chunk(full_text, context_str, page_meta, "text"))
            return

        # 3. Generate Embeddings for Semantic Splitting
        embeddings = self.model.encode(combined_sentences)

        # 4. Calculate Cosine Distances
        distances = []
        for i in range(len(embeddings) - 1):
            # Cosine similarity: 1 is identical, 0 is orthogonal
            sim = cosine_similarity([embeddings[i]], [embeddings[i+1]])[0][0]
            distances.append(sim)

        # 5. Form Chunks based on Low Similarity (Topic Shifts)
        current_chunk_sentences = [combined_sentences[0]]
        current_chunk_len = len(combined_sentences[0])

        for i, dist in enumerate(distances):
            next_sent = combined_sentences[i+1]

            # SPLIT IF:
            # (Similarity drops below threshold) OR (Chunk gets too big)
            is_topic_shift = dist < self.similarity_threshold
            is_max_size = (current_chunk_len + len(next_sent)) > self.target_size

            if is_topic_shift or is_max_size:
                # Save current chunk
                chunk_text = " ".join(current_chunk_sentences)
                context_str = " > ".join(breadcrumbs)
                chunks_list.append(self._create_chunk(chunk_text, context_str, page_meta, "text"))

                # Reset
                current_chunk_sentences = [next_sent]
                current_chunk_len = len(next_sent)
            else:
                # Continue current chunk
                current_chunk_sentences.append(next_sent)
                current_chunk_len += len(next_sent)

        # Append any remaining text
        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            context_str = " > ".join(breadcrumbs)
            chunks_list.append(self._create_chunk(chunk_text, context_str, page_meta, "text"))

    def _identify_protected_blocks(self, text: str) -> List[Tuple[int, int, str, str]]:
        """
        Identify Tables and Visuals that should NOT be split.
        Returns list of (start_index, end_index, type, content)
        """
        blocks = []

        # A. Markdown Tables
        # Matches blocks of lines starting with | and ending with |
        table_pattern = re.compile(r'(^\|.*\|$\n?)+', re.MULTILINE)
        for match in table_pattern.finditer(text):
            blocks.append((match.start(), match.end(), "table", match.group().strip()))

        # B. Visuals / Images
        # Matches ![alt](url) or <img src="...">
        image_pattern = re.compile(r'!\[.*?\]\(.*?\)|<img.*?>')
        for match in image_pattern.finditer(text):
            blocks.append((match.start(), match.end(), "visual", match.group().strip()))

        # Sort blocks by position so we process them in order
        blocks.sort(key=lambda x: x[0])
        return blocks

    def _create_chunk(self, content: str, breadcrumbs: str, meta: Dict, type: str) -> Dict:
        """Standardizes the chunk output format."""

        # Generate ID based on content hash
        chunk_id = hashlib.md5(content.encode('utf-8')).hexdigest()[:12]

        return {
            "chunk_id": chunk_id,
            "document_source": meta.get("file_name", "unknown"),
            "page_number": meta.get("page_number", 0),
            "breadcrumbs": breadcrumbs,
            "type": type,
            "content": content,
            "length": len(content)
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hybrid Semantic Chunker")
    parser.add_argument("--input-dir", required=True, help="Directory containing metadata.json and pages/")
    parser.add_argument("--threshold", type=float, default=0.4, help="Similarity threshold for splitting (lower = more splits)")
    parser.add_argument("--size", type=int, default=1500, help="Target char size per chunk")

    args = parser.parse_args()

    chunker = SemanticHybridChunker(
        input_dir=args.input_dir,
        similarity_threshold=args.threshold,
        target_size=args.size
    )
    chunker.process()