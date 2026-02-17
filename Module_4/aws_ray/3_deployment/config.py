"""
config.py - Centralized configuration for Ray Document Processing Pipeline

Author: Prudhvi | Thoughtworks
"""

import os


class PipelineConfig:

    # =========================================================================
    # AWS
    # =========================================================================
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')

    S3_BUCKET: str           = os.getenv('S3_BUCKET', 'your-document-pipeline')
    S3_INPUT_PREFIX: str     = 'input'
    S3_EXTRACTED_PREFIX: str = 'extracted'
    S3_CHUNKS_PREFIX: str    = 'chunks'
    S3_ENRICHED_PREFIX: str  = 'enriched'
    S3_EMBEDDINGS_PREFIX: str = 'embeddings'
    S3_ERRORS_PREFIX: str    = 'errors'

    DYNAMODB_CONTROL_TABLE: str = os.getenv('DYNAMODB_CONTROL_TABLE', 'document_processing_control')
    DYNAMODB_AUDIT_TABLE: str   = os.getenv('DYNAMODB_AUDIT_TABLE',   'document_processing_audit')
    DYNAMODB_METRICS_TABLE: str = os.getenv('DYNAMODB_METRICS_TABLE', 'pipeline_metrics_daily')

    # =========================================================================
    # RAY
    # =========================================================================
    RAY_ADDRESS: str   = os.getenv('RAY_ADDRESS', 'auto')
    RAY_NAMESPACE: str = os.getenv('RAY_NAMESPACE', 'document-pipeline')

    # CPU + memory per stage (Fargate Spot — no GPU needed)
    EXTRACTION_NUM_CPUS: int  = 2;  EXTRACTION_MEMORY_MB: int  = 4096
    CHUNKING_NUM_CPUS: int    = 1;  CHUNKING_MEMORY_MB: int    = 2048
    ENRICHMENT_NUM_CPUS: int  = 1;  ENRICHMENT_MEMORY_MB: int  = 2048
    EMBEDDING_NUM_CPUS: int   = 2;  EMBEDDING_MEMORY_MB: int   = 4096
    LOADING_NUM_CPUS: int     = 1;  LOADING_MEMORY_MB: int     = 2048

    # =========================================================================
    # PROCESSING
    # =========================================================================
    EXTRACTION_TIMEOUT: int = 600   # 10 min
    CHUNKING_TIMEOUT: int   = 300   # 5 min
    ENRICHMENT_TIMEOUT: int = 600   # 10 min
    EMBEDDING_TIMEOUT: int  = 1800  # 30 min
    LOADING_TIMEOUT: int    = 300   # 5 min

    MAX_RETRIES: int             = 3
    EMBEDDING_BATCH_SIZE: int    = 100
    PINECONE_BATCH_SIZE: int     = 100
    POLL_INTERVAL_SECONDS: int   = 30
    MAX_DOCUMENTS_PER_POLL: int  = 10

    # =========================================================================
    # AI / ML
    # =========================================================================
    OPENAI_API_KEY: str    = os.getenv('OPENAI_API_KEY', '')
    OPENAI_MODEL: str      = os.getenv('OPENAI_MODEL', 'text-embedding-3-small')
    OPENAI_DIMENSIONS: int = int(os.getenv('OPENAI_DIMENSIONS', '1536'))
    OPENAI_GPT_MODEL: str  = os.getenv('OPENAI_GPT_MODEL', 'gpt-4o')

    PINECONE_API_KEY: str  = os.getenv('PINECONE_API_KEY', '')
    PINECONE_INDEX: str    = os.getenv('PINECONE_INDEX', 'financial-documents')
    PINECONE_NAMESPACE: str = os.getenv('PINECONE_NAMESPACE', 'default')
    PINECONE_METRIC: str   = 'cosine'

    # =========================================================================
    # CHUNKING
    # =========================================================================
    CHUNK_TARGET_SIZE: int    = 1500
    CHUNK_MIN_SIZE: int       = 800
    CHUNK_MAX_SIZE: int       = 3000
    CHUNK_MAX_TABLE_SIZE: int = 2000

    # =========================================================================
    # LOGGING
    # =========================================================================
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    # =========================================================================
    # VALIDATION
    # =========================================================================
    @classmethod
    def validate(cls) -> bool:
        errors = []
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY not set")
        if not cls.PINECONE_API_KEY:
            errors.append("PINECONE_API_KEY not set")
        if not cls.S3_BUCKET:
            errors.append("S3_BUCKET not set")
        if errors:
            for e in errors:
                print(f"  [config error] {e}")
        return len(errors) == 0

    @classmethod
    def print_config(cls):
        print("=" * 60)
        print("PIPELINE CONFIGURATION")
        print("=" * 60)
        print(f"AWS Region:        {cls.AWS_REGION}")
        print(f"S3 Bucket:         {cls.S3_BUCKET}")
        print(f"Control Table:     {cls.DYNAMODB_CONTROL_TABLE}")
        print(f"Ray Address:       {cls.RAY_ADDRESS}")
        print(f"Embedding Model:   {cls.OPENAI_MODEL} ({cls.OPENAI_DIMENSIONS}d)")
        print(f"Pinecone Index:    {cls.PINECONE_INDEX}")
        print(f"Poll Interval:     {cls.POLL_INTERVAL_SECONDS}s")
        print("=" * 60)


config = PipelineConfig()
