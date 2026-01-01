"""
Page-Level Chunking
===================

Chunks documents by pages - one chunk per page.

How it works:
    1. Detect page boundaries in text
    2. Create one chunk per page
    3. Preserve page numbers
    4. Keep page content intact

Pros:
    - Natural document unit
    - Easy to cite (page numbers)
    - Preserves original structure
    - Good for PDFs
    - Simple to understand

Cons:
    - Variable chunk sizes
    - May split topics across pages
    - Not all documents have pages
    - May be too large/small

Use when:
    - Processing PDFs with clear pages
    - Need to cite page numbers
    - Documents already paginated
    - Legal/academic documents
    - Page-level accuracy matters

Example:
    PDF with 3 pages:
    
    Chunk 1: Page 1 content (all of it)
    Chunk 2: Page 2 content (all of it)
    Chunk 3: Page 3 content (all of it)
    
    Each chunk maintains page number for citations

Common Sources:
    - PDFs (natural pages)
    - Docling output (preserves pages)
    - LlamaParse (includes page numbers)
    - Unstructured (page metadata)

Usage:
    python 6_page_chunker.py text.md
    python 6_page_chunker.py extracted_documents/paper/text.md
"""

import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


class PageChunker:
    """Page-level chunking - one chunk per page"""
    
    def __init__(self, page_separator: str = "\n---PAGE_BREAK---\n"):
        """
        Args:
            page_separator: String that separates pages in text
                           Common formats:
                           - "\n---PAGE_BREAK---\n" (custom)
                           - "\f" (form feed)
                           - "<!-- PAGE N -->" (HTML comment)
        """
        self.page_separator = page_separator
    
    def _detect_pages_from_docling(self, text: str) -> List[Dict]:
        """
        Detect pages from Docling-extracted text
        
        Docling often includes page markers like:
        <!-- PAGE 1 -->
        or
        [Page 1]
        """
        # Try HTML comment style
        pages = re.split(r'<!--\s*PAGE\s+(\d+)\s*-->', text, flags=re.IGNORECASE)
        
        if len(pages) > 1:
            # Found HTML-style page markers
            chunks = []
            for i in range(1, len(pages), 2):
                page_num = int(pages[i])
                page_content = pages[i + 1].strip() if i + 1 < len(pages) else ""
                if page_content:
                    chunks.append({
                        'page_number': page_num,
                        'text': page_content
                    })
            return chunks
        
        # Try bracket style
        pages = re.split(r'\[Page\s+(\d+)\]', text, flags=re.IGNORECASE)
        
        if len(pages) > 1:
            chunks = []
            for i in range(1, len(pages), 2):
                page_num = int(pages[i])
                page_content = pages[i + 1].strip() if i + 1 < len(pages) else ""
                if page_content:
                    chunks.append({
                        'page_number': page_num,
                        'text': page_content
                    })
            return chunks
        
        return []
    
    def _detect_pages_from_separator(self, text: str) -> List[Dict]:
        """Detect pages using explicit separator"""
        pages = text.split(self.page_separator)
        
        chunks = []
        for i, page_content in enumerate(pages):
            page_content = page_content.strip()
            if page_content:
                chunks.append({
                    'page_number': i + 1,
                    'text': page_content
                })
        
        return chunks
    
    def _detect_pages_from_form_feed(self, text: str) -> List[Dict]:
        """Detect pages using form feed character (\\f)"""
        pages = text.split('\f')
        
        chunks = []
        for i, page_content in enumerate(pages):
            page_content = page_content.strip()
            if page_content:
                chunks.append({
                    'page_number': i + 1,
                    'text': page_content
                })
        
        return chunks
    
    def _estimate_pages_by_length(self, text: str, chars_per_page: int = 3000) -> List[Dict]:
        """
        Fallback: Estimate pages by character count
        
        Typical page: ~500 words = ~3000 characters
        """
        chunks = []
        start = 0
        page_num = 1
        
        while start < len(text):
            end = start + chars_per_page
            
            # Try to break at paragraph
            if end < len(text):
                # Look for paragraph break near the end
                search_start = max(start, end - 500)
                search_end = min(len(text), end + 500)
                search_text = text[search_start:search_end]
                
                para_break = search_text.find('\n\n')
                if para_break != -1:
                    end = search_start + para_break
            
            page_content = text[start:end].strip()
            
            if page_content:
                chunks.append({
                    'page_number': page_num,
                    'text': page_content,
                    'estimated': True
                })
                page_num += 1
            
            start = end
        
        return chunks
    
    def chunk(self, text: str, auto_detect: bool = True) -> List[Dict]:
        """
        Chunk text by pages
        
        Args:
            text: Input text to chunk
            auto_detect: Try to automatically detect page boundaries
            
        Returns:
            List of chunk dictionaries with page metadata
        """
        chunks = []
        
        if auto_detect:
            # Try different detection methods
            
            # Method 1: Docling-style markers
            chunks = self._detect_pages_from_docling(text)
            if chunks:
                print(f"✓ Detected {len(chunks)} pages (Docling markers)")
            
            # Method 2: Custom separator
            if not chunks:
                chunks = self._detect_pages_from_separator(text)
                if chunks:
                    print(f"✓ Detected {len(chunks)} pages (custom separator)")
            
            # Method 3: Form feed
            if not chunks:
                chunks = self._detect_pages_from_form_feed(text)
                if chunks:
                    print(f"✓ Detected {len(chunks)} pages (form feed)")
            
            # Method 4: Estimate by length
            if not chunks:
                print("⚠️  No page markers found, estimating pages by length")
                chunks = self._estimate_pages_by_length(text)
                if chunks:
                    print(f"✓ Estimated {len(chunks)} pages (~3000 chars each)")
        else:
            # Use only separator
            chunks = self._detect_pages_from_separator(text)
        
        # Enrich with metadata
        enriched_chunks = []
        for i, page_data in enumerate(chunks):
            chunk = {
                'chunk_id': i,
                'page_number': page_data['page_number'],
                'text': page_data['text'],
                'char_count': len(page_data['text']),
                'word_count': len(page_data['text'].split()),
                'estimated': page_data.get('estimated', False),
                'metadata': {
                    'strategy': 'page',
                    'page_separator': self.page_separator if not page_data.get('estimated') else 'estimated'
                }
            }
            enriched_chunks.append(chunk)
        
        return enriched_chunks
    
    def save_chunks(self, chunks: List[Dict], output_dir: Path):
        """Save chunks to individual JSON files"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for chunk in chunks:
            # Use page number in filename
            filename = output_dir / f"page_{chunk['page_number']:04d}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(chunk, f, indent=2, ensure_ascii=False)
        
        # Save manifest
        manifest = {
            'total_pages': len(chunks),
            'strategy': 'page',
            'created_at': datetime.now().isoformat(),
            'chunks': [
                {
                    'chunk_id': c['chunk_id'],
                    'page_number': c['page_number'],
                    'file': f"page_{c['page_number']:04d}.json",
                    'char_count': c['char_count'],
                    'estimated': c.get('estimated', False)
                }
                for c in chunks
            ]
        }
        
        with open(output_dir / 'manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(chunks)} pages to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Page-level chunking")
    parser.add_argument('input_file', help='Text file to chunk')
    parser.add_argument('--separator', default='\n---PAGE_BREAK---\n',
                       help='Page separator string')
    parser.add_argument('--no-auto-detect', action='store_true',
                       help='Disable auto-detection of page markers')
    parser.add_argument('--output-dir', default='chunks_page', help='Output directory')
    args = parser.parse_args()
    
    # Read input
    with open(args.input_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    print(f"Input: {args.input_file}")
    print(f"Length: {len(text):,} characters\n")
    
    # Chunk
    chunker = PageChunker(page_separator=args.separator)
    chunks = chunker.chunk(text, auto_detect=not args.no_auto_detect)
    
    if not chunks:
        print("❌ No pages detected!")
        return
    
    sizes = [c['char_count'] for c in chunks]
    estimated = sum(1 for c in chunks if c.get('estimated', False))
    
    print(f"\nGenerated {len(chunks)} page chunks")
    print(f"Size range: {min(sizes)} - {max(sizes)} chars")
    print(f"Avg size: {sum(sizes) / len(sizes):.0f} chars")
    if estimated:
        print(f"Estimated pages: {estimated} (no markers found)\n")
    else:
        print()
    
    # Show sample pages
    print("Sample Pages:")
    for chunk in chunks[:3]:
        print(f"  Page {chunk['page_number']}: {chunk['char_count']} chars")
        print(f"    Preview: {chunk['text'][:80]}...")
        print()
    
    # Save
    output_dir = Path(args.output_dir)
    chunker.save_chunks(chunks, output_dir)


if __name__ == "__main__":
    main()
