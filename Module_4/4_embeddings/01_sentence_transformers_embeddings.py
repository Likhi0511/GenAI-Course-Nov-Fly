"""
================================================================================
SENTENCE TRANSFORMERS EMBEDDINGS GENERATOR
================================================================================

Purpose: Generate embeddings locally using Sentence Transformers (free, open-source)

Author: Prudhvi
Created: January 2025

Features:
- Local processing (no API calls)
- Free to use
- 384-dimensional embeddings
- Batch processing for efficiency
- Progress tracking
- Error handling
- In-place modification (adds 'embedding' field to existing chunks)

Model: all-MiniLM-L6-v2
- Dimensions: 384
- Speed: Fast
- Quality: Good for most use cases
- Size: 80MB download

Usage:
    python 01_sentence_transformers_embeddings.py <input_file>
    
Example:
    python 01_sentence_transformers_embeddings.py data/chunks.json
    
Output:
    data/chunks_sentence_transformers_embeddings.json
================================================================================
"""

import json
import numpy as np
import sys
import argparse
from sentence_transformers import SentenceTransformer
from datetime import datetime
import logging
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SentenceTransformerEmbedder:
    """
    Generate embeddings using Sentence Transformers.
    
    This class handles:
    - Loading the embedding model
    - Batch processing for efficiency
    - Progress tracking
    - Saving results with metadata
    """
    
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2', batch_size: int = 32):
        """
        Initialize the embedder.
        
        Args:
            model_name: Sentence Transformers model name
            batch_size: Number of texts to process at once
        """
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = None
        
        logger.info(f"Initializing SentenceTransformerEmbedder")
        logger.info(f"Model: {model_name}")
        logger.info(f"Batch size: {batch_size}")
    
    def load_model(self):
        """Load the Sentence Transformers model."""
        logger.info(f"Loading model: {self.model_name}")
        logger.info("This may take a minute on first run (downloading model)...")
        
        self.model = SentenceTransformer(self.model_name)
        
        logger.info(f"Model loaded successfully")
        logger.info(f"Embedding dimensions: {self.model.get_sentence_embedding_dimension()}")
    
    def load_chunks(self, input_file: str) -> List[Dict]:
        """
        Load chunks from JSON file.
        
        Args:
            input_file: Path to input JSON file
            
        Returns:
            List of chunk dictionaries
        """
        logger.info(f"Loading chunks from: {input_file}")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        chunks = data['chunks']
        logger.info(f"Loaded {len(chunks)} chunks")
        
        return chunks
    
    def generate_embeddings(self, chunks: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for all chunks.
        
        Args:
            chunks: List of chunk dictionaries
            
        Returns:
            List of chunks with embeddings added
        """
        logger.info("Generating embeddings...")
        logger.info(f"Processing {len(chunks)} chunks in batches of {self.batch_size}")
        
        # Extract content_only field for embedding
        texts = [chunk['content_only'] for chunk in chunks]
        
        # Generate embeddings with progress bar
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True  # L2 normalization for cosine similarity
        )
        
        # Add embeddings to chunks
        enriched_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            enriched_chunk = chunk.copy()
            enriched_chunk['embedding'] = embedding.tolist()  # Convert numpy to list
            enriched_chunk['embedding_metadata'] = {
                'model': self.model_name,
                'dimensions': len(embedding),
                'normalized': True,
                'generated_at': datetime.now().isoformat()
            }
            enriched_chunks.append(enriched_chunk)
        
        logger.info(f"Generated {len(enriched_chunks)} embeddings")
        
        return enriched_chunks
    
    def save_results(self, chunks: List[Dict], input_file: str):
        """
        Save chunks with embeddings to JSON file.
        Output file is created in same directory as input with modified name.
        
        Args:
            chunks: List of chunks with embeddings
            input_file: Path to input file (used to determine output location)
        """
        # Generate output filename in same directory
        input_path = Path(input_file)
        output_file = input_path.parent / f"{input_path.stem}_sentence_transformers_embeddings{input_path.suffix}"
        
        logger.info(f"Saving results to: {output_file}")
        
        output_data = {
            'metadata': {
                'model': self.model_name,
                'dimensions': self.model.get_sentence_embedding_dimension(),
                'total_chunks': len(chunks),
                'generated_at': datetime.now().isoformat(),
                'embedding_config': {
                    'batch_size': self.batch_size,
                    'normalized': True,
                    'model_type': 'sentence-transformers'
                }
            },
            'chunks': chunks
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        # Calculate file size
        file_size_mb = output_file.stat().st_size / (1024 * 1024)
        logger.info(f"Saved successfully ({file_size_mb:.2f} MB)")
        
        return str(output_file)
    
    def process(self, input_file: str):
        """
        Complete pipeline: load → embed → save.
        
        Args:
            input_file: Path to input JSON file
            
        Returns:
            Path to output file
        """
        start_time = datetime.now()
        logger.info("="*80)
        logger.info("STARTING EMBEDDING GENERATION")
        logger.info("="*80)
        
        # Load model
        self.load_model()
        
        # Load chunks
        chunks = self.load_chunks(input_file)
        
        # Generate embeddings
        enriched_chunks = self.generate_embeddings(chunks)
        
        # Save results
        output_file = self.save_results(enriched_chunks, input_file)
        
        # Summary
        elapsed_time = (datetime.now() - start_time).total_seconds()
        logger.info("="*80)
        logger.info("EMBEDDING GENERATION COMPLETE")
        logger.info(f"Total time: {elapsed_time:.2f} seconds")
        logger.info(f"Average time per chunk: {elapsed_time/len(chunks):.3f} seconds")
        logger.info(f"Output file: {output_file}")
        logger.info("="*80)
        
        return output_file


def main():
    """Main execution function."""
    
    # Setup argument parser
    parser = argparse.ArgumentParser(
        description='Generate embeddings using Sentence Transformers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python 01_sentence_transformers_embeddings.py data/chunks.json
  python 01_sentence_transformers_embeddings.py /path/to/my_chunks.json
  
Output:
  Input:  data/chunks.json
  Output: data/chunks_sentence_transformers_embeddings.json
        '''
    )
    
    parser.add_argument(
        'input_file',
        type=str,
        help='Path to input JSON file containing chunks'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='all-MiniLM-L6-v2',
        help='Sentence Transformers model name (default: all-MiniLM-L6-v2)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=32,
        help='Batch size for processing (default: 32)'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate input file exists
    if not Path(args.input_file).exists():
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)
    
    print("="*80)
    print("SENTENCE TRANSFORMERS EMBEDDING GENERATION")
    print("="*80)
    print(f"Input file: {args.input_file}")
    print(f"Model: {args.model}")
    print(f"Batch size: {args.batch_size}")
    print(f"Dimensions: 384")
    print(f"Cost: FREE")
    print("="*80)
    print()
    
    # Create embedder and process
    embedder = SentenceTransformerEmbedder(
        model_name=args.model,
        batch_size=args.batch_size
    )
    
    output_file = embedder.process(args.input_file)
    
    print("\n" + "="*80)
    print("SUCCESS!")
    print("="*80)
    print(f"Input:  {args.input_file}")
    print(f"Output: {output_file}")
    print("\nEmbedding field added to each chunk!")
    print("\nYou can now use these embeddings for:")
    print("  - Semantic search")
    print("  - Document clustering")
    print("  - RAG systems")
    print("  - Similarity analysis")
    print("="*80)


if __name__ == "__main__":
    main()
