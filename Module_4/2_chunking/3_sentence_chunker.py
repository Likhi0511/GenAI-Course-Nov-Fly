"""
Sentence-Based Chunking
=======================

Chunks text on sentence boundaries only.

How it works:
    1. Split text into sentences
    2. Add whole sentences to chunk until size limit
    3. Never split mid-sentence
    4. Start new chunk with next sentence

Pros:
    - Natural reading units
    - Never breaks sentences
    - Readable chunks
    - Good for citations

Cons:
    - Variable chunk sizes
    - Sentence detection not perfect
    - May create very small chunks

Use when:
    - Readability important
    - Need to cite specific sentences
    - Generating summaries
    - User-facing content

Example:
    text = "First sentence here. Second sentence here. Third sentence here."
    chunk_size = 50
    
    Chunk 1: "First sentence here. Second sentence here."  (45 chars)
    Chunk 2: "Third sentence here."  (20 chars)
    
    Note: Won't split "Second sentence here." even if it exceeds limit

Usage:
    python 3_sentence_chunker.py text.md
    python 3_sentence_chunker.py text.md --chunk-size 800
"""

import json
import re
import argparse
from pathlib import Path
from typing import List, Dict
from datetime import datetime


class SentenceChunker:
    """Sentence-based chunking - never splits mid-sentence"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100):
        """
        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Number of sentences to overlap (approximate)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using regex
        
        Matches:
            - Period, exclamation, or question mark
            - Followed by space and capital letter
            - Or end of string
        """
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z]|\s*$)', text)
        
        # Clean and filter
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Filter very short sentences (likely artifacts)
        sentences = [s for s in sentences if len(s) > 10]
        
        return sentences
    
    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk text on sentence boundaries
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of chunk dictionaries with metadata
        """
        # Split into sentences
        sentences = self._split_sentences(text)
        
        if not sentences:
            return []
        
        chunks = []
        current_sentences = []
        current_length = 0
        chunk_id = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            
            # Check if adding this sentence would exceed chunk size
            if current_length + sentence_length > self.chunk_size and current_sentences:
                # Save current chunk
                chunk_text = ' '.join(current_sentences)
                chunk = {
                    'chunk_id': chunk_id,
                    'text': chunk_text,
                    'char_count': len(chunk_text),
                    'word_count': len(chunk_text.split()),
                    'sentence_count': len(current_sentences),
                    'sentences': current_sentences.copy(),
                    'metadata': {
                        'strategy': 'sentence',
                        'chunk_size': self.chunk_size
                    }
                }
                chunks.append(chunk)
                chunk_id += 1
                
                # Start new chunk with overlap (last sentence)
                if current_sentences:
                    current_sentences = [current_sentences[-1], sentence]
                    current_length = len(current_sentences[-2]) + sentence_length
                else:
                    current_sentences = [sentence]
                    current_length = sentence_length
            else:
                # Add sentence to current chunk
                current_sentences.append(sentence)
                current_length += sentence_length
        
        # Add last chunk
        if current_sentences:
            chunk_text = ' '.join(current_sentences)
            chunk = {
                'chunk_id': chunk_id,
                'text': chunk_text,
                'char_count': len(chunk_text),
                'word_count': len(chunk_text.split()),
                'sentence_count': len(current_sentences),
                'sentences': current_sentences.copy(),
                'metadata': {
                    'strategy': 'sentence',
                    'chunk_size': self.chunk_size
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
            'strategy': 'sentence',
            'chunk_size': self.chunk_size,
            'created_at': datetime.now().isoformat(),
            'chunks': [
                {
                    'chunk_id': c['chunk_id'],
                    'file': f"chunk_{c['chunk_id']:04d}.json",
                    'char_count': c['char_count'],
                    'sentence_count': c['sentence_count']
                }
                for c in chunks
            ]
        }
        
        with open(output_dir / 'manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(chunks)} chunks to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Sentence-based chunking")
    parser.add_argument('input_file', help='Text file to chunk')
    parser.add_argument('--chunk-size', type=int, default=1000, help='Target chunk size')
    parser.add_argument('--output-dir', default='chunks_sentence', help='Output directory')
    args = parser.parse_args()
    
    # Read input
    with open(args.input_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    print(f"Input: {args.input_file}")
    print(f"Length: {len(text):,} characters")
    print(f"Target chunk size: {args.chunk_size}\n")
    
    # Chunk
    chunker = SentenceChunker(chunk_size=args.chunk_size)
    chunks = chunker.chunk(text)
    
    sizes = [c['char_count'] for c in chunks]
    sentences = [c['sentence_count'] for c in chunks]
    
    print(f"Generated {len(chunks)} chunks")
    print(f"Size range: {min(sizes)} - {max(sizes)} chars")
    print(f"Avg size: {sum(sizes) / len(sizes):.0f} chars")
    print(f"Avg sentences per chunk: {sum(sentences) / len(sentences):.1f}\n")
    
    # Save
    output_dir = Path(args.output_dir)
    chunker.save_chunks(chunks, output_dir)


if __name__ == "__main__":
    main()
