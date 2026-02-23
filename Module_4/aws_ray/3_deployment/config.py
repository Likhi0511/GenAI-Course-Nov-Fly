import os
from typing import Optional

class PipelineConfig:
    """
    FIXED VERSION: Includes missing resource constants and S3 prefixes
    required by ray_tasks.py and ray_orchestrator.py.
    """

    # ========================================================================
    # AWS INFRASTRUCTURE (From CloudFormation Env Vars)
    # ========================================================================
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')
    S3_BUCKET: str = os.getenv('S3_BUCKET', '')
    
    DYNAMODB_CONTROL_TABLE: str = os.getenv('DYNAMODB_CONTROL_TABLE', '')
    DYNAMODB_AUDIT_TABLE: str = os.getenv('DYNAMODB_AUDIT_TABLE', '')
    DYNAMODB_METRICS_TABLE: str = os.getenv('DYNAMODB_METRICS_TABLE', '')

    # ========================================================================
    # RAY CLUSTER CONFIGURATION
    # ========================================================================
    # Critical Fix: RAY_ADDRESS must be "auto" on Head Node
    RAY_ADDRESS: str = os.getenv('RAY_ADDRESS', 'auto')
    RAY_NAMESPACE: str = os.getenv('RAY_NAMESPACE', 'document-pipeline')

    # ------------------------------------------------------------------------
    # RAY RESOURCE ALLOCATION (Fixes AttributeError: 'EXTRACTION_NUM_CPUS')
    # ------------------------------------------------------------------------
    # These constants are explicitly required by @ray.remote decorators 
    # in ray_tasks.py.
    
    # Stage 1: Extraction
    EXTRACTION_NUM_CPUS: int = 1
    EXTRACTION_MEMORY_MB: int = 2048

    # Stage 2: Chunking
    CHUNKING_NUM_CPUS: int = 1
    CHUNKING_MEMORY_MB: int = 512

    # Stage 3: Enrichment
    ENRICHMENT_NUM_CPUS: int = 1
    ENRICHMENT_MEMORY_MB: int = 512

    # Stage 4: Embedding
    EMBEDDING_NUM_CPUS: int = 1
    EMBEDDING_MEMORY_MB: int = 512

    # Stage 5: Loading
    LOADING_NUM_CPUS: int = 1
    LOADING_MEMORY_MB: int = 512

    # ========================================================================
    # S3 PATH CONFIGURATION
    # ========================================================================
    # Used to coordinate data flow between pipeline stages
    S3_INPUT_PREFIX: str = 'input/'
    S3_EXTRACTED_PREFIX: str = 'extracted'
    S3_CHUNKS_PREFIX: str = 'chunks'
    S3_ENRICHED_PREFIX: str = 'enriched'
    S3_EMBEDDINGS_PREFIX: str = 'embeddings'

    # ========================================================================
    # STAGE-SPECIFIC PARAMETERS
    # ========================================================================
    
    # Stage 2: Chunking Strategy
    CHUNK_TARGET_SIZE: int = 1500
    CHUNK_MIN_SIZE: int = 500
    CHUNK_MAX_SIZE: int = 3000

    # Stage 4: Embedding Settings
    # Note: ray_tasks.py specifically looks for 'OPENAI_MODEL' and 'OPENAI_DIMENSIONS'
    OPENAI_MODEL: str = 'text-embedding-ada-002'
    OPENAI_DIMENSIONS: int = 1536
    EMBEDDING_BATCH_SIZE: int = 100

    # Stage 5: Pinecone Settings
    PINECONE_INDEX: str = os.getenv('PINECONE_INDEX_NAME', 'clinical-trials-index')
    PINECONE_NAMESPACE: str = os.getenv('PINECONE_NAMESPACE', 'clinical-trials')
    PINECONE_METRIC: str = 'cosine'
    PINECONE_BATCH_SIZE: int = 100

    # ========================================================================
    # API KEYS & LOGGING
    # ========================================================================
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    PINECONE_API_KEY: str = os.getenv('PINECONE_API_KEY', '')
    
    POLLING_INTERVAL: int = int(os.getenv('POLLING_INTERVAL', '30'))
    MAX_DOCUMENTS_PER_POLL: int = int(os.getenv('MAX_DOCUMENTS_PER_POLL', '10'))
    PROCESSING_VERSION: str = os.getenv('PROCESSING_VERSION', 'v1')
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    @classmethod
    def validate(cls) -> bool:
        """Verifies all critical AWS and API configurations are present."""
        required = [
            (cls.S3_BUCKET, "S3_BUCKET"),
            (cls.DYNAMODB_CONTROL_TABLE, "DYNAMODB_CONTROL_TABLE"),
            (cls.OPENAI_API_KEY, "OPENAI_API_KEY"),
            (cls.PINECONE_API_KEY, "PINECONE_API_KEY")
        ]
        
        missing = [name for val, name in required if not val]
        if missing:
            print(f"❌ CONFIGURATION ERROR: Missing {', '.join(missing)}")
            return False
        return True

    @classmethod
    def print_config(cls):
        """Standard summary for CloudWatch logs."""
        print("PIPELINE CONFIGURATION LOADED")
        print(f"Bucket: {cls.S3_BUCKET} | Region: {cls.AWS_REGION}")
        print(f"Ray: {cls.RAY_ADDRESS} | Namespace: {cls.RAY_NAMESPACE}")

config = PipelineConfig()