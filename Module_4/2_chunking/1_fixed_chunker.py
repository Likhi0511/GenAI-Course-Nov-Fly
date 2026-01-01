"""
Fixed-Size Chunking
===================

Simple sliding window chunking at exact character positions.

How it works:
    1. Start at position 0
    2. Take chunk_size characters
    3. Move forward by (chunk_size - overlap)
    4. Repeat until end of text

Pros:
    - Very fast
    - Predictable chunk sizes
    - Simple implementation
    - No dependencies

Cons:
    - May split sentences mid-way
    - May split words
    - Ignores document structure
    - No semantic meaning

Use when:
    - Speed is critical
    - Exact chunk sizes needed
    - Simple documents
    - Prototyping

Example:
    text = "The quick brown fox jumps over the lazy dog"
    chunk_size = 20
    overlap = 5
    
    Chunk 1: "The quick brown fox "  (chars 0-20)
    Chunk 2: "fox jumps over the l"  (chars 15-35, 5 char overlap)
    Chunk 3: "the lazy dog"           (chars 30-end)

Usage:
    python 1_fixed_chunker.py text.md
    python 1_fixed_chunker.py text.md --chunk-size 512 --overlap 50
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict
from datetime import datetime


class FixedChunker:
    """Fixed-size chunking with sliding window"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Args:
            chunk_size: Size of each chunk in characters
            chunk_overlap: Number of characters to overlap between chunks
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("Overlap must be less than chunk_size")
        
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.step_size = chunk_size - chunk_overlap
    
    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk text using fixed-size sliding window
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of chunk dictionaries with metadata
        """
        chunks = []
        position = 0
        chunk_id = 0
        
        while position < len(text):
            # Extract chunk
            end_position = min(position + self.chunk_size, len(text))
            chunk_text = text[position:end_position]
            
            # Create chunk metadata
            chunk = {
                'chunk_id': chunk_id,
                'text': chunk_text,
                'char_count': len(chunk_text),
                'word_count': len(chunk_text.split()),
                'start_position': position,
                'end_position': end_position,
                'metadata': {
                    'strategy': 'fixed',
                    'chunk_size': self.chunk_size,
                    'overlap': self.chunk_overlap
                }
            }
            
            chunks.append(chunk)
            chunk_id += 1
            
            # Move to next position
            position += self.step_size
        
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
            'strategy': 'fixed',
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
    parser = argparse.ArgumentParser(description="Fixed-size chunking")
    parser.add_argument('input_file', help='Text file to chunk')
    parser.add_argument('--chunk-size', type=int, default=1000, help='Chunk size in characters')
    parser.add_argument('--overlap', type=int, default=200, help='Overlap in characters')
    parser.add_argument('--output-dir', default='chunks_fixed', help='Output directory')
    args = parser.parse_args()
    
    # Read input
    with open(args.input_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    print(f"Input: {args.input_file}")
    print(f"Length: {len(text):,} characters")
    print(f"Chunk size: {args.chunk_size}")
    print(f"Overlap: {args.overlap}\n")
    
    # Chunk
    chunker = FixedChunker(chunk_size=args.chunk_size, chunk_overlap=args.overlap)
    chunks = chunker.chunk(text)
    
    print(f"Generated {len(chunks)} chunks")
    print(f"Avg size: {sum(c['char_count'] for c in chunks) / len(chunks):.0f} chars\n")
    
    # Save
    output_dir = Path(args.output_dir)
    chunker.save_chunks(chunks, output_dir)


if __name__ == "__main__":
    main()
