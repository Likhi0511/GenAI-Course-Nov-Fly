"""
S3 Vector Retrieval - Updated with Debug Logging
Query vectors from S3 vector indexes
"""

import boto3
from typing import List, Dict
import logging
import json

from langchain_openai import OpenAIEmbeddings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class S3VectorRetriever:
    """Retrieve vectors from S3 vector indexes"""

    def __init__(
        self,
        semantic_bucket: str,
        procedural_bucket: str,
        aws_region: str = 'us-east-1'
    ):
        self.semantic_bucket = semantic_bucket
        self.procedural_bucket = procedural_bucket

        self.s3vectors = boto3.client('s3vectors', region_name=aws_region)
        self.embeddings = OpenAIEmbeddings(model='text-embedding-3-small')

        logger.info(f"Initialized S3VectorRetriever")
        logger.info(f"  Semantic bucket: {semantic_bucket}")
        logger.info(f"  Procedural bucket: {procedural_bucket}")

    def search_semantic(self, query: str, top_k: int = 8) -> List[Dict]:
        """Search semantic memory"""
        query_embedding = self.embeddings.embed_query(query)

        try:
            response = self.s3vectors.query_vectors(
                vectorBucketName=self.semantic_bucket,
                indexName='semantic-index',
                queryVector={'float32': query_embedding},
                topK=top_k,
                returnDistance=True,
                returnMetadata=True
                # returnData is NOT a valid parameter - removed
            )
            print("search_semantic response",response)

            vectors = response.get('vectors', [])
            logger.info(f"Found {len(vectors)} semantic results")

            # Debug: log what we got
            if vectors:
                sample = vectors[0]
                logger.debug(f"Sample vector keys: {list(sample.keys())}")
                logger.debug(f"Sample metadata keys: {list(sample.get('metadata', {}).keys())}")

                # Check if text is in metadata
                if 'metadata' in sample and 'text' in sample['metadata']:
                    text_len = len(sample['metadata']['text'])
                    logger.info(f"✓ Text found in metadata (length: {text_len} chars)")
                else:
                    logger.warning(f"✗ Text NOT found in metadata - re-run ingestion!")
                    logger.warning(f"  Available metadata keys: {list(sample.get('metadata', {}).keys())}")

            return vectors

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            logger.exception("Full error:")
            return []

    def search_procedural(self, query: str, top_k: int = 3) -> List[Dict]:
        """Search procedural memory"""
        query_embedding = self.embeddings.embed_query(query)

        try:
            response = self.s3vectors.query_vectors(
                vectorBucketName=self.procedural_bucket,
                indexName='procedural-index',
                queryVector={'float32': query_embedding},
                topK=top_k,
                returnDistance=True,
                returnMetadata=True
                # returnData is NOT a valid parameter - removed
            )
            print("search_procedural response", response)

            vectors = response.get('vectors', [])
            logger.info(f"Found {len(vectors)} procedural results")

            # Debug: check for text in metadata
            if vectors:
                sample = vectors[0]
                if 'metadata' in sample and 'text' in sample['metadata']:
                    text_len = len(sample['metadata']['text'])
                    logger.info(f"✓ Text found in metadata (length: {text_len} chars)")
                else:
                    logger.warning(f"✗ Text NOT found in metadata - re-run ingestion!")

            return vectors

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