"""
Pinecone Vector Retrieval
Query vectors from Pinecone index
"""

import os
from typing import List, Dict
import logging

from pinecone import Pinecone
from langchain_openai import OpenAIEmbeddings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PineconeRetriever:
    """Retrieve vectors from Pinecone index"""

    def __init__(
        self,
        index_name: str = 'nl2sql-semantic-memory'
    ):
        self.index_name = index_name

        # Initialize Pinecone
        api_key = os.getenv('PINECONE_API_KEY')
        if not api_key:
            raise ValueError("PINECONE_API_KEY environment variable not set")

        self.pc = Pinecone(api_key=api_key)
        self.index = self.pc.Index(index_name)
        
        # Initialize embeddings
        self.embeddings = OpenAIEmbeddings(model='text-embedding-3-small')
        
        logger.info(f"Initialized PineconeRetriever")
        logger.info(f"  Index: {index_name}")

    def search_semantic(self, query: str, top_k: int = 8) -> List[Dict]:
        """Search semantic memory (tables, columns, relationships)"""
        query_embedding = self.embeddings.embed_query(query)

        try:
            # Query with filter for semantic memory
            response = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                filter={'memory_type': 'semantic'},
                include_metadata=True
            )
            
            vectors = response.get('matches', [])
            logger.info(f"Found {len(vectors)} semantic results")
            
            # Debug: check if text is in metadata
            if vectors:
                sample = vectors[0]
                if 'metadata' in sample and 'text' in sample['metadata']:
                    text_len = len(sample['metadata']['text'])
                    logger.info(f"✓ Text found in metadata (length: {text_len} chars)")
                else:
                    logger.warning(f"✗ Text NOT found in metadata")
            
            # Convert Pinecone format to our standard format
            results = []
            for match in vectors:
                results.append({
                    'id': match.get('id'),
                    'score': match.get('score'),  # Pinecone returns score (0-1, higher is better)
                    'metadata': match.get('metadata', {})
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            logger.exception("Full error:")
            return []

    def search_procedural(self, query: str, top_k: int = 3) -> List[Dict]:
        """Search procedural memory (query examples)"""
        query_embedding = self.embeddings.embed_query(query)

        try:
            # Query with filter for procedural memory
            response = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                filter={'memory_type': 'procedural'},
                include_metadata=True
            )
            
            vectors = response.get('matches', [])
            logger.info(f"Found {len(vectors)} procedural results")
            
            # Debug: check for text in metadata
            if vectors:
                sample = vectors[0]
                if 'metadata' in sample and 'text' in sample['metadata']:
                    text_len = len(sample['metadata']['text'])
                    logger.info(f"✓ Text found in metadata (length: {text_len} chars)")
                else:
                    logger.warning(f"✗ Text NOT found in metadata")
            
            # Convert Pinecone format to our standard format
            results = []
            for match in vectors:
                results.append({
                    'id': match.get('id'),
                    'score': match.get('score'),
                    'metadata': match.get('metadata', {})
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Procedural search failed: {e}")
            logger.exception("Full error:")
            return []

    def search_both(self, query: str, semantic_k: int = 8, procedural_k: int = 3) -> Dict:
        """Search both memory types"""
        logger.info(f"Searching for: '{query}'")
        logger.info(f"  Semantic top-k: {semantic_k}")
        logger.info(f"  Procedural top-k: {procedural_k}")
        
        results = {
            'semantic': self.search_semantic(query, semantic_k),
            'procedural': self.search_procedural(query, procedural_k)
        }
        
        logger.info(f"Total retrieved: {len(results['semantic'])} semantic + {len(results['procedural'])} procedural")
        
        return results

    def get_stats(self) -> Dict:
        """Get index statistics"""
        try:
            stats = self.index.describe_index_stats()
            return {
                'total_vectors': stats.get('total_vector_count', 0),
                'dimension': stats.get('dimension', 0),
                'index_fullness': stats.get('index_fullness', 0)
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}
