"""
Pinecone Vector Ingestion
Ingest semantic memory chunks into Pinecone vector database
"""

import json
from pathlib import Path
from typing import List, Dict, Tuple
import logging
import os
import sys

from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PineconeIngestion:
    """Ingest semantic memory into Pinecone vector database"""

    def __init__(
        self,
        index_name: str = 'nl2sql-semantic-memory',
        data_path: str = './data/knowledge_base',
        dimension: int = 1536,
        cloud: str = 'aws',
        region: str = 'us-east-1'
    ):
        self.index_name = index_name
        self.data_path = Path(data_path)
        self.dimension = dimension
        self.cloud = cloud
        self.region = region

        # Initialize Pinecone
        api_key = os.getenv('PINECONE_API_KEY')
        if not api_key:
            raise ValueError("PINECONE_API_KEY environment variable not set")

        self.pc = Pinecone(api_key=api_key)
        logger.info("Initialized Pinecone client")

        # Initialize OpenAI embeddings
        self.embeddings = OpenAIEmbeddings(model='text-embedding-3-small')
        logger.info("Initialized OpenAI embeddings")

        # Create or connect to index
        self._setup_index()

    def _setup_index(self):
        """Create Pinecone index if it doesn't exist"""
        existing_indexes = [index.name for index in self.pc.list_indexes()]

        if self.index_name not in existing_indexes:
            logger.info(f"Creating new index: {self.index_name}")
            
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric='cosine',
                spec=ServerlessSpec(
                    cloud=self.cloud,
                    region=self.region
                )
            )
            logger.info(f"✓ Created index: {self.index_name}")
        else:
            logger.info(f"✓ Index already exists: {self.index_name}")

        # Connect to index
        self.index = self.pc.Index(self.index_name)
        logger.info(f"✓ Connected to index: {self.index_name}")

    def load_json_files(self) -> List[Path]:
        """Load all semantic JSON files"""
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

        # Determine memory type
        memory_type = 'procedural' if entity_type == 'query_example' else 'semantic'

        # Build metadata - Pinecone stores this separately
        metadata = {
            'table_name': table_name,
            'entity_type': entity_type,
            'memory_type': memory_type,
            'keywords': ','.join(chunk.get('keywords', [])),
            'text': text  # Store full text in metadata
        }

        # Add column name if present
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

                # Create Pinecone vector format
                vector = {
                    'id': chunk_id,
                    'values': embedding,
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

    def upload_vectors(self, vectors: List[Dict], batch_size: int = 100):
        """Upload vectors to Pinecone in batches"""
        if not vectors:
            logger.warning("No vectors to upload")
            return

        total_uploaded = 0
        
        logger.info(f"Uploading {len(vectors)} vectors in batches of {batch_size}...")

        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            batch_num = i // batch_size + 1

            try:
                # Upsert batch to Pinecone
                self.index.upsert(vectors=batch)
                total_uploaded += len(batch)
                logger.info(f"  ✓ Batch {batch_num}: Uploaded {len(batch)} vectors")

            except Exception as e:
                logger.error(f"  ✗ Batch {batch_num} failed: {e}")

        logger.info(f"Total uploaded: {total_uploaded}/{len(vectors)}")

    def ingest_all(self) -> Dict:
        """Main ingestion pipeline"""
        logger.info("="*70)
        logger.info("STARTING PINECONE INGESTION")
        logger.info("="*70)

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

        # Combine all vectors (Pinecone uses single index)
        all_vectors = all_semantic + all_procedural

        logger.info(f"\nTotal vectors: {len(all_semantic)} semantic, {len(all_procedural)} procedural")
        logger.info(f"Combined total: {len(all_vectors)} vectors")

        # Upload to Pinecone
        self.upload_vectors(all_vectors)

        # Get index stats
        stats = self.index.describe_index_stats()
        logger.info(f"\nIndex stats: {stats}")

        logger.info("\n" + "="*70)
        logger.info("INGESTION COMPLETE")
        logger.info("="*70)

        return {
            'semantic_count': len(all_semantic),
            'procedural_count': len(all_procedural),
            'total_count': len(all_vectors),
            'index_name': self.index_name
        }


def main():
    """Main entry point"""
    
    # Configuration
    INDEX_NAME = 'nl2sql-semantic-memory'
    DATA_PATH = '../data/knowledge_base'
    
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
    
    if not os.getenv('PINECONE_API_KEY'):
        print(f"✗ PINECONE_API_KEY not set")
        print(f"  Set it with: export PINECONE_API_KEY='your-key'")
        sys.exit(1)
    print(f"✓ PINECONE_API_KEY set")
    
    if not os.getenv('OPENAI_API_KEY'):
        print(f"✗ OPENAI_API_KEY not set")
        sys.exit(1)
    print(f"✓ OPENAI_API_KEY set")
    
    print("\nStarting ingestion...\n")
    
    # Run ingestion
    try:
        ingestion = PineconeIngestion(
            index_name=INDEX_NAME,
            data_path=DATA_PATH
        )
        
        results = ingestion.ingest_all()
        
        print("\n" + "="*70)
        print("RESULTS")
        print("="*70)
        print(f"Semantic vectors:   {results['semantic_count']}")
        print(f"Procedural vectors: {results['procedural_count']}")
        print(f"Total vectors:      {results['total_count']}")
        print(f"Index name:         {results['index_name']}")
        print("="*70)
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        logger.exception("Ingestion failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
