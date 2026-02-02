"""
config.py

Centralized configuration for Ray Document Processing Pipeline

Author: Prudhvi
Organization: Thoughtworks
"""

import os
from typing import Optional


class PipelineConfig:
    """Centralized configuration for the pipeline."""
    
    # ========================================================================
    # AWS CONFIGURATION
    # ========================================================================
    
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')
    
    # S3 Configuration
    S3_BUCKET: str = os.getenv('S3_BUCKET', 'your-document-pipeline')
    S3_INPUT_PREFIX: str = 'input'
    S3_EXTRACTED_PREFIX: str = 'extracted'
    S3_CHUNKS_PREFIX: str = 'chunks'
    S3_ENRICHED_PREFIX: str = 'enriched'
    S3_EMBEDDINGS_PREFIX: str = 'embeddings'
    S3_ERRORS_PREFIX: str = 'errors'
    
    # DynamoDB Tables
    DYNAMODB_CONTROL_TABLE: str = os.getenv('DYNAMODB_CONTROL_TABLE', 'document_processing_control')
    DYNAMODB_AUDIT_TABLE: str = os.getenv('DYNAMODB_AUDIT_TABLE', 'document_processing_audit')
    DYNAMODB_METRICS_TABLE: str = os.getenv('DYNAMODB_METRICS_TABLE', 'pipeline_metrics_daily')
    
    # ========================================================================
    # RAY CONFIGURATION
    # ========================================================================
    
    RAY_ADDRESS: str = os.getenv('RAY_ADDRESS', 'auto')
    RAY_NAMESPACE: str = os.getenv('RAY_NAMESPACE', 'document-pipeline')
    
    # Resource Allocation per Task
    EXTRACTION_NUM_CPUS: int = 2
    EXTRACTION_NUM_GPUS: int = 0
    EXTRACTION_MEMORY_MB: int = 4096
    
    CHUNKING_NUM_CPUS: int = 1
    CHUNKING_NUM_GPUS: int = 0
    CHUNKING_MEMORY_MB: int = 2048
    
    ENRICHMENT_NUM_CPUS: int = 1
    ENRICHMENT_NUM_GPUS: int = 0
    ENRICHMENT_MEMORY_MB: int = 2048
    
    EMBEDDING_NUM_CPUS: int = 2
    EMBEDDING_NUM_GPUS: int = 0
    EMBEDDING_MEMORY_MB: int = 4096
    
    LOADING_NUM_CPUS: int = 1
    LOADING_NUM_GPUS: int = 0
    LOADING_MEMORY_MB: int = 2048
    
    # ========================================================================
    # PROCESSING CONFIGURATION
    # ========================================================================
    
    # Timeouts (seconds)
    EXTRACTION_TIMEOUT: int = 600      # 10 minutes
    CHUNKING_TIMEOUT: int = 300        # 5 minutes
    ENRICHMENT_TIMEOUT: int = 600      # 10 minutes
    EMBEDDING_TIMEOUT: int = 1800      # 30 minutes
    LOADING_TIMEOUT: int = 300         # 5 minutes
    
    # Retry Configuration
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: int = 2        # Exponential backoff: 2^retry_count
    
    # Batch Sizes
    CHUNK_BATCH_SIZE: int = 100
    EMBEDDING_BATCH_SIZE: int = 100
    PINECONE_BATCH_SIZE: int = 100
    
    # Polling Configuration
    POLL_INTERVAL_SECONDS: int = 30
    MAX_DOCUMENTS_PER_POLL: int = 10
    
    # ========================================================================
    # AI/ML CONFIGURATION
    # ========================================================================
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    OPENAI_MODEL: str = os.getenv('OPENAI_MODEL', 'text-embedding-3-small')
    OPENAI_DIMENSIONS: int = int(os.getenv('OPENAI_DIMENSIONS', '1536'))
    OPENAI_GPT_MODEL: str = os.getenv('OPENAI_GPT_MODEL', 'gpt-4o')
    
    # Pinecone Configuration
    PINECONE_API_KEY: str = os.getenv('PINECONE_API_KEY', '')
    PINECONE_ENVIRONMENT: str = os.getenv('PINECONE_ENVIRONMENT', 'us-east-1-aws')
    PINECONE_INDEX: str = os.getenv('PINECONE_INDEX', 'financial-documents')
    PINECONE_NAMESPACE: str = os.getenv('PINECONE_NAMESPACE', 'default')
    PINECONE_METRIC: str = 'cosine'
    
    # AWS Comprehend Configuration
    COMPREHEND_REGION: str = AWS_REGION
    COMPREHEND_LANGUAGE_CODE: str = 'en'
    
    # ========================================================================
    # CHUNKING CONFIGURATION
    # ========================================================================
    
    CHUNK_TARGET_SIZE: int = 1500
    CHUNK_MIN_SIZE: int = 800
    CHUNK_MAX_SIZE: int = 2500
    CHUNK_ENABLE_MERGING: bool = True
    
    # ========================================================================
    # LOGGING CONFIGURATION
    # ========================================================================
    
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # ========================================================================
    # VALIDATION
    # ========================================================================
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present."""
        errors = []
        
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY environment variable not set")
        
        if not cls.PINECONE_API_KEY:
            errors.append("PINECONE_API_KEY environment variable not set")
        
        if not cls.S3_BUCKET:
            errors.append("S3_BUCKET environment variable not set")
        
        if errors:
            print("Configuration errors:")
            for error in errors:
                print(f"  - {error}")
            return False
        
        return True
    
    @classmethod
    def print_config(cls):
        """Print current configuration (masking sensitive values)."""
        print("=" * 80)
        print("PIPELINE CONFIGURATION")
        print("=" * 80)
        print(f"AWS Region: {cls.AWS_REGION}")
        print(f"S3 Bucket: {cls.S3_BUCKET}")
        print(f"DynamoDB Control Table: {cls.DYNAMODB_CONTROL_TABLE}")
        print(f"Ray Address: {cls.RAY_ADDRESS}")
        print(f"OpenAI Model: {cls.OPENAI_MODEL}")
        print(f"OpenAI Dimensions: {cls.OPENAI_DIMENSIONS}")
        print(f"Pinecone Index: {cls.PINECONE_INDEX}")
        print(f"Max Retries: {cls.MAX_RETRIES}")
        print(f"Poll Interval: {cls.POLL_INTERVAL_SECONDS}s")
        print("=" * 80)


# Create global config instance
config = PipelineConfig()
