"""
S3 Vectors Ingestion - Corrected API Version
=============================================
Uses correct boto3 S3 Vectors API based on official documentation
"""

import json
import boto3
from pathlib import Path
from typing import List, Dict, Tuple
import logging
import os
import sys

from langchain_openai import OpenAIEmbeddings
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class S3VectorIngestion:
    """Ingest semantic memory into S3 vector buckets using correct boto3 API"""

    def __init__(
        self,
        semantic_bucket: str,
        procedural_bucket: str,
        data_path: str = './data/knowledge_base',
        aws_region: str = 'us-east-1'
    ):
        self.semantic_bucket = semantic_bucket
        self.procedural_bucket = procedural_bucket
        self.data_path = Path(data_path)
        self.aws_region = aws_region

        # Initialize S3 Vectors client
        self.s3vectors = boto3.client('s3vectors', region_name=aws_region)
        logger.info(f"Initialized S3 Vectors client in {aws_region}")

        # Initialize OpenAI embeddings
        self.embeddings = OpenAIEmbeddings(model='text-embedding-3-small')
        logger.info("Initialized OpenAI embeddings")

    def create_buckets(self):
        """Create S3 vector buckets"""
        logger.info("Creating vector buckets...")

        for bucket in [self.semantic_bucket, self.procedural_bucket]:
            try:
                # Check if bucket exists using list_vector_buckets
                response = self.s3vectors.list_vector_buckets()
                existing_buckets = [b['vectorBucketName'] for b in response.get('vectorBuckets', [])]

                if bucket in existing_buckets:
                    logger.info(f"✓ Bucket exists: {bucket}")
                else:
                    # Create bucket with correct parameters from documentation
                    self.s3vectors.create_vector_bucket(
                        vectorBucketName=bucket,
                        encryptionConfiguration={
                            'sseType': 'AES256'  # SSE-S3 encryption
                        }
                    )
                    logger.info(f"✓ Created bucket: {bucket}")

            except ClientError as e:
                logger.error(f"✗ Bucket operation failed for {bucket}: {e}")
            except Exception as e:
                logger.error(f"✗ Unexpected error with bucket {bucket}: {e}")

    def create_indexes(self):
        """Create vector indexes with correct parameters"""
        logger.info("Creating vector indexes...")

        # Index names must be lowercase, 3-63 chars, use only letters, numbers, dots, hyphens
        indexes = [
            (self.semantic_bucket, 'semantic-index'),  # Use hyphen instead of underscore
            (self.procedural_bucket, 'procedural-index')  # Use hyphen instead of underscore
        ]

        self.semantic_index = 'semantic-index'
        self.procedural_index = 'procedural-index'

        for bucket, index_name in indexes:
            try:
                # Check if index exists using list_indexes
                response = self.s3vectors.list_indexes(vectorBucketName=bucket)
                existing_indexes = [idx['indexName'] for idx in response.get('indexes', [])]

                if index_name in existing_indexes:
                    logger.info(f"✓ Index exists: {bucket}/{index_name}")
                else:
                    # Create index with correct parameters from documentation
                    self.s3vectors.create_index(
                        vectorBucketName=bucket,
                        indexName=index_name,
                        dataType='float32',  # Required parameter
                        dimension=1536,  # OpenAI text-embedding-3-small dimension
                        distanceMetric='cosine'  # Required parameter
                    )
                    logger.info(f"✓ Created index: {bucket}/{index_name}")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_msg = e.response['Error']['Message']
                logger.error(f"✗ Index creation failed for {bucket}/{index_name}")
                logger.error(f"  Error code: {error_code}")
                logger.error(f"  Error message: {error_msg}")

                # Critical error - cannot continue without indexes
                raise Exception(f"Failed to create index {index_name}: {error_msg}")

            except Exception as e:
                logger.error(f"✗ Unexpected error with index {bucket}/{index_name}: {e}")
                raise

    def load_json_files(self) -> List[Path]:
        """Load semantic JSON files"""
        # Try both patterns - with and without '_enhanced'
        files = list(self.data_path.glob('semantic_*.json'))

        if files:
            logger.info(f"Found {len(files)} semantic JSON files:")
            for f in files:
                logger.info(f"  - {f.name}")
        else:
            logger.warning(f"No semantic JSON files found in {self.data_path}")

        return files

    def parse_chunk(self, chunk: Dict, table_name: str) -> Tuple[str, str, Dict, str]:
        """Parse chunk and extract components"""
        chunk_id = chunk.get('chunk_id', 'unknown')
        entity_type = chunk.get('entity_type', 'unknown')
        text = chunk.get('text', '')

        memory_type = 'procedural' if entity_type == 'query_example' else 'semantic'

        # IMPORTANT: Store all important fields in metadata since S3 Vectors
        # only returns metadata, not the original text
        metadata = {
            'table_name': table_name,
            'entity_type': entity_type,
            'keywords': ','.join(chunk.get('keywords', [])),
            'text': text  # ADD THE FULL TEXT HERE
        }

        if 'column_name' in chunk:
            metadata['column_name'] = chunk['column_name']

        return chunk_id, text, metadata, memory_type

    def process_file(self, json_file: Path) -> Tuple[List[Dict], List[Dict]]:
        """Process JSON file and generate vectors"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"Processing: {json_file.name}")
        except Exception as e:
            logger.error(f"Failed to load {json_file.name}: {e}")
            return [], []

        table_name = data.get('table', 'unknown')
        chunks = data.get('chunks', [])

        semantic_vectors = []
        procedural_vectors = []

        for chunk in chunks:
            try:
                chunk_id, text, metadata, memory_type = self.parse_chunk(chunk, table_name)

                if not text:
                    continue

                # Generate embedding
                embedding = self.embeddings.embed_query(text)

                # Create vector with correct structure for put_vectors
                vector = {
                    'key': chunk_id,
                    'data': {'float32': embedding},
                    'metadata': metadata
                }

                if memory_type == 'semantic':
                    semantic_vectors.append(vector)
                else:
                    procedural_vectors.append(vector)

            except Exception as e:
                logger.error(f"Error processing chunk: {e}")
                continue

        logger.info(f"  {table_name}: {len(semantic_vectors)} semantic, {len(procedural_vectors)} procedural")
        return semantic_vectors, procedural_vectors

    def upload_vectors(self, vectors: List[Dict], bucket: str, index_name: str):
        """Upload vectors using put_vectors API"""
        if not vectors:
            logger.warning(f"No vectors to upload to {bucket}/{index_name}")
            return

        batch_size = 100
        total_uploaded = 0

        logger.info(f"Uploading {len(vectors)} vectors to {bucket}/{index_name}...")

        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            batch_num = i // batch_size + 1

            try:
                # Use put_vectors with correct parameters
                self.s3vectors.put_vectors(
                    vectorBucketName=bucket,
                    indexName=index_name,
                    vectors=batch
                )
                total_uploaded += len(batch)
                logger.info(f"  ✓ Batch {batch_num}: {len(batch)} vectors uploaded")

            except ClientError as e:
                logger.error(f"  ✗ Batch {batch_num} failed: {e}")
            except Exception as e:
                logger.error(f"  ✗ Batch {batch_num} error: {e}")

        logger.info(f"Total uploaded: {total_uploaded}/{len(vectors)}")

    def ingest_all(self) -> Dict:
        """Main ingestion pipeline"""
        logger.info("="*70)
        logger.info("STARTING S3 VECTORS INGESTION")
        logger.info("="*70)

        # Create buckets and indexes (will raise exception on failure)
        try:
            self.create_buckets()
            self.create_indexes()
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            return {
                'semantic_count': 0,
                'procedural_count': 0,
                'error': f'Setup failed: {e}'
            }

        # Load and process files
        json_files = self.load_json_files()

        if not json_files:
            logger.error(f"No files found in {self.data_path}")
            return {
                'semantic_count': 0,
                'procedural_count': 0,
                'error': 'No input files'
            }

        all_semantic = []
        all_procedural = []

        for json_file in json_files:
            semantic, procedural = self.process_file(json_file)
            all_semantic.extend(semantic)
            all_procedural.extend(procedural)

        logger.info(f"\nTotal vectors: {len(all_semantic)} semantic, {len(all_procedural)} procedural")

        # Upload vectors using the correct index names
        self.upload_vectors(all_semantic, self.semantic_bucket, self.semantic_index)
        self.upload_vectors(all_procedural, self.procedural_bucket, self.procedural_index)

        logger.info("\n" + "="*70)
        logger.info("INGESTION COMPLETE")
        logger.info("="*70)

        return {
            'semantic_count': len(all_semantic),
            'procedural_count': len(all_procedural),
            'semantic_bucket': self.semantic_bucket,
            'procedural_bucket': self.procedural_bucket
        }


def main():
    """Main entry point"""

    # Configuration
    SEMANTIC_BUCKET = 'nl2sql-semantic-memory'
    PROCEDURAL_BUCKET = 'nl2sql-procedural-memory'
    DATA_PATH = '/Users/akellaprudhvi/PycharmProjects/Generative_AI_Course_Bundle/project-1/data/knowledge_base'
    AWS_REGION = 'us-east-1'

    # Pre-flight checks
    print("\nPre-flight checks...")

    if not os.path.exists(DATA_PATH):
        print(f"✗ Data path not found: {DATA_PATH}")
        sys.exit(1)
    print(f"✓ Data path exists")

    files = list(Path(DATA_PATH).glob('semantic_*.json'))
    if not files:
        print(f"✗ No semantic JSON files found")
        sys.exit(1)
    print(f"✓ Found {len(files)} files")

    try:
        boto3.client('sts').get_caller_identity()
        print(f"✓ AWS credentials configured")
    except Exception as e:
        print(f"✗ AWS credentials error: {e}")
        sys.exit(1)

    if not os.getenv('OPENAI_API_KEY'):
        print(f"✗ OPENAI_API_KEY not set")
        sys.exit(1)
    print(f"✓ OPENAI_API_KEY set")

    print("\nStarting ingestion...\n")

    # Run ingestion
    try:
        ingestion = S3VectorIngestion(
            semantic_bucket=SEMANTIC_BUCKET,
            procedural_bucket=PROCEDURAL_BUCKET,
            data_path=DATA_PATH,
            aws_region=AWS_REGION
        )

        results = ingestion.ingest_all()

        # Check for errors
        if results.get('error'):
            print("\n" + "="*70)
            print("INGESTION FAILED")
            print("="*70)
            print(f"Error: {results['error']}")
            print("="*70)
            sys.exit(1)

        print("\n" + "="*70)
        print("RESULTS")
        print("="*70)
        print(f"Semantic vectors:   {results['semantic_count']}")
        print(f"Procedural vectors: {results['procedural_count']}")
        print(f"Semantic bucket:    {results['semantic_bucket']}")
        print(f"Procedural bucket:  {results['procedural_bucket']}")
        print("="*70)

        if results['semantic_count'] == 0 and results['procedural_count'] == 0:
            print("\n⚠ WARNING: No vectors were uploaded!")
            sys.exit(1)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        logger.exception("Ingestion failed")
        sys.exit(1)


if __name__ == "__main__":
    main()