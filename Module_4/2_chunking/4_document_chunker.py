"""
Document-Aware Chunking
=======================

Chunks text while preserving document structure.

How it works:
    1. Detect document sections (headers)
    2. Identify special blocks (figures, tables, code)
    3. Keep sections together
    4. Never split special blocks
    5. Maintain document hierarchy

Pros:
    - Preserves document structure
    - Keeps related content together
    - Never splits tables/figures
    - Best for academic papers
    - Maintains context

Cons:
    - Variable chunk sizes
    - May create large chunks
    - Requires structured documents

Use when:
    - Processing academic papers
    - Documents have clear sections
    - Tables and figures present
    - Structure matters for RAG
    - Quality > uniform size

Example:
    text = "# Introduction\nText here...\n\n| Table |\n\n# Methods\nMore text..."
    
    Chunk 1: "# Introduction\nText here..."  (section)
    Chunk 2: "| Table |"  (table - not split!)
    Chunk 3: "# Methods\nMore text..."  (section)

Usage:
    python 4_document_chunker.py text.md
    python 4_document_chunker.py text.md --max-chunk-size 1500
"""

import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime


class DocumentAwareChunker:
    """Document-aware chunking - preserves structure"""
    
    def __init__(self, max_chunk_size: int = 1500, min_chunk_size: int = 200):
        """
        Args:
            max_chunk_size: Maximum chunk size (soft limit)
            min_chunk_size: Minimum chunk size (will merge small chunks)
        """
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
    
    def _is_header(self, line: str) -> Tuple[bool, int]:
        """Check if line is a markdown header, return (is_header, level)"""
        match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if match:
            return True, len(match.group(1))
        return False, 0
    
    def _is_special_block(self, text: str) -> bool:
        """Check if text is a special block (table, code, figure)"""
        special_markers = [
            '```',              # Code block
            '|',                # Table
            'Figure',           # Figure reference
            'Table',            # Table reference
            'AI Description:',  # Figure description
            'Caption:',         # Figure caption
            '---'              # Horizontal rule
        ]
        return any(marker in text for marker in special_markers)
    
    def _extract_sections(self, text: str) -> List[Dict]:
        """Extract document sections based on headers"""
        lines = text.split('\n')
        sections = []
        current_section = {
            'header': None,
            'level': 0,
            'content': [],
            'start_line': 0
        }
        
        for i, line in enumerate(lines):
            is_header, level = self._is_header(line)
            
            if is_header:
                # Save previous section if it has content
                if current_section['content']:
                    current_section['text'] = '\n'.join(current_section['content'])
                    current_section['end_line'] = i
                    sections.append(current_section)
                
                # Start new section
                current_section = {
                    'header': line,
                    'level': level,
                    'content': [line],
                    'start_line': i
                }
            else:
                current_section['content'].append(line)
        
        # Add last section
        if current_section['content']:
            current_section['text'] = '\n'.join(current_section['content'])
            current_section['end_line'] = len(lines)
            sections.append(current_section)
        
        return sections
    
    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk text while preserving document structure
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of chunk dictionaries with metadata
        """
        # Extract sections
        sections = self._extract_sections(text)
        
        if not sections:
            # No sections found, treat as single chunk
            return [{
                'chunk_id': 0,
                'text': text,
                'char_count': len(text),
                'word_count': len(text.split()),
                'section': None,
                'metadata': {'strategy': 'document_aware'}
            }]
        
        chunks = []
        chunk_id = 0
        
        for section in sections:
            section_text = section['text']
            section_length = len(section_text)
            
            # If section is a special block, keep it together
            if self._is_special_block(section_text):
                chunk = {
                    'chunk_id': chunk_id,
                    'text': section_text,
                    'char_count': section_length,
                    'word_count': len(section_text.split()),
                    'section': {
                        'header': section.get('header'),
                        'level': section.get('level')
                    },
                    'is_special_block': True,
                    'metadata': {
                        'strategy': 'document_aware',
                        'preserved': 'special_block'
                    }
                }
                chunks.append(chunk)
                chunk_id += 1
            
            # If section fits in max size, keep as single chunk
            elif section_length <= self.max_chunk_size:
                chunk = {
                    'chunk_id': chunk_id,
                    'text': section_text,
                    'char_count': section_length,
                    'word_count': len(section_text.split()),
                    'section': {
                        'header': section.get('header'),
                        'level': section.get('level')
                    },
                    'metadata': {
                        'strategy': 'document_aware',
                        'preserved': 'section'
                    }
                }
                chunks.append(chunk)
                chunk_id += 1
            
            # If section too large, split by paragraphs
            else:
                paragraphs = section_text.split('\n\n')
                current_chunk_paras = []
                current_length = 0
                
                for para in paragraphs:
                    para_length = len(para)
                    
                    if current_length + para_length > self.max_chunk_size and current_chunk_paras:
                        # Save current chunk
                        chunk_text = '\n\n'.join(current_chunk_paras)
                        chunk = {
                            'chunk_id': chunk_id,
                            'text': chunk_text,
                            'char_count': len(chunk_text),
                            'word_count': len(chunk_text.split()),
                            'section': {
                                'header': section.get('header'),
                                'level': section.get('level')
                            },
                            'metadata': {
                                'strategy': 'document_aware',
                                'preserved': 'paragraph_boundary'
                            }
                        }
                        chunks.append(chunk)
                        chunk_id += 1
                        
                        # Start new chunk
                        current_chunk_paras = [para]
                        current_length = para_length
                    else:
                        current_chunk_paras.append(para)
                        current_length += para_length
                
                # Add remaining paragraphs
                if current_chunk_paras:
                    chunk_text = '\n\n'.join(current_chunk_paras)
                    chunk = {
                        'chunk_id': chunk_id,
                        'text': chunk_text,
                        'char_count': len(chunk_text),
                        'word_count': len(chunk_text.split()),
                        'section': {
                            'header': section.get('header'),
                            'level': section.get('level')
                        },
                        'metadata': {
                            'strategy': 'document_aware',
                            'preserved': 'paragraph_boundary'
                        }
                    }
                    chunks.append(chunk)
                    chunk_id += 1
        
        # Merge very small chunks
        chunks = self._merge_small_chunks(chunks)
        
        # Re-number chunks
        for i, chunk in enumerate(chunks):
            chunk['chunk_id'] = i
        
        return chunks
    
    def _merge_small_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """Merge chunks that are too small"""
        if len(chunks) <= 1:
            return chunks
        
        merged = []
        i = 0
        
        while i < len(chunks):
            current = chunks[i]
            
            # If chunk is too small and not last, merge with next
            if current['char_count'] < self.min_chunk_size and i < len(chunks) - 1:
                next_chunk = chunks[i + 1]
                merged_text = current['text'] + '\n\n' + next_chunk['text']
                merged_chunk = {
                    'chunk_id': current['chunk_id'],
                    'text': merged_text,
                    'char_count': len(merged_text),
                    'word_count': len(merged_text.split()),
                    'section': current['section'],
                    'metadata': {
                        'strategy': 'document_aware',
                        'preserved': 'merged_small_chunks'
                    }
                }
                merged.append(merged_chunk)
                i += 2  # Skip next chunk
            else:
                merged.append(current)
                i += 1
        
        return merged
    
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
            'strategy': 'document_aware',
            'max_chunk_size': self.max_chunk_size,
            'min_chunk_size': self.min_chunk_size,
            'created_at': datetime.now().isoformat(),
            'chunks': [
                {
                    'chunk_id': c['chunk_id'],
                    'file': f"chunk_{c['chunk_id']:04d}.json",
                    'char_count': c['char_count'],
                    'section': c.get('section', {}).get('header', 'N/A')
                }
                for c in chunks
            ]
        }
        
        with open(output_dir / 'manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(chunks)} chunks to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Document-aware chunking")
    parser.add_argument('input_file', help='Text file to chunk')
    parser.add_argument('--max-chunk-size', type=int, default=1500, help='Max chunk size')
    parser.add_argument('--min-chunk-size', type=int, default=200, help='Min chunk size')
    parser.add_argument('--output-dir', default='chunks_document', help='Output directory')
    args = parser.parse_args()
    
    # Read input
    with open(args.input_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    print(f"Input: {args.input_file}")
    print(f"Length: {len(text):,} characters")
    print(f"Max chunk size: {args.max_chunk_size}")
    print(f"Min chunk size: {args.min_chunk_size}\n")
    
    # Chunk
    chunker = DocumentAwareChunker(
        max_chunk_size=args.max_chunk_size,
        min_chunk_size=args.min_chunk_size
    )
    chunks = chunker.chunk(text)
    
    sizes = [c['char_count'] for c in chunks]
    special_blocks = sum(1 for c in chunks if c.get('is_special_block', False))
    
    print(f"Generated {len(chunks)} chunks")
    print(f"Size range: {min(sizes)} - {max(sizes)} chars")
    print(f"Avg size: {sum(sizes) / len(sizes):.0f} chars")
    print(f"Special blocks preserved: {special_blocks}\n")
    
    # Save
    output_dir = Path(args.output_dir)
    chunker.save_chunks(chunks, output_dir)


if __name__ == "__main__":
    main()
