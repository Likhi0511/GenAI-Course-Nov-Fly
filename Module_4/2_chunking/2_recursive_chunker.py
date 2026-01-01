"""
Recursive Chunking
==================

Smart text splitting using recursive separators.

How it works:
    1. Try to split on double newlines (paragraphs)
    2. If chunks too large, split on single newlines (lines)
    3. If still too large, split on periods (sentences)
    4. If still too large, split on spaces (words)
    5. Last resort: split on characters

Pros:
    - Preserves natural boundaries
    - Good balance of speed and quality
    - Industry standard (LangChain)
    - Works for most documents

Cons:
    - Still character-based (not semantic)
    - May split related content

Use when:
    - Default choice for most use cases
    - Don't know document structure
    - Need reliable, fast chunking
    - General purpose RAG

Example:
    text = "Introduction\n\nThe model uses attention.\n\nMethods\n\nWe trained for 3 days."
    
    Step 1: Try "\n\n" (paragraphs)
    Chunk 1: "Introduction\n\nThe model uses attention."
    Chunk 2: "Methods\n\nWe trained for 3 days."
    
    If chunk too large, try "\n", then ".", then " "

Usage:
    python 2_recursive_chunker.py text.md
    python 2_recursive_chunker.py text.md --chunk-size 1000 --overlap 200
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict
from datetime import datetime

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ImportError:
    print("Error: langchain not installed")
    print("Install with: pip install langchain langchain-text-splitters")
    exit(1)


class RecursiveChunker:
    """Recursive character text splitting"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Number of characters to overlap
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Create LangChain splitter
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
            is_separator_regex=False
        )
    
    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk text using recursive splitting
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of chunk dictionaries with metadata
        """
        # Split text
        raw_chunks = self.splitter.split_text(text)
        
        # Enrich with metadata
        chunks = []
        for i, chunk_text in enumerate(raw_chunks):
            chunk = {
                'chunk_id': i,
                'text': chunk_text,
                'char_count': len(chunk_text),
                'word_count': len(chunk_text.split()),
                'metadata': {
                    'strategy': 'recursive',
                    'chunk_size': self.chunk_size,
                    'overlap': self.chunk_overlap,
                    'separators': ["\n\n", "\n", ". ", " ", ""]
                }
            }
            chunks.append(chunk)
        
        return chunks
    
    def save_chunks(self, chunks: List[Dict], output_dir: Path):
        """Save chunks to individual JSON files"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for chunk in chunks:
            filename = output_dir / f"chunk_{chunk['chunk_id']:04d}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(chunk, f, indent=2, ensure_ascii=False)
        
        # Save manifest
        manifest = {
            'total_chunks': len(chunks),
            'strategy': 'recursive',
            'chunk_size': self.chunk_size,
            'overlap': self.chunk_overlap,
            'created_at': datetime.now().isoformat(),
            'chunks': [
                {
                    'chunk_id': c['chunk_id'],
                    'file': f"chunk_{c['chunk_id']:04d}.json",
                    'char_count': c['char_count']
                }
                for c in chunks
            ]
        }
        
        with open(output_dir / 'manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(chunks)} chunks to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Recursive character chunking")
    parser.add_argument('input_file', help='Text file to chunk')
    parser.add_argument('--chunk-size', type=int, default=1000, help='Target chunk size')
    parser.add_argument('--overlap', type=int, default=200, help='Overlap between chunks')
    parser.add_argument('--output-dir', default='chunks_recursive', help='Output directory')
    args = parser.parse_args()
    
    # Read input
    with open(args.input_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    print(f"Input: {args.input_file}")
    print(f"Length: {len(text):,} characters")
    print(f"Target chunk size: {args.chunk_size}")
    print(f"Overlap: {args.overlap}\n")
    
    # Chunk
    chunker = RecursiveChunker(chunk_size=args.chunk_size, chunk_overlap=args.overlap)
    chunks = chunker.chunk(text)
    
    sizes = [c['char_count'] for c in chunks]
    print(f"Generated {len(chunks)} chunks")
    print(f"Size range: {min(sizes)} - {max(sizes)} chars")
    print(f"Avg size: {sum(sizes) / len(sizes):.0f} chars\n")
    
    # Save
    output_dir = Path(args.output_dir)
    chunker.save_chunks(chunks, output_dir)


if __name__ == "__main__":
    main()
