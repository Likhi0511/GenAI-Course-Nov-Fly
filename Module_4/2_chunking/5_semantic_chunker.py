"""
Semantic Chunking Implementation
=================================

Semantic chunking using sentence embeddings and similarity.

How it works:
1. Split text into sentences
2. Generate embeddings for each sentence
3. Calculate similarity between consecutive sentences
4. Group sentences with high similarity together
5. Create chunks from similar sentence groups

Why this is better:
- Groups semantically similar content
- Natural topic boundaries
- Better retrieval accuracy
- Coherent chunks

Algorithm:
    For each sentence:
        - Compute embedding
        - Compare with previous sentence
        - If similarity > threshold: add to current chunk
        - If similarity < threshold: start new chunk
        
Example:
    S1: "Transformers use attention mechanisms."
    S2: "Attention allows focusing on relevant parts."
    S3: "We trained the model on 40GB of data."
    
    Embeddings:
    S1 ≈ S2 (similarity: 0.85) → Same chunk
    S2 ≉ S3 (similarity: 0.42) → New chunk
    
    Result:
    Chunk 1: S1 + S2 (about attention)
    Chunk 2: S3 (about training)

Usage:
    python 5_semantic_chunker.py text.md
    python 5_semantic_chunker.py text.md --similarity-threshold 0.7
"""

import numpy as np
import re
from pathlib import Path
from typing import List, Tuple
from sentence_transformers import SentenceTransformer
import tiktoken


class SemanticChunker:
    """
    Semantic chunking using sentence embeddings and similarity
    """
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.75,
        min_chunk_size: int = 200,
        max_chunk_size: int = 1500
    ):
        """
        Args:
            model_name: Sentence transformer model
            similarity_threshold: Similarity threshold for grouping (0.0-1.0)
            min_chunk_size: Minimum chunk size in characters
            max_chunk_size: Maximum chunk size in characters
        """
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        
        print(f"Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        print("✓ Model loaded\n")
        
        # Initialize tokenizer for token counting
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except:
            self.tokenizer = None
    
    def chunk(self, text: str, verbose: bool = True) -> List[dict]:
        """
        Perform semantic chunking
        
        Returns:
            List of chunks with metadata
        """
        if verbose:
            print("="*70)
            print("SEMANTIC CHUNKING")
            print("="*70)
            print(f"Similarity threshold: {self.similarity_threshold}")
            print(f"Min chunk size: {self.min_chunk_size} chars")
            print(f"Max chunk size: {self.max_chunk_size} chars\n")
        
        # Step 1: Split into sentences
        if verbose:
            print("[1/4] Splitting into sentences...")
        sentences = self._split_sentences(text)
        if verbose:
            print(f"✓ Found {len(sentences)} sentences\n")
        
        if len(sentences) == 0:
            return []
        
        # Step 2: Generate embeddings
        if verbose:
            print("[2/4] Generating sentence embeddings...")
        embeddings = self.model.encode(sentences, show_progress_bar=verbose)
        if verbose:
            print(f"✓ Generated {len(embeddings)} embeddings\n")
        
        # Step 3: Calculate similarities
        if verbose:
            print("[3/4] Calculating sentence similarities...")
        similarities = self._calculate_similarities(embeddings)
        if verbose:
            print(f"✓ Calculated {len(similarities)} similarity scores\n")
        
        # Step 4: Group sentences into chunks
        if verbose:
            print("[4/4] Grouping sentences into semantic chunks...")
        chunks = self._group_sentences(sentences, similarities, embeddings)
        if verbose:
            print(f"✓ Created {len(chunks)} semantic chunks\n")
        
        # Enrich with metadata
        enriched_chunks = self._enrich_chunks(chunks, embeddings)
        
        if verbose:
            self._print_summary(enriched_chunks, similarities)
        
        return enriched_chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using regex
        """
        # Split on sentence boundaries
        # Matches: . ! ? followed by space and capital letter or end of string
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z]|\s*$)', text)
        
        # Clean and filter
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Filter out very short sentences (likely artifacts)
        sentences = [s for s in sentences if len(s) > 20]
        
        return sentences
    
    def _calculate_similarities(self, embeddings: np.ndarray) -> List[float]:
        """
        Calculate cosine similarity between consecutive sentences
        
        Returns:
            List of similarities where similarities[i] is similarity between
            sentence i and sentence i+1
        """
        similarities = []
        
        for i in range(len(embeddings) - 1):
            # Cosine similarity
            similarity = self._cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(similarity)
        
        return similarities
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    
    def _group_sentences(
        self, 
        sentences: List[str], 
        similarities: List[float],
        embeddings: np.ndarray
    ) -> List[dict]:
        """
        Group sentences into chunks based on similarity
        
        Algorithm:
            - Start with first sentence in chunk
            - For each next sentence:
                - If similarity > threshold AND size < max: add to current chunk
                - Else: start new chunk
            - Ensure min chunk size (merge small chunks)
        """
        if len(sentences) == 0:
            return []
        
        chunks = []
        current_chunk_sentences = [sentences[0]]
        current_chunk_size = len(sentences[0])
        
        for i in range(1, len(sentences)):
            sentence = sentences[i]
            sentence_size = len(sentence)
            prev_similarity = similarities[i - 1]
            
            # Decision: Add to current chunk or start new?
            should_add = (
                prev_similarity >= self.similarity_threshold and
                current_chunk_size + sentence_size <= self.max_chunk_size
            )
            
            if should_add:
                # Add to current chunk
                current_chunk_sentences.append(sentence)
                current_chunk_size += sentence_size
            else:
                # Start new chunk
                # Save current chunk
                chunks.append({
                    'sentences': current_chunk_sentences,
                    'text': ' '.join(current_chunk_sentences),
                    'size': current_chunk_size,
                    'boundary_similarity': prev_similarity
                })
                
                # Start new chunk
                current_chunk_sentences = [sentence]
                current_chunk_size = sentence_size
        
        # Add last chunk
        if current_chunk_sentences:
            chunks.append({
                'sentences': current_chunk_sentences,
                'text': ' '.join(current_chunk_sentences),
                'size': current_chunk_size,
                'boundary_similarity': None  # Last chunk has no next
            })
        
        # Merge small chunks
        chunks = self._merge_small_chunks(chunks)
        
        return chunks
    
    def _merge_small_chunks(self, chunks: List[dict]) -> List[dict]:
        """
        Merge chunks that are too small
        """
        if len(chunks) <= 1:
            return chunks
        
        merged_chunks = []
        i = 0
        
        while i < len(chunks):
            current_chunk = chunks[i]
            
            # If chunk is too small and not the last chunk
            if current_chunk['size'] < self.min_chunk_size and i < len(chunks) - 1:
                # Merge with next chunk
                next_chunk = chunks[i + 1]
                merged_chunk = {
                    'sentences': current_chunk['sentences'] + next_chunk['sentences'],
                    'text': current_chunk['text'] + ' ' + next_chunk['text'],
                    'size': current_chunk['size'] + next_chunk['size'],
                    'boundary_similarity': next_chunk.get('boundary_similarity')
                }
                merged_chunks.append(merged_chunk)
                i += 2  # Skip next chunk (already merged)
            else:
                merged_chunks.append(current_chunk)
                i += 1
        
        return merged_chunks
    
    def _enrich_chunks(self, chunks: List[dict], all_embeddings: np.ndarray) -> List[dict]:
        """
        Add metadata to chunks
        """
        enriched = []
        
        for i, chunk in enumerate(chunks):
            # Calculate average embedding for chunk
            sentence_indices = self._get_sentence_indices(chunk['sentences'], all_embeddings)
            chunk_embedding = np.mean([all_embeddings[idx] for idx in sentence_indices], axis=0)
            
            enriched_chunk = {
                'chunk_id': i + 1,
                'text': chunk['text'],
                'sentences': chunk['sentences'],
                'sentence_count': len(chunk['sentences']),
                'char_count': chunk['size'],
                'word_count': len(chunk['text'].split()),
                'token_count': self._count_tokens(chunk['text']),
                'embedding': chunk_embedding.tolist(),
                'boundary_similarity': chunk.get('boundary_similarity'),
                'metadata': {
                    'chunking_method': 'semantic',
                    'embedding_model': self.model_name,
                    'similarity_threshold': self.similarity_threshold
                }
            }
            
            enriched.append(enriched_chunk)
        
        return enriched
    
    def _get_sentence_indices(self, sentences: List[str], all_embeddings: np.ndarray) -> List[int]:
        """Find indices of sentences in original list"""
        # This is a simplified version - in production you'd track this better
        return list(range(len(sentences)))
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens"""
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except:
                pass
        return None
    
    def _print_summary(self, chunks: List[dict], similarities: List[float]):
        """Print chunking summary"""
        print("="*70)
        print("SEMANTIC CHUNKING SUMMARY")
        print("="*70)
        print()
        
        print(f"Total Chunks: {len(chunks)}")
        print(f"Total Sentences: {sum(c['sentence_count'] for c in chunks)}")
        print()
        
        # Size statistics
        sizes = [c['char_count'] for c in chunks]
        print(f"Chunk Sizes:")
        print(f"  Min: {min(sizes)} chars")
        print(f"  Max: {max(sizes)} chars")
        print(f"  Avg: {sum(sizes) / len(sizes):.0f} chars")
        print()
        
        # Similarity statistics
        boundary_sims = [c['boundary_similarity'] for c in chunks if c['boundary_similarity'] is not None]
        if boundary_sims:
            print(f"Boundary Similarities (where chunks split):")
            print(f"  Min: {min(boundary_sims):.3f}")
            print(f"  Max: {max(boundary_sims):.3f}")
            print(f"  Avg: {sum(boundary_sims) / len(boundary_sims):.3f}")
            print()
        
        # Show first 3 chunks
        print("Sample Chunks:")
        for i, chunk in enumerate(chunks[:3]):
            print(f"\n  Chunk {i+1}:")
            print(f"    Sentences: {chunk['sentence_count']}")
            print(f"    Size: {chunk['char_count']} chars")
            print(f"    Preview: {chunk['text'][:100]}...")
            if chunk['boundary_similarity']:
                print(f"    Next chunk similarity: {chunk['boundary_similarity']:.3f}")


def visualize_similarities(sentences: List[str], similarities: List[float], threshold: float):
    """
    Visualize sentence similarities to see where chunks will split
    """
    print("\n" + "="*70)
    print("SENTENCE SIMILARITY VISUALIZATION")
    print("="*70)
    print(f"Threshold: {threshold:.3f} (splits happen below this)\n")
    
    for i in range(min(10, len(similarities))):  # Show first 10
        sim = similarities[i]
        
        # Visual bar
        bar_length = int(sim * 50)
        bar = "█" * bar_length + "░" * (50 - bar_length)
        
        # Mark if below threshold (chunk boundary)
        marker = " ⬅️ CHUNK BOUNDARY" if sim < threshold else ""
        
        print(f"S{i+1} → S{i+2}: {sim:.3f} {bar}{marker}")
        
        # Show sentence previews
        print(f"  S{i+1}: {sentences[i][:60]}...")
        print(f"  S{i+2}: {sentences[i+1][:60]}...")
        print()


def main():
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Semantic Text Chunking")
    parser.add_argument('input_file', help='Text file to chunk')
    parser.add_argument('--similarity-threshold', type=float, default=0.75,
                       help='Similarity threshold (0.0-1.0, default: 0.75)')
    parser.add_argument('--min-size', type=int, default=200,
                       help='Minimum chunk size in characters')
    parser.add_argument('--max-size', type=int, default=1500,
                       help='Maximum chunk size in characters')
    parser.add_argument('--model', default='all-MiniLM-L6-v2',
                       help='Sentence transformer model')
    parser.add_argument('--visualize', action='store_true',
                       help='Show similarity visualization')
    parser.add_argument('--output', help='Output JSON file')
    
    args = parser.parse_args()
    
    # Read input
    input_file = Path(args.input_file)
    if not input_file.exists():
        print(f"Error: File not found: {input_file}")
        return
    
    with open(input_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    print(f"Input: {input_file}")
    print(f"Length: {len(text):,} characters\n")
    
    # Create chunker
    chunker = SemanticChunker(
        model_name=args.model,
        similarity_threshold=args.similarity_threshold,
        min_chunk_size=args.min_size,
        max_chunk_size=args.max_size
    )
    
    # Chunk
    chunks = chunker.chunk(text, verbose=True)
    
    # Visualize if requested
    if args.visualize:
        sentences = chunker._split_sentences(text)
        embeddings = chunker.model.encode(sentences, show_progress_bar=False)
        similarities = chunker._calculate_similarities(embeddings)
        visualize_similarities(sentences, similarities, args.similarity_threshold)
    
    # Save if requested
    if args.output:
        output_file = Path(args.output)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Saved to: {output_file}")
    
    print("\n" + "="*70)
    print("Example Usage in RAG:")
    print("="*70)
    print("""
    # 1. Semantic chunking creates coherent chunks
    chunks = chunker.chunk(document_text)
    
    # 2. Chunks already have embeddings!
    for chunk in chunks:
        embedding = chunk['embedding']  # Already computed!
        store_in_vectordb(chunk['text'], embedding)
    
    # 3. Better retrieval because chunks are semantically coherent
    query = "How does attention work?"
    # Will retrieve chunks that discuss attention together
    """)


if __name__ == "__main__":
    main()
