"""
ray_orchestrator.py

Main Ray Pipeline Orchestrator
Coordinates all pipeline stages and manages document processing flow

Author: Prudhvi
Organization: Thoughtworks

Usage:
    python ray_orchestrator.py
"""

import ray
import time
import logging
from datetime import datetime
from typing import Dict, List

from config import config
from dynamodb_manager import DynamoDBManager
from ray_tasks import (
    PDFExtractionTask,
    SemanticChunkingTask,
    EnrichmentTask,
    EmbeddingTask,
    VectorLoadingTask
)
from utils import setup_logging, get_timestamp, format_duration


logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Main orchestrator for the document processing pipeline."""
    
    def __init__(self):
        """Initialize orchestrator."""
        self.db_manager = DynamoDBManager()
        self.processing_count = 0
        self.completed_count = 0
        self.failed_count = 0
        
        logger.info("Pipeline Orchestrator initialized")
    
    def process_document(self, document_id: str, s3_bucket: str, s3_key: str) -> bool:
        """
        Process a single document through all pipeline stages.
        
        Args:
            document_id: Unique document identifier
            s3_bucket: Source S3 bucket
            s3_key: Source S3 key
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("="*80)
        logger.info(f"Starting pipeline for document: {document_id}")
        logger.info("="*80)
        
        pipeline_start = time.time()
        
        try:
            # ================================================================
            # STAGE 1: PDF EXTRACTION
            # ================================================================
            logger.info("Stage 1/5: PDF Extraction")
            extraction_result = self._execute_stage(
                task_class=PDFExtractionTask,
                stage_name='extraction',
                document_id=document_id,
                s3_bucket=s3_bucket,
                s3_key=s3_key
            )
            
            if extraction_result['status'] != 'COMPLETED':
                raise Exception(f"Extraction failed: {extraction_result.get('error')}")
            
            # ================================================================
            # STAGE 2: SEMANTIC CHUNKING
            # ================================================================
            logger.info("Stage 2/5: Semantic Chunking")
            chunking_result = self._execute_stage(
                task_class=SemanticChunkingTask,
                stage_name='chunking',
                document_id=document_id,
                extracted_s3_prefix=extraction_result['output_s3_key']
            )
            
            if chunking_result['status'] != 'COMPLETED':
                raise Exception(f"Chunking failed: {chunking_result.get('error')}")
            
            # ================================================================
            # STAGE 3: METADATA ENRICHMENT
            # ================================================================
            logger.info("Stage 3/5: Metadata Enrichment")
            enrichment_result = self._execute_stage(
                task_class=EnrichmentTask,
                stage_name='enrichment',
                document_id=document_id,
                chunks_s3_key=chunking_result['output_s3_key']
            )
            
            if enrichment_result['status'] != 'COMPLETED':
                raise Exception(f"Enrichment failed: {enrichment_result.get('error')}")
            
            # ================================================================
            # STAGE 4: EMBEDDING GENERATION
            # ================================================================
            logger.info("Stage 4/5: Embedding Generation")
            embedding_result = self._execute_stage(
                task_class=EmbeddingTask,
                stage_name='embedding',
                document_id=document_id,
                enriched_s3_key=enrichment_result['output_s3_key']
            )
            
            if embedding_result['status'] != 'COMPLETED':
                raise Exception(f"Embedding failed: {embedding_result.get('error')}")
            
            # ================================================================
            # STAGE 5: VECTOR LOADING
            # ================================================================
            logger.info("Stage 5/5: Vector Loading to Pinecone")
            loading_result = self._execute_stage(
                task_class=VectorLoadingTask,
                stage_name='loading',
                document_id=document_id,
                embeddings_s3_key=embedding_result['output_s3_key']
            )
            
            if loading_result['status'] != 'COMPLETED':
                raise Exception(f"Loading failed: {loading_result.get('error')}")
            
            # ================================================================
            # MARK DOCUMENT AS COMPLETED
            # ================================================================
            self.db_manager.mark_document_completed(document_id)
            
            total_duration = time.time() - pipeline_start
            
            logger.info("="*80)
            logger.info(f"✓ Pipeline COMPLETED for {document_id}")
            logger.info(f"  Total time: {format_duration(total_duration)}")
            logger.info("="*80)
            
            self.completed_count += 1
            return True
            
        except Exception as e:
            logger.error(f"✗ Pipeline FAILED for {document_id}: {e}")
            self.db_manager.mark_document_failed(
                document_id=document_id,
                stage='pipeline',
                error=str(e)
            )
            
            self.failed_count += 1
            return False
    
    def _execute_stage(self, task_class, stage_name: str, 
                      document_id: str, **kwargs) -> Dict:
        """
        Execute a single pipeline stage with error handling and tracking.
        
        Args:
            task_class: Ray remote task class
            stage_name: Name of the stage (extraction, chunking, etc.)
            document_id: Document identifier
            **kwargs: Additional arguments for the task
        
        Returns:
            Dict with stage execution results
        """
        started_at = get_timestamp()
        
        # Update stage status to IN_PROGRESS
        self.db_manager.update_stage_status(
            document_id=document_id,
            stage=stage_name,
            status='IN_PROGRESS',
            started_at=started_at
        )
        
        # Execute task
        logger.info(f"  Executing {stage_name}...")
        task = task_class.remote()
        result = ray.get(task.process.remote(document_id=document_id, **kwargs))
        
        # Update stage status based on result
        completed_at = get_timestamp() if result['status'] == 'COMPLETED' else None
        
        self.db_manager.update_stage_status(
            document_id=document_id,
            stage=stage_name,
            status=result['status'],
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=result.get('duration_seconds'),
            output_s3_key=result.get('output_s3_key'),
            error=result.get('error'),
            metadata=result.get('metadata', {})
        )
        
        if result['status'] == 'COMPLETED':
            logger.info(f"  ✓ {stage_name} completed in {format_duration(result['duration_seconds'])}")
        else:
            logger.error(f"  ✗ {stage_name} failed: {result.get('error')}")
        
        return result
    
    def poll_and_process(self):
        """
        Main polling loop - continuously check for pending documents and process them.
        """
        logger.info("="*80)
        logger.info("Starting polling loop...")
        logger.info(f"Poll interval: {config.POLL_INTERVAL_SECONDS}s")
        logger.info(f"Max documents per poll: {config.MAX_DOCUMENTS_PER_POLL}")
        logger.info("="*80)
        
        while True:
            try:
                # Fetch pending documents
                pending_docs = self.db_manager.get_pending_documents(
                    limit=config.MAX_DOCUMENTS_PER_POLL
                )
                
                if not pending_docs:
                    logger.info(f"No pending documents. Waiting {config.POLL_INTERVAL_SECONDS}s...")
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                    continue
                
                logger.info(f"Found {len(pending_docs)} pending documents")
                
                # Process each document
                futures = []
                for doc in pending_docs:
                    # Process document asynchronously
                    future = self._process_document_async(
                        document_id=doc['document_id'],
                        s3_bucket=doc['source_bucket'],
                        s3_key=doc['source_s3_key']
                    )
                    futures.append((doc['document_id'], future))
                
                # Wait for all to complete (or fail)
                for doc_id, future in futures:
                    try:
                        ray.get(future)
                    except Exception as e:
                        logger.error(f"Error processing {doc_id}: {e}")
                
                # Print statistics
                self._print_statistics()
                
            except KeyboardInterrupt:
                logger.info("Received interrupt signal. Shutting down...")
                break
            
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                time.sleep(config.POLL_INTERVAL_SECONDS)
    
    @ray.remote
    def _process_document_async(self, document_id: str, s3_bucket: str, s3_key: str):
        """Async wrapper for process_document."""
        return self.process_document(document_id, s3_bucket, s3_key)
    
    def _print_statistics(self):
        """Print current processing statistics."""
        logger.info("-"*80)
        logger.info("STATISTICS")
        logger.info(f"  Processing: {self.processing_count}")
        logger.info(f"  Completed:  {self.completed_count}")
        logger.info(f"  Failed:     {self.failed_count}")
        logger.info("-"*80)


def main():
    """Main execution function."""
    
    # Setup logging
    setup_logging(level=config.LOG_LEVEL)
    
    logger.info("="*80)
    logger.info("RAY DOCUMENT PROCESSING PIPELINE")
    logger.info("="*80)
    
    # Validate configuration
    if not config.validate():
        logger.error("Configuration validation failed. Exiting.")
        return
    
    # Print configuration
    config.print_config()
    
    # Initialize Ray
    logger.info("Initializing Ray...")
    
    if config.RAY_ADDRESS == 'auto':
        # Connect to existing Ray cluster
        ray.init(address='auto', namespace=config.RAY_NAMESPACE)
    else:
        # Start local Ray cluster
        ray.init(namespace=config.RAY_NAMESPACE)
    
    logger.info(f"Ray initialized: {ray.is_initialized()}")
    logger.info(f"Ray dashboard: {ray.get_dashboard_url()}")
    
    # Create orchestrator
    orchestrator = PipelineOrchestrator()
    
    # Start polling loop
    try:
        orchestrator.poll_and_process()
    
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    
    finally:
        ray.shutdown()
        logger.info("Ray shutdown complete")


if __name__ == "__main__":
    main()
