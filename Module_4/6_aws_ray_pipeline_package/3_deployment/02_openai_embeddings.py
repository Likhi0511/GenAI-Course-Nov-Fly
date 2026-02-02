"""
================================================================================
OPENAI EMBEDDINGS GENERATOR
================================================================================

Purpose: Generate embeddings using OpenAI's Embeddings API (best quality)

Author: Prudhvi
Created: January 2025

Features:
- State-of-the-art quality
- 1536 or 3072 dimensions
- Automatic retry logic
- Rate limiting handling
- Cost tracking
- Progress tracking
- In-place modification (adds 'embedding' field to existing chunks)

Model: text-embedding-3-small (default)
- Dimensions: 1536
- Cost: $0.020 per 1M tokens
- Quality: Excellent

Alternative: text-embedding-3-large
- Dimensions: 3072
- Cost: $0.130 per 1M tokens
- Quality: Best available

Usage:
    python 02_openai_embeddings.py <input_file> [--model MODEL] [--dimensions DIM]
    
Example:
    python 02_openai_embeddings.py data/chunks.json
    python 02_openai_embeddings.py data/chunks.json --model text-embedding-3-large --dimensions 3072
    
Output:
    data/chunks_openai_embeddings.json
================================================================================
"""

import json
import os
import sys
import argparse
from openai import OpenAI
from datetime import datetime
import logging
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm
import time
from tenacity import retry, stop_after_attempt, wait_exponential

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OpenAIEmbedder:
    """
    Generate embeddings using OpenAI's Embeddings API.
    
    This class handles:
    - API authentication
    - Batch processing with rate limiting
    - Automatic retries on failures
    - Cost tracking
    - Progress monitoring
    """
    
    def __init__(
        self, 
        model: str = 'text-embedding-3-small',
        dimensions: int = 1536,
        batch_size: int = 100
    ):
        """
        Initialize the embedder.
        
        Args:
            model: OpenAI embedding model name
            dimensions: Embedding dimensions (1536 or 3072 for small, up to 3072 for large)
            batch_size: Number of texts per API call (max 2048)
        """
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.client = None
        self.total_tokens = 0
        
        logger.info(f"Initializing OpenAIEmbedder")
        logger.info(f"Model: {model}")
        logger.info(f"Dimensions: {dimensions}")
        logger.info(f"Batch size: {batch_size}")
    
    def initialize_client(self):
        """Initialize OpenAI client with API key."""
        api_key = os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Please set OPENAI_API_KEY environment variable:\n"
                "export OPENAI_API_KEY='your-api-key-here'"
            )
        
        self.client = OpenAI(api_key=api_key)
        logger.info("OpenAI client initialized successfully")
    
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
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Get embeddings for a batch of texts with retry logic.
        
        Args:
            texts: List of text strings
            
        Returns:
            List of embedding vectors
        """
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions
        )
        
        # Track token usage
        self.total_tokens += response.usage.total_tokens
        
        # Extract embeddings in order
        embeddings = [item.embedding for item in response.data]
        
        return embeddings
    
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
        
        enriched_chunks = []
        
        # Process in batches with progress bar
        for i in tqdm(range(0, len(chunks), self.batch_size), desc="Embedding batches"):
            batch = chunks[i:i + self.batch_size]
            
            # Extract content_only field
            texts = [chunk['content_only'] for chunk in batch]
            
            # Get embeddings for batch
            try:
                embeddings = self.get_embeddings_batch(texts)
                
                # Add embeddings to chunks
                for chunk, embedding in zip(batch, embeddings):
                    enriched_chunk = chunk.copy()
                    enriched_chunk['embedding'] = embedding
                    enriched_chunk['embedding_metadata'] = {
                        'model': self.model,
                        'dimensions': self.dimensions,
                        'generated_at': datetime.now().isoformat()
                    }
                    enriched_chunks.append(enriched_chunk)
                
                # Small delay to respect rate limits
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error processing batch {i//self.batch_size + 1}: {str(e)}")
                raise
        
        logger.info(f"Generated {len(enriched_chunks)} embeddings")
        logger.info(f"Total tokens used: {self.total_tokens:,}")
        
        return enriched_chunks
    
    def calculate_cost(self) -> Dict[str, float]:
        """
        Calculate API cost based on tokens used.
        
        Returns:
            Dictionary with cost breakdown
        """
        # Pricing per 1M tokens (as of Jan 2025)
        pricing = {
            'text-embedding-3-small': 0.020,  # $0.020 per 1M tokens
            'text-embedding-3-large': 0.130   # $0.130 per 1M tokens
        }
        
        price_per_million = pricing.get(self.model, 0.020)
        cost = (self.total_tokens / 1_000_000) * price_per_million
        
        return {
            'total_tokens': self.total_tokens,
            'price_per_million_tokens': price_per_million,
            'total_cost_usd': round(cost, 4)
        }
    
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
        output_file = input_path.parent / f"{input_path.stem}_openai_embeddings{input_path.suffix}"
        
        logger.info(f"Saving results to: {output_file}")
        
        cost_info = self.calculate_cost()
        
        output_data = {
            'metadata': {
                'model': self.model,
                'dimensions': self.dimensions,
                'total_chunks': len(chunks),
                'generated_at': datetime.now().isoformat(),
                'embedding_config': {
                    'batch_size': self.batch_size,
                    'model_type': 'openai'
                },
                'cost_tracking': cost_info
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
        logger.info("STARTING OPENAI EMBEDDING GENERATION")
        logger.info("="*80)
        
        # Initialize client
        self.initialize_client()
        
        # Load chunks
        chunks = self.load_chunks(input_file)
        
        # Generate embeddings
        enriched_chunks = self.generate_embeddings(chunks)
        
        # Save results
        output_file = self.save_results(enriched_chunks, input_file)
        
        # Summary
        elapsed_time = (datetime.now() - start_time).total_seconds()
        cost_info = self.calculate_cost()
        
        logger.info("="*80)
        logger.info("EMBEDDING GENERATION COMPLETE")
        logger.info(f"Total time: {elapsed_time:.2f} seconds")
        logger.info(f"Average time per chunk: {elapsed_time/len(chunks):.3f} seconds")
        logger.info(f"Total tokens: {cost_info['total_tokens']:,}")
        logger.info(f"Total cost: ${cost_info['total_cost_usd']:.4f} USD")
        logger.info(f"Output file: {output_file}")
        logger.info("="*80)
        
        return output_file


def main():
    """Main execution function."""
    
    # Setup argument parser
    parser = argparse.ArgumentParser(
        description='Generate embeddings using OpenAI Embeddings API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python 02_openai_embeddings.py data/chunks.json
  python 02_openai_embeddings.py data/chunks.json --model text-embedding-3-large
  python 02_openai_embeddings.py data/chunks.json --dimensions 3072
  
Output:
  Input:  data/chunks.json
  Output: data/chunks_openai_embeddings.json
  
Cost:
  text-embedding-3-small (1536D): $0.020 per 1M tokens
  text-embedding-3-large (3072D): $0.130 per 1M tokens
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
        default='text-embedding-3-small',
        choices=['text-embedding-3-small', 'text-embedding-3-large'],
        help='OpenAI embedding model (default: text-embedding-3-small)'
    )
    
    parser.add_argument(
        '--dimensions',
        type=int,
        default=1536,
        help='Embedding dimensions (default: 1536)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for API calls (default: 100)'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate input file exists
    if not Path(args.input_file).exists():
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)
    
    # Validate API key
    if not os.getenv('OPENAI_API_KEY'):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("\nPlease set it:")
        print("  export OPENAI_API_KEY='your-api-key-here'")
        sys.exit(1)
    
    # Cost estimation
    print("="*80)
    print("OPENAI EMBEDDINGS - COST ESTIMATION")
    print("="*80)
    print(f"Input file: {args.input_file}")
    print(f"Model: {args.model}")
    print(f"Dimensions: {args.dimensions}")
    
    if args.model == 'text-embedding-3-small':
        print("Cost: $0.020 per 1M tokens")
        print("Estimated: ~$0.01-0.05 for typical documents")
    else:
        print("Cost: $0.130 per 1M tokens")
        print("Estimated: ~$0.05-0.20 for typical documents")
    
    print("="*80)
    
    # Confirm before proceeding
    response = input("\nProceed with embedding generation? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled.")
        sys.exit(0)
    
    # Create embedder and process
    embedder = OpenAIEmbedder(
        model=args.model,
        dimensions=args.dimensions,
        batch_size=args.batch_size
    )
    
    output_file = embedder.process(args.input_file)
    
    print("\n" + "="*80)
    print("SUCCESS!")
    print("="*80)
    print(f"Input:  {args.input_file}")
    print(f"Output: {output_file}")
    print("\nCheck the metadata section for actual cost incurred.")
    print("Embedding field added to each chunk!")
    print("="*80)


if __name__ == "__main__":
    main()
