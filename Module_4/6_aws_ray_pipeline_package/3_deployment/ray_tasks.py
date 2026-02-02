"""
ray_tasks.py

Ray Remote Tasks for Document Processing Pipeline
Each task represents a stage in the pipeline

Author: Prudhvi
Organization: Thoughtworks
"""

import ray
import os
import sys
import json
import time
import logging
from pathlib import Path
from typing import Dict
from datetime import datetime

# Import existing modules
from docling_gold_standard_advanced import DoclingHybridSnapV2
from chunk_semantic_gold import SemanticChunker
from enrich_chunks import ChunkEnrichmentPipeline
sys.path.insert(0, os.path.dirname(__file__))
from load_embeddings_to_pinecone import PineconeLoader

# Import OpenAI embedder
import importlib.util
spec = importlib.util.spec_from_file_location("openai_embeddings", "02_openai_embeddings.py")
openai_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(openai_module)
OpenAIEmbedder = openai_module.OpenAIEmbedder

# Import config and utils
from config import config
from utils import S3Helper, LocalFileManager, format_duration


logger = logging.getLogger(__name__)


# ============================================================================
# RAY REMOTE TASKS
# ============================================================================

@ray.remote(num_cpus=config.EXTRACTION_NUM_CPUS, memory=config.EXTRACTION_MEMORY_MB * 1024 * 1024)
class PDFExtractionTask:
    """Ray remote task for PDF extraction using Docling."""
    
    def __init__(self):
        self.extractor = DoclingHybridSnapV2(
            output_base_dir="/tmp/extracted"
        )
        self.s3_helper = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
        self.file_manager = LocalFileManager()
        self.logger = logging.getLogger(__name__)
    
    def process(self, document_id: str, s3_bucket: str, s3_key: str) -> Dict:
        """
        Extract PDF from S3 and save results back to S3.
        
        Args:
            document_id: Unique document identifier
            s3_bucket: Source S3 bucket
            s3_key: Source S3 key for PDF
        
        Returns:
            Dict with status, output_path, metrics, and error (if any)
        """
        start_time = time.time()
        workspace = self.file_manager.create_document_workspace(document_id)
        
        local_pdf = workspace / "input.pdf"
        local_output = workspace / "extracted"
        
        try:
            self.logger.info(f"Starting PDF extraction for {document_id}")
            
            # Download PDF from S3
            if not self.s3_helper.download_file(s3_key, str(local_pdf)):
                raise Exception(f"Failed to download PDF from s3://{s3_bucket}/{s3_key}")
            
            # Extract using Docling
            self.logger.info(f"Running Docling extraction...")
            self.extractor.extract(str(local_pdf))
            
            # Docling creates output in extracted_docs_hybrid_v2/document_name/
            # Find the actual output directory
            extracted_base = Path("/tmp/extracted/extracted_docs_hybrid_v2")
            output_dirs = list(extracted_base.glob("*"))
            
            if not output_dirs:
                raise Exception("No extraction output found")
            
            actual_output = output_dirs[0]  # Should be only one directory
            
            # Upload results to S3
            s3_output_prefix = f"{config.S3_EXTRACTED_PREFIX}/{document_id}"
            if not self.s3_helper.upload_directory(str(actual_output), s3_output_prefix):
                raise Exception(f"Failed to upload extraction results to S3")
            
            # Read metadata for metrics
            metadata_path = actual_output / "metadata.json"
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            duration = time.time() - start_time
            
            result = {
                'status': 'COMPLETED',
                'output_s3_key': s3_output_prefix,
                'duration_seconds': int(duration),
                'metadata': {
                    'pages_extracted': len(metadata.get('pages', [])),
                    'images_extracted': sum(
                        len(p.get('images', [])) for p in metadata.get('pages', [])
                    )
                }
            }
            
            self.logger.info(
                f"Extraction completed for {document_id} in {format_duration(duration)}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Extraction failed for {document_id}: {e}")
            return {
                'status': 'FAILED',
                'error': str(e),
                'duration_seconds': int(time.time() - start_time)
            }
        
        finally:
            # Cleanup
            self.file_manager.cleanup_document_workspace(document_id)


@ray.remote(num_cpus=config.CHUNKING_NUM_CPUS, memory=config.CHUNKING_MEMORY_MB * 1024 * 1024)
class SemanticChunkingTask:
    """Ray remote task for semantic chunking."""
    
    def __init__(self):
        self.chunker = SemanticChunker(
            target_size=config.CHUNK_TARGET_SIZE,
            min_size=config.CHUNK_MIN_SIZE,
            max_size=config.CHUNK_MAX_SIZE,
            enable_merging=config.CHUNK_ENABLE_MERGING
        )
        self.s3_helper = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
        self.file_manager = LocalFileManager()
        self.logger = logging.getLogger(__name__)
    
    def process(self, document_id: str, extracted_s3_prefix: str) -> Dict:
        """
        Download extracted markdown pages, chunk them, upload chunks to S3.
        
        Args:
            document_id: Unique document identifier
            extracted_s3_prefix: S3 prefix where extracted pages are stored
        
        Returns:
            Dict with status, output_path, metrics, and error (if any)
        """
        start_time = time.time()
        workspace = self.file_manager.create_document_workspace(document_id)
        
        local_pages_dir = workspace / "pages"
        output_file = workspace / "chunks.json"
        
        try:
            self.logger.info(f"Starting chunking for {document_id}")
            
            # Download markdown pages from S3
            pages_prefix = f"{extracted_s3_prefix}/pages/"
            if not self.s3_helper.download_directory(pages_prefix, str(local_pages_dir)):
                raise Exception(f"Failed to download pages from s3://{config.S3_BUCKET}/{pages_prefix}")
            
            # Chunk pages
            self.logger.info(f"Running semantic chunking...")
            chunks = self.chunker.process_folder(str(local_pages_dir))
            
            # Save chunks locally
            output_data = {
                'metadata': {
                    'document_id': document_id,
                    'total_chunks': len(chunks),
                    'chunked_at': datetime.utcnow().isoformat() + 'Z',
                    'chunking_config': {
                        'target_size': config.CHUNK_TARGET_SIZE,
                        'min_size': config.CHUNK_MIN_SIZE,
                        'max_size': config.CHUNK_MAX_SIZE
                    }
                },
                'chunks': chunks
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            # Upload to S3
            s3_output_key = f"{config.S3_CHUNKS_PREFIX}/{document_id}_chunks.json"
            if not self.s3_helper.upload_file(str(output_file), s3_output_key):
                raise Exception(f"Failed to upload chunks to S3")
            
            duration = time.time() - start_time
            
            result = {
                'status': 'COMPLETED',
                'output_s3_key': s3_output_key,
                'duration_seconds': int(duration),
                'metadata': {
                    'chunks_created': len(chunks)
                }
            }
            
            self.logger.info(
                f"Chunking completed for {document_id} in {format_duration(duration)}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Chunking failed for {document_id}: {e}")
            return {
                'status': 'FAILED',
                'error': str(e),
                'duration_seconds': int(time.time() - start_time)
            }
        
        finally:
            self.file_manager.cleanup_document_workspace(document_id)


@ray.remote(num_cpus=config.ENRICHMENT_NUM_CPUS, memory=config.ENRICHMENT_MEMORY_MB * 1024 * 1024)
class EnrichmentTask:
    """Ray remote task for metadata enrichment using AWS Comprehend."""
    
    def __init__(self):
        self.enricher = ChunkEnrichmentPipeline()
        self.s3_helper = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
        self.file_manager = LocalFileManager()
        self.logger = logging.getLogger(__name__)
    
    def process(self, document_id: str, chunks_s3_key: str) -> Dict:
        """
        Download chunks, enrich with AWS Comprehend, upload enriched chunks.
        
        Args:
            document_id: Unique document identifier
            chunks_s3_key: S3 key where chunks JSON is stored
        
        Returns:
            Dict with status, output_path, metrics, and error (if any)
        """
        start_time = time.time()
        workspace = self.file_manager.create_document_workspace(document_id)
        
        local_chunks = workspace / "chunks.json"
        
        try:
            self.logger.info(f"Starting enrichment for {document_id}")
            
            # Download chunks from S3
            if not self.s3_helper.download_file(chunks_s3_key, str(local_chunks)):
                raise Exception(f"Failed to download chunks from s3://{config.S3_BUCKET}/{chunks_s3_key}")
            
            # Enrich chunks
            self.logger.info(f"Running AWS Comprehend enrichment...")
            enriched_file = self.enricher.process(str(local_chunks))
            
            # The enricher creates a new file with _enriched_metadata suffix
            if not enriched_file:
                # Build expected filename
                enriched_file = str(local_chunks).replace('.json', '_enriched_metadata.json')
            
            # Upload to S3
            s3_output_key = f"{config.S3_ENRICHED_PREFIX}/{document_id}_enriched.json"
            if not self.s3_helper.upload_file(enriched_file, s3_output_key):
                raise Exception(f"Failed to upload enriched chunks to S3")
            
            # Read enriched data for metrics
            with open(enriched_file, 'r') as f:
                data = json.load(f)
            
            duration = time.time() - start_time
            
            result = {
                'status': 'COMPLETED',
                'output_s3_key': s3_output_key,
                'duration_seconds': int(duration),
                'metadata': {
                    'comprehend_calls': len(data.get('chunks', [])),
                    'chunks_enriched': len(data.get('chunks', []))
                }
            }
            
            self.logger.info(
                f"Enrichment completed for {document_id} in {format_duration(duration)}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Enrichment failed for {document_id}: {e}")
            return {
                'status': 'FAILED',
                'error': str(e),
                'duration_seconds': int(time.time() - start_time)
            }
        
        finally:
            self.file_manager.cleanup_document_workspace(document_id)


@ray.remote(num_cpus=config.EMBEDDING_NUM_CPUS, memory=config.EMBEDDING_MEMORY_MB * 1024 * 1024)
class EmbeddingTask:
    """Ray remote task for OpenAI embedding generation."""
    
    def __init__(self):
        self.embedder = OpenAIEmbedder(
            model=config.OPENAI_MODEL,
            dimensions=config.OPENAI_DIMENSIONS,
            batch_size=config.EMBEDDING_BATCH_SIZE
        )
        self.s3_helper = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
        self.file_manager = LocalFileManager()
        self.logger = logging.getLogger(__name__)
    
    def process(self, document_id: str, enriched_s3_key: str) -> Dict:
        """
        Download enriched chunks, generate embeddings, upload to S3.
        
        Args:
            document_id: Unique document identifier
            enriched_s3_key: S3 key where enriched chunks are stored
        
        Returns:
            Dict with status, output_path, metrics, and error (if any)
        """
        start_time = time.time()
        workspace = self.file_manager.create_document_workspace(document_id)
        
        local_enriched = workspace / "enriched.json"
        
        try:
            self.logger.info(f"Starting embedding generation for {document_id}")
            
            # Download enriched chunks from S3
            if not self.s3_helper.download_file(enriched_s3_key, str(local_enriched)):
                raise Exception(f"Failed to download enriched chunks from s3://{config.S3_BUCKET}/{enriched_s3_key}")
            
            # Generate embeddings
            self.logger.info(f"Running OpenAI embedding generation...")
            embedded_file = self.embedder.process(str(local_enriched))
            
            # Upload to S3
            s3_output_key = f"{config.S3_EMBEDDINGS_PREFIX}/{document_id}_embeddings.json"
            if not self.s3_helper.upload_file(embedded_file, s3_output_key):
                raise Exception(f"Failed to upload embeddings to S3")
            
            # Read for cost tracking
            with open(embedded_file, 'r') as f:
                data = json.load(f)
            
            cost_info = data['metadata']['cost_tracking']
            duration = time.time() - start_time
            
            result = {
                'status': 'COMPLETED',
                'output_s3_key': s3_output_key,
                'duration_seconds': int(duration),
                'metadata': {
                    'tokens_processed': cost_info['total_tokens'],
                    'openai_cost_usd': cost_info['total_cost_usd'],
                    'embeddings_generated': data['metadata']['total_chunks']
                }
            }
            
            self.logger.info(
                f"Embedding completed for {document_id} in {format_duration(duration)}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Embedding failed for {document_id}: {e}")
            return {
                'status': 'FAILED',
                'error': str(e),
                'duration_seconds': int(time.time() - start_time)
            }
        
        finally:
            self.file_manager.cleanup_document_workspace(document_id)


@ray.remote(num_cpus=config.LOADING_NUM_CPUS, memory=config.LOADING_MEMORY_MB * 1024 * 1024)
class VectorLoadingTask:
    """Ray remote task for loading vectors to Pinecone."""
    
    def __init__(self):
        self.loader = PineconeLoader(api_key=config.PINECONE_API_KEY)
        self.s3_helper = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
        self.file_manager = LocalFileManager()
        self.logger = logging.getLogger(__name__)
    
    def process(self, document_id: str, embeddings_s3_key: str) -> Dict:
        """
        Download embeddings from S3 and load into Pinecone.
        
        Args:
            document_id: Unique document identifier
            embeddings_s3_key: S3 key where embeddings are stored
        
        Returns:
            Dict with status, metrics, and error (if any)
        """
        start_time = time.time()
        workspace = self.file_manager.create_document_workspace(document_id)
        
        local_embeddings = workspace / "embeddings.json"
        
        try:
            self.logger.info(f"Starting vector loading for {document_id}")
            
            # Download embeddings from S3
            if not self.s3_helper.download_file(embeddings_s3_key, str(local_embeddings)):
                raise Exception(f"Failed to download embeddings from s3://{config.S3_BUCKET}/{embeddings_s3_key}")
            
            # Initialize Pinecone
            self.logger.info(f"Initializing Pinecone connection...")
            if not self.loader.initialize():
                raise Exception("Failed to initialize Pinecone client")
            
            # Load JSON file
            data = self.loader.load_json_file(str(local_embeddings))
            if not data:
                raise Exception("Failed to load embeddings JSON")
            
            # Create or get index
            if not self.loader.create_or_get_index(
                index_name=config.PINECONE_INDEX,
                dimensions=data['dimensions'],
                metric=config.PINECONE_METRIC
            ):
                raise Exception("Failed to create/access Pinecone index")
            
            # Upload vectors
            self.logger.info(f"Uploading vectors to Pinecone...")
            if not self.loader.upsert_vectors(
                chunks=data['chunks'],
                namespace=config.PINECONE_NAMESPACE,
                batch_size=config.PINECONE_BATCH_SIZE
            ):
                raise Exception("Failed to upsert vectors to Pinecone")
            
            duration = time.time() - start_time
            
            result = {
                'status': 'COMPLETED',
                'duration_seconds': int(duration),
                'metadata': {
                    'vectors_uploaded': len(data['chunks']),
                    'pinecone_index': config.PINECONE_INDEX,
                    'pinecone_namespace': config.PINECONE_NAMESPACE
                }
            }
            
            self.logger.info(
                f"Vector loading completed for {document_id} in {format_duration(duration)}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Vector loading failed for {document_id}: {e}")
            return {
                'status': 'FAILED',
                'error': str(e),
                'duration_seconds': int(time.time() - start_time)
            }
        
        finally:
            self.file_manager.cleanup_document_workspace(document_id)
