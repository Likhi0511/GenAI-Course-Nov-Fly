#!/usr/bin/env python3
"""
load_embeddings_to_pinecone.py

Loads embeddings from JSON file into Pinecone vector database.
Automatically detects dimensions and creates appropriate index.

Usage:
    python load_embeddings_to_pinecone.py <embedding_file.json> [options]

Examples:
    # Load with auto-detected dimensions
    python load_embeddings_to_pinecone.py large_chunks_sentence_transformers_embeddings.json

    # Specify custom index name
    python load_embeddings_to_pinecone.py file.json --index-name my-financial-docs

    # Use namespace for organization
    python load_embeddings_to_pinecone.py file.json --namespace earnings-reports

Requirements:
    pip install pinecone-client

Author: Prudhvi
Date: January 2025
"""

import json
from pinecone import Pinecone, ServerlessSpec
import sys
import argparse
from pathlib import Path
import time
from datetime import datetime
import os


class PineconeLoader:
    """Load embeddings into Pinecone vector database."""
    
    def __init__(self, api_key):
        """
        Initialize loader.
        
        Args:
            api_key: Pinecone API key
        """
        self.api_key = api_key
        self.pc = None
        self.index = None
        
    def initialize(self):
        """Initialize Pinecone client."""
        print(f"\n{'='*70}")
        print("INITIALIZING PINECONE")
        print(f"{'='*70}")
        
        try:
            self.pc = Pinecone(api_key=self.api_key)
            print("✓ Pinecone client initialized")
            return True
        except Exception as e:
            print(f"✗ Initialization failed: {str(e)}")
            return False
    
    def load_json_file(self, json_file, override_dimensions=None):
        """
        Load and validate JSON file.
        
        Args:
            json_file: Path to JSON file with embeddings
            override_dimensions: Optional dimensions override
            
        Returns:
            Dictionary with chunks and metadata, or None if failed
        """
        print(f"\n{'='*70}")
        print("LOADING JSON FILE")
        print(f"{'='*70}")
        print(f"File: {json_file}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate structure
            if 'chunks' not in data:
                print("✗ Error: JSON file must have 'chunks' key")
                return None
            
            chunks = data['chunks']
            
            if len(chunks) == 0:
                print("✗ Error: No chunks found in JSON file")
                return None
            
            # Check for embedding field
            first_chunk = chunks[0]
            if 'embedding' not in first_chunk:
                print("✗ Error: Chunks must have 'embedding' field")
                return None
            
            # Determine dimensions
            if override_dimensions:
                dimensions = override_dimensions
                print(f"✓ Using specified dimensions: {dimensions}")
                print(f"✓ Loaded {len(chunks)} chunks")
            else:
                dimensions = len(first_chunk['embedding'])
                print(f"✓ Loaded {len(chunks)} chunks")
                print(f"✓ Auto-detected {dimensions} dimensions")
            
            return {
                'chunks': chunks,
                'dimensions': dimensions,
                'metadata': data.get('metadata', {})
            }
            
        except FileNotFoundError:
            print(f"✗ Error: File not found: {json_file}")
            return None
        except json.JSONDecodeError as e:
            print(f"✗ Error: Invalid JSON: {str(e)}")
            return None
        except Exception as e:
            print(f"✗ Error loading file: {str(e)}")
            return None
    
    def create_or_get_index(self, index_name, dimensions, metric='cosine', cloud='aws', region='us-east-1'):
        """
        Create index or get existing one.
        
        Args:
            index_name: Name of index to create
            dimensions: Number of dimensions
            metric: Distance metric (cosine, euclidean, dotproduct)
            cloud: Cloud provider (aws, gcp, azure)
            region: Cloud region
        """
        print(f"\n{'='*70}")
        print("INDEX SETUP")
        print(f"{'='*70}")
        print(f"Index name: {index_name}")
        print(f"Dimensions: {dimensions}")
        print(f"Metric: {metric}")
        print(f"Cloud: {cloud}")
        print(f"Region: {region}")
        
        try:
            # Check if index already exists
            existing_indexes = self.pc.list_indexes()
            index_names = [idx['name'] for idx in existing_indexes]
            
            if index_name in index_names:
                print(f"\n⚠ Index '{index_name}' already exists")
                
                # Get existing index info
                index_info = self.pc.describe_index(index_name)
                existing_dims = index_info['dimension']
                
                if existing_dims != dimensions:
                    print(f"✗ Error: Existing index has {existing_dims} dimensions, need {dimensions}")
                    print(f"Options:")
                    print(f"  1. Use different index name: --index-name my-new-index")
                    print(f"  2. Delete existing index in Pinecone console")
                    return False
                
                print(f"✓ Using existing index")
                self.index = self.pc.Index(index_name)
                
                # Get stats
                stats = self.index.describe_index_stats()
                print(f"✓ Current vectors: {stats['total_vector_count']}")
                
            else:
                print(f"\nCreating new index...")
                
                self.pc.create_index(
                    name=index_name,
                    dimension=dimensions,
                    metric=metric,
                    spec=ServerlessSpec(
                        cloud=cloud,
                        region=region
                    )
                )
                
                print(f"✓ Index '{index_name}' created")
                print(f"⏳ Waiting for index to be ready...")
                
                # Wait for index to be ready
                while not self.pc.describe_index(index_name).get('status', {}).get('ready', False):
                    time.sleep(1)
                
                print(f"✓ Index is ready!")
                
                self.index = self.pc.Index(index_name)
            
            return True
            
        except Exception as e:
            print(f"✗ Failed to create/get index: {str(e)}")
            return False
    
    def prepare_vectors(self, chunks, namespace=None):
        """
        Prepare vectors for Pinecone format.
        
        Args:
            chunks: List of chunk dictionaries
            namespace: Optional namespace
            
        Returns:
            List of vectors in Pinecone format
        """
        print(f"\n{'='*70}")
        print("PREPARING VECTORS")
        print(f"{'='*70}")
        print(f"Total chunks: {len(chunks)}")
        if namespace:
            print(f"Namespace: {namespace}")
        
        vectors = []
        
        for chunk in chunks:
            # Get ID
            vector_id = chunk.get('id', chunk.get('chunk_id', ''))
            if not vector_id:
                print(f"⚠ Warning: Chunk missing ID, skipping")
                continue
            
            # Get embedding
            embedding = chunk.get('embedding')
            if not embedding:
                print(f"⚠ Warning: Chunk {vector_id} missing embedding, skipping")
                continue
            
            # Prepare metadata (Pinecone has size limits, so be selective)
            metadata = {}
            
            # Add text content (truncate if too long)
            text = chunk.get('content_only', chunk.get('text', ''))
            if text:
                # Pinecone metadata limit is 40KB, keep text under 10KB to be safe
                metadata['text'] = text[:10000] if len(text) > 10000 else text
            
            # Add select metadata fields
            if 'metadata' in chunk and isinstance(chunk['metadata'], dict):
                chunk_meta = chunk['metadata']
                
                # Add common fields
                if 'source' in chunk_meta:
                    metadata['source'] = str(chunk_meta['source'])
                if 'page_number' in chunk_meta:
                    metadata['page'] = int(chunk_meta['page_number'])
                if 'type' in chunk_meta:
                    metadata['type'] = str(chunk_meta['type'])
                
                # Add key phrases (first 10)
                if 'key_phrases' in chunk_meta:
                    phrases = chunk_meta['key_phrases'][:10]
                    metadata['key_phrases'] = ','.join(phrases)
                
                # Add years
                if 'years' in chunk_meta:
                    years = chunk_meta['years'][:5]
                    for i, year in enumerate(years):
                        metadata[f'year_{i+1}'] = str(year)
                
                # Add quality metrics
                if 'quality_metrics' in chunk_meta:
                    qm = chunk_meta['quality_metrics']
                    if 'word_count' in qm:
                        metadata['word_count'] = int(qm['word_count'])
            
            vector = {
                "id": vector_id,
                "values": embedding,
                "metadata": metadata
            }
            
            vectors.append(vector)
        
        print(f"✓ Prepared {len(vectors)} vectors")
        return vectors
    
    def upload_vectors(self, vectors, namespace=None, batch_size=100):
        """
        Upload vectors to Pinecone.
        
        Args:
            vectors: List of vector dictionaries
            namespace: Optional namespace
            batch_size: Number of vectors per batch
        """
        print(f"\n{'='*70}")
        print("UPLOADING VECTORS")
        print(f"{'='*70}")
        print(f"Total vectors: {len(vectors)}")
        print(f"Batch size: {batch_size}")
        if namespace:
            print(f"Namespace: {namespace}")
        
        try:
            total_uploaded = 0
            start_time = time.time()
            
            # Upload in batches
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i+batch_size]
                
                self.index.upsert(
                    vectors=batch,
                    namespace=namespace or ""
                )
                
                total_uploaded += len(batch)
                elapsed = time.time() - start_time
                rate = total_uploaded / elapsed if elapsed > 0 else 0
                
                print(f"  Uploaded {total_uploaded}/{len(vectors)} vectors ({rate:.1f} vectors/sec)")
            
            total_time = time.time() - start_time
            print(f"\n✓ All vectors uploaded!")
            print(f"  Total time: {total_time:.2f} seconds")
            print(f"  Average rate: {len(vectors)/total_time:.1f} vectors/second")
            
            return True
            
        except Exception as e:
            print(f"\n✗ Failed to upload vectors: {str(e)}")
            return False
    
    def verify_upload(self, expected_count, namespace=None):
        """
        Verify vectors were uploaded correctly.
        
        Args:
            expected_count: Expected number of vectors
            namespace: Optional namespace
        """
        print(f"\n{'='*70}")
        print("VERIFYING UPLOAD")
        print(f"{'='*70}")
        
        try:
            # Get index stats
            stats = self.index.describe_index_stats()
            
            if namespace:
                ns_stats = stats.get('namespaces', {}).get(namespace, {})
                actual_count = ns_stats.get('vector_count', 0)
                print(f"Namespace: {namespace}")
            else:
                actual_count = stats['total_vector_count']
            
            print(f"Expected vectors: {expected_count}")
            print(f"Actual vectors: {actual_count}")
            
            if actual_count == expected_count:
                print(f"✓ Upload verified!")
            else:
                print(f"⚠ Warning: Count mismatch ({actual_count} vs {expected_count})")
                print(f"  This might be temporary - Pinecone updates stats asynchronously")
            
            print(f"\nIndex statistics:")
            print(f"  Total vectors: {stats['total_vector_count']}")
            print(f"  Dimension: {stats['dimension']}")
            
            if 'namespaces' in stats:
                print(f"  Namespaces:")
                for ns, ns_data in stats['namespaces'].items():
                    print(f"    - {ns}: {ns_data.get('vector_count', 0)} vectors")
            
            return True
            
        except Exception as e:
            print(f"✗ Verification failed: {str(e)}")
            return False


def main():
    """Main function."""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Load embeddings into Pinecone vector database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s large_chunks_openai_embeddings.json
  %(prog)s file.json --index-name my-docs --dimensions 1536
  %(prog)s file.json --namespace earnings --api-key pc-xxx
  %(prog)s file.json --cloud gcp --region us-central1
        """
    )

    # /Users/akellaprudhvi/mystuff/Course/GenAI-Course-Modules/Module_4/1_extraction/1_llama_parse/extracted_docs_ultimate/AI-Enablers-Adopters-research-report/large_chunks_production_enriched_metadata_sentence_transformers_embeddings.json --dimensions 384

    parser.add_argument('json_file', help='Path to JSON file with embeddings')
    parser.add_argument('--api-key', help='Pinecone API key (or use PINECONE_API_KEY env var)')
    parser.add_argument('--index-name', default='embeddings-index', help='Index name (default: embeddings-index)')
    parser.add_argument('--dimensions', type=int, help='Vector dimensions (auto-detected if not specified)')
    parser.add_argument('--namespace', help='Namespace for vectors (optional)')
    parser.add_argument('--metric', default='cosine', choices=['cosine', 'euclidean', 'dotproduct'],
                        help='Distance metric (default: cosine)')
    parser.add_argument('--cloud', default='aws', choices=['aws', 'gcp', 'azure'],
                        help='Cloud provider (default: aws)')
    parser.add_argument('--region', default='us-east-1', help='Cloud region (default: us-east-1)')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for uploads (default: 100)')
    
    args = parser.parse_args()
    
    # Validate file exists
    if not Path(args.json_file).exists():
        print(f"Error: File not found: {args.json_file}")
        sys.exit(1)
    
    # Get API key
    api_key = args.api_key or os.getenv('PINECONE_API_KEY')
    if not api_key:
        print("Error: Pinecone API key required!")
        print("Either:")
        print("  1. Set PINECONE_API_KEY environment variable")
        print("  2. Use --api-key parameter")
        print("\nGet your API key from: https://app.pinecone.io/")
        sys.exit(1)
    
    # Print header
    print(f"\n{'#'*70}")
    print(f"# LOAD EMBEDDINGS TO PINECONE")
    print(f"{'#'*70}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Input file: {args.json_file}")
    print(f"Index name: {args.index_name}")
    print(f"Namespace: {args.namespace or 'default'}")
    print(f"Metric: {args.metric}")
    
    # Initialize loader
    loader = PineconeLoader(api_key)
    
    try:
        # Step 1: Initialize Pinecone
        if not loader.initialize():
            sys.exit(1)
        
        # Step 2: Load JSON file
        data = loader.load_json_file(args.json_file, args.dimensions)
        if not data:
            sys.exit(1)
        
        # Step 3: Create or get index
        if not loader.create_or_get_index(
            index_name=args.index_name,
            dimensions=data['dimensions'],
            metric=args.metric,
            cloud=args.cloud,
            region=args.region
        ):
            sys.exit(1)
        
        # Step 4: Prepare vectors
        vectors = loader.prepare_vectors(data['chunks'], args.namespace)
        if not vectors:
            print("✗ No vectors prepared")
            sys.exit(1)
        
        # Step 5: Upload vectors
        if not loader.upload_vectors(vectors, args.namespace, args.batch_size):
            sys.exit(1)
        
        # Step 6: Verify
        if not loader.verify_upload(len(vectors), args.namespace):
            sys.exit(1)
        
        # Success!
        print(f"\n{'#'*70}")
        print(f"# SUCCESS!")
        print(f"{'#'*70}")
        print(f"✓ Loaded {len(vectors)} vectors into Pinecone")
        print(f"✓ Index: {args.index_name}")
        print(f"✓ Namespace: {args.namespace or 'default'}")
        print(f"✓ Dimensions: {data['dimensions']}")
        print(f"✓ Metric: {args.metric}")
        print(f"\nYou can now search your embeddings!")
        print(f"\nPinecone Console: https://app.pinecone.io/")
        print(f"{'#'*70}\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
