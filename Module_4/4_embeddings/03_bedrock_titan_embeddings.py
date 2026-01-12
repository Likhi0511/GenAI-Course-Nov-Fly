"""
================================================================================
AWS BEDROCK TITAN EMBEDDINGS GENERATOR
================================================================================

Purpose: Generate embeddings using AWS Bedrock Titan Embeddings (managed, enterprise)

Author: Prudhvi
Created: January 2025

Features:
- Managed AWS service
- 1024 dimensions
- Multi-language support
- Low cost ($0.0001 per 1K tokens)
- Enterprise-ready
- Automatic retry logic
- In-place modification (adds 'embedding' field to existing chunks)

Model: amazon.titan-embed-text-v2:0
- Dimensions: 1024
- Cost: $0.0001 per 1K tokens
- Quality: Good
- Languages: 100+ languages

Usage:
    python 03_bedrock_titan_embeddings.py <input_file> [--region REGION] [--dimensions DIM]
    
Example:
    python 03_bedrock_titan_embeddings.py data/chunks.json
    python 03_bedrock_titan_embeddings.py data/chunks.json --region us-west-2 --dimensions 512
    
Output:
    data/chunks_bedrock_titan_embeddings.json
================================================================================
"""

import json
import boto3
import sys
import argparse
from datetime import datetime
import logging
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm
import time
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BedrockTitanEmbedder:
    """
    Generate embeddings using AWS Bedrock Titan Embeddings.
    
    This class handles:
    - AWS Bedrock client initialization
    - Batch processing (one at a time due to API constraints)
    - Automatic retries on failures
    - Cost tracking
    - Progress monitoring
    """
    
    def __init__(
        self, 
        model_id: str = 'amazon.titan-embed-text-v2:0',
        region_name: str = 'us-east-1',
        dimensions: int = 1024
    ):
        """
        Initialize the embedder.
        
        Args:
            model_id: Bedrock model ID
            region_name: AWS region
            dimensions: Embedding dimensions (256, 512, or 1024)
        """
        self.model_id = model_id
        self.region_name = region_name
        self.dimensions = dimensions
        self.client = None
        self.total_tokens = 0
        
        logger.info(f"Initializing BedrockTitanEmbedder")
        logger.info(f"Model: {model_id}")
        logger.info(f"Region: {region_name}")
        logger.info(f"Dimensions: {dimensions}")
    
    def initialize_client(self):
        """
        Initialize AWS Bedrock runtime client.
        
        Requires AWS credentials configured via:
        - AWS CLI: aws configure
        - Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
        - IAM role (if running on AWS)
        """
        try:
            self.client = boto3.client(
                service_name='bedrock-runtime',
                region_name=self.region_name
            )
            logger.info("AWS Bedrock client initialized successfully")
            
        except Exception as e:
            raise ValueError(
                f"Failed to initialize AWS Bedrock client: {str(e)}\n"
                "Please ensure AWS credentials are configured:\n"
                "  - Run 'aws configure' to set credentials\n"
                "  - Or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env variables\n"
                "  - Ensure IAM user has bedrock:InvokeModel permission"
            )
    
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
    def get_embedding(self, text: str) -> List[float]:
        """
        Get embedding for a single text with retry logic.
        
        Args:
            text: Text string to embed
            
        Returns:
            Embedding vector
        """
        # Prepare request body
        request_body = {
            "inputText": text,
            "dimensions": self.dimensions,
            "normalize": True  # L2 normalization for cosine similarity
        }
        
        try:
            # Invoke Bedrock model
            response = self.client.invoke_model(
                modelId=self.model_id,
                contentType='application/json',
                accept='application/json',
                body=json.dumps(request_body)
            )
            
            # Parse response
            response_body = json.loads(response['body'].read())
            embedding = response_body['embedding']
            
            # Track tokens (estimate based on text length)
            # Bedrock doesn't return token count, so we estimate
            estimated_tokens = len(text.split())
            self.total_tokens += estimated_tokens
            
            return embedding
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Bedrock API error: {error_code} - {error_message}")
            raise
    
    def generate_embeddings(self, chunks: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for all chunks.
        
        Note: Bedrock Titan processes one text at a time (no batching).
        
        Args:
            chunks: List of chunk dictionaries
            
        Returns:
            List of chunks with embeddings added
        """
        logger.info("Generating embeddings...")
        logger.info(f"Processing {len(chunks)} chunks (one at a time)")
        
        enriched_chunks = []
        
        # Process each chunk with progress bar
        for chunk in tqdm(chunks, desc="Embedding chunks"):
            text = chunk['content_only']
            
            try:
                # Get embedding
                embedding = self.get_embedding(text)
                
                # Add embedding to chunk
                enriched_chunk = chunk.copy()
                enriched_chunk['embedding'] = embedding
                enriched_chunk['embedding_metadata'] = {
                    'model': self.model_id,
                    'dimensions': self.dimensions,
                    'normalized': True,
                    'generated_at': datetime.now().isoformat()
                }
                enriched_chunks.append(enriched_chunk)
                
                # Small delay to respect rate limits
                time.sleep(0.05)
                
            except Exception as e:
                logger.error(f"Error processing chunk {chunk.get('id', 'unknown')}: {str(e)}")
                raise
        
        logger.info(f"Generated {len(enriched_chunks)} embeddings")
        logger.info(f"Estimated total tokens: {self.total_tokens:,}")
        
        return enriched_chunks
    
    def calculate_cost(self) -> Dict[str, float]:
        """
        Calculate estimated API cost based on tokens.
        
        Note: This is an estimate as Bedrock doesn't return exact token counts.
        
        Returns:
            Dictionary with cost breakdown
        """
        # Pricing: $0.0001 per 1K tokens (as of Jan 2025)
        price_per_1k_tokens = 0.0001
        cost = (self.total_tokens / 1000) * price_per_1k_tokens
        
        return {
            'estimated_tokens': self.total_tokens,
            'price_per_1k_tokens': price_per_1k_tokens,
            'estimated_cost_usd': round(cost, 6)
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
        output_file = input_path.parent / f"{input_path.stem}_bedrock_titan_embeddings{input_path.suffix}"
        
        logger.info(f"Saving results to: {output_file}")
        
        cost_info = self.calculate_cost()
        
        output_data = {
            'metadata': {
                'model': self.model_id,
                'dimensions': self.dimensions,
                'total_chunks': len(chunks),
                'generated_at': datetime.now().isoformat(),
                'embedding_config': {
                    'region': self.region_name,
                    'normalized': True,
                    'model_type': 'bedrock-titan'
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
        logger.info("STARTING BEDROCK TITAN EMBEDDING GENERATION")
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
        logger.info(f"Estimated tokens: {cost_info['estimated_tokens']:,}")
        logger.info(f"Estimated cost: ${cost_info['estimated_cost_usd']:.6f} USD")
        logger.info(f"Output file: {output_file}")
        logger.info("="*80)
        
        return output_file


def main():
    """Main execution function."""
    
    # Setup argument parser
    parser = argparse.ArgumentParser(
        description='Generate embeddings using AWS Bedrock Titan Embeddings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python 03_bedrock_titan_embeddings.py data/chunks.json
  python 03_bedrock_titan_embeddings.py data/chunks.json --region us-west-2
  python 03_bedrock_titan_embeddings.py data/chunks.json --dimensions 512
  
Output:
  Input:  data/chunks.json
  Output: data/chunks_bedrock_titan_embeddings.json
  
Cost:
  $0.0001 per 1K tokens (very cheap!)
  Typical: ~$0.001-0.005 for 50 chunks
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
        default='amazon.titan-embed-text-v2:0',
        help='Bedrock model ID (default: amazon.titan-embed-text-v2:0)'
    )
    
    parser.add_argument(
        '--region',
        type=str,
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    
    parser.add_argument(
        '--dimensions',
        type=int,
        default=1024,
        choices=[256, 512, 1024],
        help='Embedding dimensions: 256, 512, or 1024 (default: 1024)'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate input file exists
    if not Path(args.input_file).exists():
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)
    
    # Check AWS credentials
    print("Checking AWS credentials...")
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        if not credentials:
            print("Error: AWS credentials not found")
            print("\nPlease configure AWS credentials:")
            print("  1. Run: aws configure")
            print("  2. Or set environment variables:")
            print("     export AWS_ACCESS_KEY_ID='your-key'")
            print("     export AWS_SECRET_ACCESS_KEY='your-secret'")
            sys.exit(1)
        print("✓ AWS credentials found\n")
    except Exception as e:
        print(f"Error checking credentials: {str(e)}")
        sys.exit(1)
    
    # Cost estimation
    print("="*80)
    print("AWS BEDROCK TITAN EMBEDDINGS - CONFIGURATION")
    print("="*80)
    print(f"Input file: {args.input_file}")
    print(f"Model: {args.model}")
    print(f"Region: {args.region}")
    print(f"Dimensions: {args.dimensions}")
    print("Cost: $0.0001 per 1K tokens")
    print("Estimated: ~$0.001-0.005 (very cheap!)")
    print("="*80)
    print()
    
    # Create embedder and process
    embedder = BedrockTitanEmbedder(
        model_id=args.model,
        region_name=args.region,
        dimensions=args.dimensions
    )
    
    output_file = embedder.process(args.input_file)
    
    print("\n" + "="*80)
    print("SUCCESS!")
    print("="*80)
    print(f"Input:  {args.input_file}")
    print(f"Output: {output_file}")
    print("\nBedrock Titan advantages:")
    print("  - Very low cost ($0.0001 per 1K tokens)")
    print("  - Multi-language support (100+ languages)")
    print("  - Managed service (no model downloads)")
    print("  - Enterprise-ready (AWS infrastructure)")
    print("\nEmbedding field added to each chunk!")
    print("="*80)


if __name__ == "__main__":
    main()
