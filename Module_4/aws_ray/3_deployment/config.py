"""
config.py - Centralized Configuration for Ray Document Processing Pipeline

================================================================================
                        CONFIGURATION MANAGEMENT
================================================================================

This file is the SINGLE SOURCE OF TRUTH for all pipeline configuration.

Why centralize configuration?
✓ Single place to change settings (don't hunt through code!)
✓ Environment-specific configs (dev/staging/production)
✓ Easy validation (check all settings at startup)
✓ Clear documentation (what each setting does)
✓ Type safety (IDE knows what types to expect)

The 12-Factor App Principle:
"Store config in environment variables"
- Dev: Local .env file
- Production: AWS Secrets Manager / ECS environment variables
- Never hardcode secrets in code!

How It Works:
1. Read from environment variables (os.getenv)
2. Fall back to sensible defaults
3. Validate on startup (fail fast if misconfigured)
4. Print config for debugging

Example Usage:
```python
from config import config

# Access settings
bucket = config.S3_BUCKET
api_key = config.OPENAI_API_KEY

# Validate before starting
if not config.validate():
    print("Configuration error!")
    exit(1)
```

Author: Prudhvi | Thoughtworks
"""

"""
config.py - Configuration Management for Ray Document Processing Pipeline
===========================================================================

FIXED VERSION - Matches CloudFormation Environment Variables

This file centralizes ALL configuration for the pipeline, following the
12-Factor App methodology: "Store config in environment variables"

Author: Prudhvi | Thoughtworks

================================================================================
                        WHAT CHANGED (CRITICAL FIXES)
================================================================================

OLD (WRONG):
------------
S3_BUCKET_NAME = os.getenv('BUCKET_NAME')
CONTROL_TABLE = os.getenv('CONTROL_TABLE_NAME')

NEW (CORRECT):
--------------
S3_BUCKET = os.getenv('S3_BUCKET')
DYNAMODB_CONTROL_TABLE = os.getenv('DYNAMODB_CONTROL_TABLE')

WHY THIS MATTERS:
CloudFormation ECS Task Definition injects environment variables with specific
names. If your code uses different names, it won't find the values!

Result: Container starts → Can't find bucket → Crashes immediately

================================================================================
                        ENVIRONMENT VARIABLE MAPPING
================================================================================

CloudFormation provides these environment variables to ECS containers:

AWS Resources:
  S3_BUCKET                  → S3 bucket name
  DYNAMODB_CONTROL_TABLE     → Control table name
  DYNAMODB_AUDIT_TABLE       → Audit table name
  DYNAMODB_METRICS_TABLE     → Metrics table name
  AWS_REGION                 → AWS region

Ray Configuration:
  RAY_ADDRESS                → 'auto' for head, 'ray-head.local:6379' for workers
  RAY_NAMESPACE              → 'document-pipeline'

API Keys (from Secrets Manager):
  OPENAI_API_KEY             → OpenAI API key
  PINECONE_API_KEY           → Pinecone API key

Optional Settings:
  LOG_LEVEL                  → 'INFO', 'DEBUG', etc.
  POLLING_INTERVAL           → Seconds between polls (default: 30)
  PROCESSING_VERSION         → 'v1'

================================================================================
                            USAGE PATTERN
================================================================================

This config uses the Singleton pattern - one instance shared across all modules.

Good Practice:
--------------
from config import config

# Access configuration
bucket = config.S3_BUCKET
table = config.DYNAMODB_CONTROL_TABLE

# Validate before using
if not config.validate():
    print("Configuration error!")
    exit(1)

Bad Practice:
-------------
import os
bucket = os.getenv('S3_BUCKET')  # Don't repeat this everywhere!

================================================================================
"""

import os
from typing import Optional


# ============================================================================
# CONFIGURATION CLASS
# ============================================================================
# This class contains ALL configuration for the pipeline
# All settings come from environment variables (12-Factor App principle)
# ============================================================================

class PipelineConfig:
    """
    Centralized configuration for the document processing pipeline.

    Design Principles:
    ==================
    1. 12-Factor App: All config from environment variables
    2. Fail Fast: validate() checks required config at startup
    3. Type Safety: Type hints for all attributes
    4. Immutability: Class variables (not instance variables)
    5. Singleton: One config instance for entire application

    Why Class Variables?
    ===================
    Using class variables (not instance variables) means:
    - Only one set of values (singleton pattern)
    - No need to pass config object around
    - Thread-safe (no mutable state)
    - Easy to mock for testing

    Example:
    --------
    from config import config  # Import singleton instance

    # All modules use same config
    bucket = config.S3_BUCKET
    """

    # ========================================================================
    # AWS CONFIGURATION
    # ========================================================================
    # These are set by CloudFormation in the ECS Task Definition
    # CRITICAL: Names must match exactly!
    # ========================================================================

    # ------------------------------------------------------------------------
    # AWS Region
    # ------------------------------------------------------------------------
    # CloudFormation sets: AWS_REGION
    # Example: 'us-east-1', 'eu-west-1'
    #
    # Why we need this:
    # - boto3 clients need to know which region to connect to
    # - Ensures we access resources in the correct region
    # ------------------------------------------------------------------------
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')

    # ------------------------------------------------------------------------
    # S3 Configuration
    # ------------------------------------------------------------------------
    # CloudFormation sets: S3_BUCKET
    # Example: 'ray-document-pipeline-123456789'
    #
    # Why we need this:
    # - Every stage reads/writes to S3
    # - Stage 1: Downloads PDFs from input/
    # - Stages 2-5: Upload intermediate results
    #
    # Folder Structure:
    # s3://bucket/input/           ← PDFs uploaded here
    # s3://bucket/extracted/       ← Stage 1 output
    # s3://bucket/chunks/          ← Stage 2 output
    # s3://bucket/enriched/        ← Stage 3 output
    # s3://bucket/embeddings/      ← Stage 4 output
    # s3://bucket/errors/          ← Failed documents
    # ------------------------------------------------------------------------
    S3_BUCKET: str = os.getenv('S3_BUCKET', '')

    # S3 folder prefixes (these are NOT environment variables)
    S3_INPUT_PREFIX: str = 'input/'
    S3_EXTRACTED_PREFIX: str = 'extracted/'
    S3_CHUNKS_PREFIX: str = 'chunks/'
    S3_ENRICHED_PREFIX: str = 'enriched/'
    S3_EMBEDDINGS_PREFIX: str = 'embeddings/'
    S3_ERRORS_PREFIX: str = 'errors/'

    # ------------------------------------------------------------------------
    # DynamoDB Configuration
    # ------------------------------------------------------------------------
    # CloudFormation sets three table names:
    # - DYNAMODB_CONTROL_TABLE: Tracks current state of each document
    # - DYNAMODB_AUDIT_TABLE: Event history for compliance
    # - DYNAMODB_METRICS_TABLE: Daily aggregated metrics
    #
    # Control Table Schema:
    # - document_id (HASH)
    # - processing_version (RANGE)
    # - status (GSI key): PENDING, IN_PROGRESS, COMPLETED, FAILED
    # - updated_at (GSI range key): ISO timestamp
    # - s3_bucket, s3_key: Source PDF location
    # - current_stage: Which stage is processing
    # - retry_count: Number of retries
    # - ttl: Expiration timestamp (90 days)
    #
    # Audit Table Schema:
    # - document_id (HASH)
    # - timestamp (RANGE)
    # - event_type: DOCUMENT_RECEIVED, STAGE_STARTED, STAGE_COMPLETED, etc.
    # - status, message, metadata
    # - ttl: Expiration timestamp (180 days)
    # ------------------------------------------------------------------------
    DYNAMODB_CONTROL_TABLE: str = os.getenv('DYNAMODB_CONTROL_TABLE', '')
    DYNAMODB_AUDIT_TABLE: str = os.getenv('DYNAMODB_AUDIT_TABLE', '')
    DYNAMODB_METRICS_TABLE: str = os.getenv('DYNAMODB_METRICS_TABLE', '')

    # ========================================================================
    # RAY CONFIGURATION
    # ========================================================================
    # Ray is our distributed computing framework
    # ========================================================================

    # ------------------------------------------------------------------------
    # Ray Connection
    # ------------------------------------------------------------------------
    # CloudFormation sets: RAY_ADDRESS
    #
    # Two modes:
    # 1. Ray Head:   RAY_ADDRESS='auto'
    #    → Connects to local Ray instance (started in same container)
    #
    # 2. Ray Worker: RAY_ADDRESS='ray-head.local:6379'
    #    → Connects to remote Ray head via Service Discovery
    #
    # Why 'auto'?
    # - Head starts Ray in same container (ray start --head)
    # - 'auto' tells Ray to connect to localhost:6379
    #
    # Why 'ray-head.local'?
    # - AWS Cloud Map (Service Discovery) creates DNS record
    # - Workers can find head via DNS instead of IP address
    # - Survives head container restarts (IP may change)
    # ------------------------------------------------------------------------
    RAY_ADDRESS: str = os.getenv('RAY_ADDRESS', 'auto')

    # ------------------------------------------------------------------------
    # Ray Namespace
    # ------------------------------------------------------------------------
    # CloudFormation sets: RAY_NAMESPACE='document-pipeline'
    #
    # Why namespaces?
    # - Isolates different applications on same Ray cluster
    # - Tasks/actors in namespace A can't see namespace B
    # - Good for multi-tenancy
    #
    # For our use case:
    # - Single application, but good practice for future expansion
    # ------------------------------------------------------------------------
    RAY_NAMESPACE: str = os.getenv('RAY_NAMESPACE', 'document-pipeline')

    # ------------------------------------------------------------------------
    # Ray Resource Allocation
    # ------------------------------------------------------------------------
    # Each stage gets specific CPU and memory resources
    # These are used in @ray.remote decorators:
    #
    # @ray.remote(num_cpus=config.RAY_EXTRACTION_CPU,
    #             memory=config.RAY_EXTRACTION_MEMORY)
    # class PDFExtractionTask:
    #     ...
    #
    # Why allocate resources?
    # - Prevents one stage from starving others
    # - Ensures critical stages get priority
    # - Helps Ray scheduler make smart decisions
    #
    # Resource Sizing Logic:
    # - Stage 1 (Extraction): Heavy (Docling + image processing) → 2 CPU, 4GB
    # - Stage 2 (Chunking): Light (text splitting) → 1 CPU, 2GB
    # - Stage 3 (Enrichment): Medium (OpenAI API calls) → 1 CPU, 2GB
    # - Stage 4 (Embedding): Medium (OpenAI API calls) → 1 CPU, 2GB
    # - Stage 5 (Loading): Light (Pinecone upload) → 1 CPU, 2GB
    # ------------------------------------------------------------------------

    # Stage 1: PDF Extraction (Docling + GPT-4 Vision)
    RAY_EXTRACTION_CPU: int = 2
    RAY_EXTRACTION_MEMORY: int = 4096  # MB

    # Stage 2: Semantic Chunking (lightweight text processing)
    RAY_CHUNKING_CPU: int = 1
    RAY_CHUNKING_MEMORY: int = 2048

    # Stage 3: Enrichment (OpenAI API calls)
    RAY_ENRICHMENT_CPU: int = 1
    RAY_ENRICHMENT_MEMORY: int = 2048

    # Stage 4: Embedding Generation (OpenAI API calls)
    RAY_EMBEDDING_CPU: int = 1
    RAY_EMBEDDING_MEMORY: int = 2048

    # Stage 5: Vector Loading (Pinecone upload)
    RAY_LOADING_CPU: int = 1
    RAY_LOADING_MEMORY: int = 2048

    # ========================================================================
    # API KEYS
    # ========================================================================
    # CloudFormation injects these from AWS Secrets Manager
    # NEVER hardcode API keys in code!
    # ========================================================================

    # ------------------------------------------------------------------------
    # OpenAI API Key
    # ------------------------------------------------------------------------
    # CloudFormation flow:
    # 1. You create secret in Secrets Manager
    # 2. You pass secret ARN to CloudFormation
    # 3. ECS Task Definition references secret
    # 4. ECS injects value as environment variable
    #
    # Used for:
    # - Stage 1: GPT-4o Vision (image descriptions)
    # - Stage 3: GPT-4o-mini (metadata extraction)
    # - Stage 4: text-embedding-3-small (embeddings)
    # ------------------------------------------------------------------------
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')

    # ------------------------------------------------------------------------
    # Pinecone API Key
    # ------------------------------------------------------------------------
    # Same flow as OpenAI key
    #
    # Used for:
    # - Stage 5: Uploading vectors to Pinecone index
    # ------------------------------------------------------------------------
    PINECONE_API_KEY: str = os.getenv('PINECONE_API_KEY', '')

    # ========================================================================
    # PROCESSING PARAMETERS
    # ========================================================================
    # How the orchestrator and tasks behave
    # ========================================================================

    # ------------------------------------------------------------------------
    # Orchestrator Polling
    # ------------------------------------------------------------------------
    # How often to check DynamoDB for new documents
    #
    # POLLING_INTERVAL: Seconds between polls
    # - Too fast (5s): Wastes DynamoDB read capacity
    # - Too slow (300s): Delays document processing
    # - Sweet spot: 30s (responsive but not wasteful)
    #
    # MAX_DOCUMENTS_PER_POLL: How many to process per poll
    # - Prevents overwhelming Ray cluster
    # - DynamoDB Query limit is 1MB, this is a logical limit
    # - If 50 documents pending, process 10 now, 10 next poll, etc.
    # ------------------------------------------------------------------------
    POLLING_INTERVAL: int = int(os.getenv('POLLING_INTERVAL', '30'))  # seconds
    MAX_DOCUMENTS_PER_POLL: int = int(os.getenv('MAX_DOCUMENTS_PER_POLL', '10'))

    # ------------------------------------------------------------------------
    # Processing Version
    # ------------------------------------------------------------------------
    # Used in DynamoDB partition key
    # Allows reprocessing same document with different logic
    #
    # Example:
    # - v1: Basic pipeline
    # - v2: Improved chunking algorithm
    #
    # Same document can exist as:
    # - (document_id=doc_123, processing_version=v1)
    # - (document_id=doc_123, processing_version=v2)
    # ------------------------------------------------------------------------
    PROCESSING_VERSION: str = os.getenv('PROCESSING_VERSION', 'v1')

    # ------------------------------------------------------------------------
    # Retry Configuration
    # ------------------------------------------------------------------------
    # How many times to retry failed stages
    #
    # Why retry?
    # - Transient errors: Network hiccups, API rate limits
    # - OpenAI API can return 429 (too many requests)
    # - S3 operations can timeout
    #
    # Why exponential backoff?
    # - First retry: Wait 60s
    # - Second retry: Wait 120s
    # - Third retry: Wait 240s
    # - Gives systems time to recover
    # ------------------------------------------------------------------------
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 60  # seconds (base delay, actual delay is exponential)

    # ------------------------------------------------------------------------
    # Stage Timeouts
    # ------------------------------------------------------------------------
    # Maximum time each stage can run before being killed
    #
    # Why timeouts?
    # - Prevents hung tasks from blocking workers forever
    # - Forces failure → retry instead of infinite wait
    #
    # Timeout Sizing:
    # - Stage 1 (Extraction): 10 min (large PDFs take time)
    # - Stage 2 (Chunking): 5 min (text processing is fast)
    # - Stage 3 (Enrichment): 10 min (many API calls)
    # - Stage 4 (Embedding): 30 min (many embeddings, rate limited)
    # - Stage 5 (Loading): 5 min (Pinecone upload is fast)
    # ------------------------------------------------------------------------
    STAGE1_TIMEOUT: int = 600  # 10 minutes
    STAGE2_TIMEOUT: int = 300  # 5 minutes
    STAGE3_TIMEOUT: int = 600  # 10 minutes
    STAGE4_TIMEOUT: int = 1800  # 30 minutes
    STAGE5_TIMEOUT: int = 300  # 5 minutes

    # ========================================================================
    # OPENAI CONFIGURATION
    # ========================================================================

    # ------------------------------------------------------------------------
    # Model Selection
    # ------------------------------------------------------------------------
    # Different models for different tasks
    #
    # OPENAI_MODEL_EXTRACTION: 'gpt-4o' (Vision capable)
    # - Used in Stage 1 for image descriptions
    # - Needs vision capability (gpt-3.5 can't do this)
    # - Cost: ~$0.01 per image
    #
    # OPENAI_MODEL_ENRICHMENT: 'gpt-4o-mini' (Text only, cheaper)
    # - Used in Stage 3 for metadata extraction
    # - Cheaper than gpt-4o (~10× cheaper)
    # - Cost: ~$0.001 per chunk
    #
    # OPENAI_EMBEDDING_MODEL: 'text-embedding-3-small'
    # - Used in Stage 4 for embeddings
    # - Cheaper and faster than text-embedding-3-large
    # - Cost: ~$0.00002 per 1K tokens
    # ------------------------------------------------------------------------
    OPENAI_MODEL_EXTRACTION: str = 'gpt-4o'
    OPENAI_MODEL_ENRICHMENT: str = 'gpt-4o-mini'
    OPENAI_EMBEDDING_MODEL: str = 'text-embedding-3-small'
    OPENAI_EMBEDDING_DIMENSIONS: int = 1536  # text-embedding-3-small outputs 1536D

    # ========================================================================
    # PINECONE CONFIGURATION
    # ========================================================================

    # ------------------------------------------------------------------------
    # Index Configuration
    # ------------------------------------------------------------------------
    # PINECONE_INDEX_NAME: Which Pinecone index to use
    # - Must be created before running pipeline
    # - Dimension must match embedding model (1536)
    # - Metric must be 'cosine' for text similarity
    #
    # PINECONE_NAMESPACE: Logical partition within index
    # - Allows multiple datasets in same index
    # - Queries can filter by namespace
    # - Example: namespace='clinical-trials' vs namespace='research-papers'
    # ------------------------------------------------------------------------
    PINECONE_INDEX_NAME: str = os.getenv('PINECONE_INDEX_NAME', 'documents')
    PINECONE_NAMESPACE: str = os.getenv('PINECONE_NAMESPACE', 'default')
    PINECONE_METRIC: str = 'cosine'

    # ========================================================================
    # CHUNKING PARAMETERS
    # ========================================================================
    # How to split documents into chunks for RAG
    # ========================================================================

    # ------------------------------------------------------------------------
    # Chunk Size Strategy
    # ------------------------------------------------------------------------
    # Why chunk at all?
    # - LLMs have context limits (can't process entire PDF)
    # - Embeddings work best on focused text (not entire documents)
    # - RAG retrieves relevant chunks (not entire documents)
    #
    # CHUNK_TARGET_SIZE: 1500 characters
    # - Why 1500? ~375 tokens (~300 words)
    # - Sweet spot: Enough context, not too much noise
    # - GPT-4 context: 128K tokens, but chunks should be smaller
    #
    # CHUNK_MIN_SIZE: 800 characters
    # - Prevents tiny chunks (not useful for search)
    # - Example: Single sentence isn't enough context
    #
    # CHUNK_MAX_SIZE: 3000 characters
    # - Hard limit to prevent oversized chunks
    # - ~750 tokens (~600 words)
    #
    # CHUNK_OVERLAP: 200 characters
    # - Prevents losing context at boundaries
    # - Example: "...important fact. New paragraph..."
    #   → Both chunks get "important fact"
    # ------------------------------------------------------------------------
    CHUNK_TARGET_SIZE: int = 1500  # characters (~375 tokens)
    CHUNK_MIN_SIZE: int = 800  # minimum viable chunk
    CHUNK_MAX_SIZE: int = 3000  # hard limit
    CHUNK_OVERLAP: int = 200  # overlap between chunks

    # ========================================================================
    # LOGGING
    # ========================================================================

    # CloudFormation sets: LOG_LEVEL
    # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
    #
    # Development: DEBUG (see everything)
    # Production: INFO (high-level progress)
    # Troubleshooting: DEBUG (detailed tracing)
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    # ========================================================================
    # VALIDATION
    # ========================================================================
    # Check that all required configuration is present before starting
    # ========================================================================

    @classmethod
    def validate(cls) -> bool:
        """
        Validate that all required configuration is present.

        This is called at startup (before processing any documents) to ensure
        the application has everything it needs.

        Fail-fast principle: Better to crash immediately with clear error
        than fail mysteriously 10 minutes into processing.

        Returns:
            True if all required config present, False otherwise

        Example:
        --------
        from config import config

        if not config.validate():
            print("Missing configuration!")
            sys.exit(1)

        # Safe to proceed
        start_pipeline()
        """
        errors = []

        # ====================================================================
        # Check AWS Resources
        # ====================================================================
        if not cls.S3_BUCKET:
            errors.append("❌ S3_BUCKET environment variable not set")
            errors.append("   CloudFormation should set this!")

        if not cls.DYNAMODB_CONTROL_TABLE:
            errors.append("❌ DYNAMODB_CONTROL_TABLE environment variable not set")
            errors.append("   CloudFormation should set this!")

        if not cls.DYNAMODB_AUDIT_TABLE:
            errors.append("❌ DYNAMODB_AUDIT_TABLE environment variable not set")
            errors.append("   CloudFormation should set this!")

        # ====================================================================
        # Check API Keys
        # ====================================================================
        if not cls.OPENAI_API_KEY:
            errors.append("❌ OPENAI_API_KEY environment variable not set")
            errors.append("   Check AWS Secrets Manager!")

        if not cls.PINECONE_API_KEY:
            errors.append("❌ PINECONE_API_KEY environment variable not set")
            errors.append("   Check AWS Secrets Manager!")

        # ====================================================================
        # Print Results
        # ====================================================================
        if errors:
            print("\n" + "=" * 70)
            print("CONFIGURATION VALIDATION FAILED")
            print("=" * 70)
            for error in errors:
                print(error)
            print("=" * 70 + "\n")
            return False

        print("\n" + "=" * 70)
        print("✅ CONFIGURATION VALIDATED SUCCESSFULLY")
        print("=" * 70 + "\n")
        return True

    @classmethod
    def print_config(cls):
        """
        Print configuration (masking sensitive values).

        Useful for debugging and confirming settings at startup.
        API keys are masked for security.
        """
        print("\n" + "=" * 70)
        print("PIPELINE CONFIGURATION")
        print("=" * 70)
        print(f"AWS Region:          {cls.AWS_REGION}")
        print(f"S3 Bucket:           {cls.S3_BUCKET}")
        print(f"Control Table:       {cls.DYNAMODB_CONTROL_TABLE}")
        print(f"Audit Table:         {cls.DYNAMODB_AUDIT_TABLE}")
        print(f"Metrics Table:       {cls.DYNAMODB_METRICS_TABLE}")
        print(f"Ray Address:         {cls.RAY_ADDRESS}")
        print(f"Ray Namespace:       {cls.RAY_NAMESPACE}")
        print(f"OpenAI API Key:      {'*' * 20 if cls.OPENAI_API_KEY else 'NOT SET'}")
        print(f"Pinecone API Key:    {'*' * 20 if cls.PINECONE_API_KEY else 'NOT SET'}")
        print(f"Polling Interval:    {cls.POLLING_INTERVAL}s")
        print(f"Max Docs Per Poll:   {cls.MAX_DOCUMENTS_PER_POLL}")
        print(f"Processing Version:  {cls.PROCESSING_VERSION}")
        print(f"Log Level:           {cls.LOG_LEVEL}")
        print("=" * 70 + "\n")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================
# Create single instance that all modules import
# This is the "Singleton Pattern" in Python
# ============================================================================
config = PipelineConfig()

# ============================================================================
# SUMMARY FOR STUDENTS
# ============================================================================
#
# This file demonstrates several important patterns:
#
# 1. 12-FACTOR APP
#    - All config from environment variables
#    - No hardcoded values (especially secrets!)
#    - Easy to change between dev/staging/prod
#
# 2. SINGLETON PATTERN
#    - One config instance for entire application
#    - No need to pass config object around
#    - Import once, use everywhere
#
# 3. FAIL-FAST VALIDATION
#    - validate() checks config at startup
#    - Better to crash immediately than mysteriously later
#    - Clear error messages guide debugging
#
# 4. TYPE SAFETY
#    - Type hints for all attributes
#    - IDEs can autocomplete
#    - Catches bugs at development time
#
# 5. SEPARATION OF CONCERNS
#    - Configuration separate from business logic
#    - Change config without changing code
#    - Easy to test (mock config values)
#
# Questions for Students:
#
# 1. Why use environment variables instead of a config file?
#    → Security (no secrets in code), flexibility (same code, different config)
#
# 2. Why validate configuration at startup?
#    → Fail-fast principle, clear errors, don't waste time processing
#
# 3. Why mask API keys in print_config()?
#    → Security, logs might be visible to others
#
# 4. Why use class variables instead of instance variables?
#    → Singleton pattern, one config for all, thread-safe
#
# 5. What happens if OPENAI_API_KEY is missing?
#    → validate() returns False, application exits, clear error message
#
# ============================================================================