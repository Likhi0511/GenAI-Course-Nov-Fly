"""
utils.py - Helper Utilities for Ray Document Processing Pipeline

================================================================================
                        UTILITY FUNCTIONS & HELPERS
================================================================================

This file contains the "toolbox" for our pipeline - reusable utilities that
make our code cleaner and more maintainable.

Think of it like a toolkit:
- S3Helper: Your "file transfer tool" (upload/download to S3)
- LocalFileManager: Your "workspace organizer" (temp folders)
- Helper functions: Your "measuring tools" (time, timestamps, logging)

Why create utilities?
✓ DRY Principle (Don't Repeat Yourself)
✓ Centralized error handling
✓ Easier testing (mock these instead of AWS SDK)
✓ Consistent behavior across all stages
✓ Clear interface (what vs how)

Example Without Utils (ugly!):
```python
# Scattered throughout code - error prone!
import boto3
s3 = boto3.client('s3')
s3.upload_file('/tmp/file.pdf', 'my-bucket', 'input/file.pdf')
# No error handling, no logging, repeated everywhere!
```

Example With Utils (clean!):
```python
from utils import S3Helper
s3_helper = S3Helper(bucket='my-bucket')
s3_helper.upload_file('/tmp/file.pdf', 'input/file.pdf')
# Error handling built-in, logging automatic!
```

Author: Prudhvi | Thoughtworks
"""

import boto3  # AWS SDK for Python
import logging
import os
import shutil  # For directory operations (copy, delete)
from pathlib import Path  # Modern way to handle file paths
from datetime import datetime


logger = logging.getLogger(__name__)


# ============================================================================
# S3 HELPER CLASS
# ============================================================================
# This class wraps all S3 operations we need in the pipeline
# Think of it as a "file transfer manager" for AWS S3
# ============================================================================

class S3Helper:
    """
    S3 upload/download operations wrapper.

    This class provides a clean interface to AWS S3, hiding the complexity
    of the boto3 SDK and adding error handling, logging, and retries.

    Why wrap S3 operations?
    ✓ Consistent error handling (all methods return True/False)
    ✓ Automatic logging (know what's happening)
    ✓ Directory operations (upload/download entire folders)
    ✓ Easy to mock for testing (no need for real S3)
    ✓ Single place to add features (compression, encryption, etc.)

    Common Use Cases:
    1. Download PDF from S3 (Stage 1)
    2. Upload extraction results to S3 (Stage 1)
    3. Download chunks from S3 (Stage 3)
    4. Upload embeddings to S3 (Stage 4)

    Example Usage:
    ```python
    # Initialize once per task
    s3_helper = S3Helper(bucket='my-pipeline-bucket')

    # Download a file
    success = s3_helper.download_file(
        s3_key='input/trial.pdf',
        local_path='/tmp/trial.pdf'
    )

    # Upload a file
    success = s3_helper.upload_file(
        local_path='/tmp/chunks.json',
        s3_key='chunks/doc_123_chunks.json'
    )

    # Upload entire directory
    success = s3_helper.upload_directory(
        local_dir='/tmp/extracted',
        s3_prefix='extracted/doc_123'
    )
    ```

    Error Handling Pattern:
    All methods return boolean (True/False) instead of raising exceptions.
    This makes it easy to check if operation succeeded:

    ```python
    if not s3_helper.download_file(key, path):
        logger.error("Download failed!")
        return {'status': 'FAILED'}
    # Continue processing...
    ```
    """

    def __init__(self, bucket: str, region: str = 'us-east-1'):
        """
        Initialize S3 helper.

        Args:
            bucket: S3 bucket name (e.g., 'ray-ingestion-prudhvi-2026')
            region: AWS region (e.g., 'us-east-1', 'eu-west-1')

        Why store bucket and region?
        - Bucket: We always use the same bucket per pipeline
        - Region: Ensures we connect to the right AWS region

        Why not create client each time?
        - Connection pooling (reuse HTTP connections)
        - Faster (no setup overhead on each call)
        - Less resource usage
        """
        self.bucket = bucket
        # Create S3 client once and reuse it
        # This maintains a connection pool for efficiency
        self.s3 = boto3.client('s3', region_name=region)

    def download_file(self, s3_key: str, local_path: str) -> bool:
        """
        Download a single file from S3 to local disk.

        This is like "copy from S3 to your computer"

        Flow:
        1. Create parent directories if needed
        2. Download file from S3
        3. Log success/failure
        4. Return True/False

        Args:
            s3_key: S3 object key (path in bucket)
                Example: 'input/NCT04368728_Remdesivir_COVID.pdf'
            local_path: Where to save on local disk
                Example: '/tmp/doc_123/input.pdf'

        Returns:
            bool: True if successful, False if failed

        Example Usage:
        ```python
        # Download PDF for processing
        success = s3_helper.download_file(
            s3_key='input/trial.pdf',
            local_path='/tmp/workspace/input.pdf'
        )

        if not success:
            print("Download failed!")
            return

        # File is now available at /tmp/workspace/input.pdf
        with open('/tmp/workspace/input.pdf', 'rb') as f:
            process_pdf(f)
        ```

        Error Cases:
        - S3 key doesn't exist → logs error, returns False
        - No permission to read → logs error, returns False
        - Network error → logs error, returns False
        - Disk full → logs error, returns False

        Why create parent directories?
        If local_path = '/tmp/a/b/c/file.pdf' but '/tmp/a/b/c/' doesn't exist,
        the download would fail. We create it automatically for convenience.
        """
        try:
            # ================================================================
            # STEP 1: Create Parent Directories
            # ================================================================
            # Ensure the directory exists before trying to save the file
            # Example: local_path = '/tmp/doc_123/extracted/pages/page_1.md'
            #          creates:     '/tmp/doc_123/extracted/pages/'
            #
            # exist_ok=True means "don't error if already exists"
            # ================================================================
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # ================================================================
            # STEP 2: Download from S3
            # ================================================================
            # boto3's download_file handles:
            # - Chunked downloads (for large files)
            # - Retries (if network hiccups)
            # - Progress tracking (internal)
            #
            # This is a BLOCKING call - waits until download completes
            # ================================================================
            self.s3.download_file(self.bucket, s3_key, local_path)

            # ================================================================
            # STEP 3: Log Success
            # ================================================================
            # Log for debugging and monitoring
            # Shows exact S3 source and local destination
            # ================================================================
            logger.info(f"Downloaded s3://{self.bucket}/{s3_key} → {local_path}")

            return True

        except Exception as e:
            # ================================================================
            # ERROR HANDLING
            # ================================================================
            # Something went wrong! Common causes:
            # - S3 key doesn't exist (NoSuchKey error)
            # - No read permission (AccessDenied error)
            # - Network timeout (RequestTimeout error)
            # - Disk full (OSError)
            #
            # We log the error but don't raise exception
            # This lets calling code decide how to handle failure
            # ================================================================
            logger.error(f"Failed to download {s3_key}: {e}")
            return False

    def upload_file(self, local_path: str, s3_key: str) -> bool:
        """
        Upload a single file from local disk to S3.

        This is like "copy from your computer to S3"

        Flow:
        1. Upload file to S3
        2. Log success/failure
        3. Return True/False

        Args:
            local_path: Path to file on local disk
                Example: '/tmp/doc_123/chunks.json'
            s3_key: Where to save in S3 bucket
                Example: 'chunks/doc_123_chunks.json'

        Returns:
            bool: True if successful, False if failed

        Full S3 URI: s3://{bucket}/{s3_key}
        Example: s3://ray-ingestion-prudhvi-2026/chunks/doc_123_chunks.json

        Example Usage:
        ```python
        # Create a file locally
        with open('/tmp/chunks.json', 'w') as f:
            json.dump(chunks, f)

        # Upload to S3
        success = s3_helper.upload_file(
            local_path='/tmp/chunks.json',
            s3_key='chunks/doc_123_chunks.json'
        )

        if success:
            print("File available at s3://bucket/chunks/doc_123_chunks.json")
        ```

        Error Cases:
        - File doesn't exist locally → logs error, returns False
        - No permission to write to S3 → logs error, returns False
        - Network error → logs error, returns False
        - Bucket doesn't exist → logs error, returns False

        Performance Notes:
        - boto3 automatically uses multipart upload for files >5MB
        - Chunked uploads (efficient for large files)
        - Automatic retries on transient errors
        """
        try:
            # ================================================================
            # STEP 1: Upload to S3
            # ================================================================
            # boto3's upload_file handles:
            # - Multipart upload (for files >5MB)
            # - Retries (if network issues)
            # - Checksums (verifies integrity)
            #
            # This is a BLOCKING call - waits until upload completes
            # ================================================================
            self.s3.upload_file(local_path, self.bucket, s3_key)

            # ================================================================
            # STEP 2: Log Success
            # ================================================================
            logger.info(f"Uploaded {local_path} → s3://{self.bucket}/{s3_key}")

            return True

        except Exception as e:
            # ================================================================
            # ERROR HANDLING
            # ================================================================
            # Common errors:
            # - File not found (FileNotFoundError)
            # - No write permission (AccessDenied)
            # - Network timeout (RequestTimeout)
            # - Invalid bucket name (NoSuchBucket)
            # ================================================================
            logger.error(f"Failed to upload {local_path}: {e}")
            return False

    def upload_directory(self, local_dir: str, s3_prefix: str) -> bool:
        """
        Upload entire directory tree to S3.

        This is like "copy folder from your computer to S3"
        Preserves directory structure!

        Flow:
        1. Walk through all files in directory (recursively)
        2. For each file, calculate relative path
        3. Upload to S3 with preserved structure
        4. Return True if all succeeded, False if any failed

        Args:
            local_dir: Root directory on local disk
                Example: '/tmp/doc_123/extracted'
            s3_prefix: Root prefix in S3
                Example: 'extracted/doc_123'

        Returns:
            bool: True if successful, False if any file failed

        Example Structure:
        Local:
        /tmp/doc_123/extracted/
        ├── pages/
        │   ├── page_1.md
        │   └── page_2.md
        ├── figures/
        │   └── fig_p1_0.png
        └── metadata.json

        S3 Result:
        s3://bucket/extracted/doc_123/
        ├── pages/
        │   ├── page_1.md
        │   └── page_2.md
        ├── figures/
        │   └── fig_p1_0.png
        └── metadata.json

        Example Usage:
        ```python
        # After Docling extraction, we have:
        # /tmp/doc_123/extracted/
        #   ├── pages/page_1.md
        #   ├── figures/fig_1.png
        #   └── metadata.json

        # Upload entire directory
        success = s3_helper.upload_directory(
            local_dir='/tmp/doc_123/extracted',
            s3_prefix='extracted/doc_123'
        )

        # Now available in S3:
        # s3://bucket/extracted/doc_123/pages/page_1.md
        # s3://bucket/extracted/doc_123/figures/fig_1.png
        # s3://bucket/extracted/doc_123/metadata.json
        ```

        Why preserve structure?
        - Stage 2 expects specific paths (pages/*.md)
        - Easier debugging (same structure everywhere)
        - Reproducible (re-run stage with same inputs)
        """
        try:
            # ================================================================
            # WALK THROUGH DIRECTORY TREE
            # ================================================================
            # os.walk() recursively traverses directory
            # For each directory, yields: (root_path, directories, files)
            #
            # Example with /tmp/extracted/:
            # Iteration 1: ('/tmp/extracted', ['pages', 'figures'], ['metadata.json'])
            # Iteration 2: ('/tmp/extracted/pages', [], ['page_1.md', 'page_2.md'])
            # Iteration 3: ('/tmp/extracted/figures', [], ['fig_1.png'])
            # ================================================================
            for root, _, files in os.walk(local_dir):
                for file in files:
                    # ========================================================
                    # STEP 1: Build Full Local Path
                    # ========================================================
                    # Join directory + filename
                    # Example: root='/tmp/extracted/pages', file='page_1.md'
                    # Result:  '/tmp/extracted/pages/page_1.md'
                    # ========================================================
                    local_path = os.path.join(root, file)

                    # ========================================================
                    # STEP 2: Calculate Relative Path
                    # ========================================================
                    # Get path relative to base directory
                    # Example:
                    #   local_path = '/tmp/extracted/pages/page_1.md'
                    #   local_dir = '/tmp/extracted'
                    #   relative_path = 'pages/page_1.md'
                    #
                    # This preserves directory structure in S3!
                    # ========================================================
                    relative_path = os.path.relpath(local_path, local_dir)

                    # ========================================================
                    # STEP 3: Upload File
                    # ========================================================
                    # Combine S3 prefix with relative path
                    # Example:
                    #   s3_prefix = 'extracted/doc_123'
                    #   relative_path = 'pages/page_1.md'
                    #   s3_key = 'extracted/doc_123/pages/page_1.md'
                    # ========================================================
                    self.upload_file(local_path, f"{s3_prefix}/{relative_path}")

            # ================================================================
            # LOG COMPLETION
            # ================================================================
            # Log overall success (individual files already logged)
            # ================================================================
            logger.info(f"Uploaded {local_dir} → s3://{self.bucket}/{s3_prefix}")

            return True

        except Exception as e:
            # ================================================================
            # ERROR HANDLING
            # ================================================================
            # Errors here are usually:
            # - Directory doesn't exist (FileNotFoundError)
            # - Permission denied reading files (PermissionError)
            # - Any error from upload_file() bubbles up
            # ================================================================
            logger.error(f"Failed to upload directory {local_dir}: {e}")
            return False

    def download_directory(self, s3_prefix: str, local_dir: str) -> bool:
        """
        Download entire S3 prefix (folder) to local disk.

        This is like "copy folder from S3 to your computer"
        Preserves directory structure!

        Flow:
        1. List all objects with given prefix (paginated)
        2. For each object, calculate local path
        3. Download to local disk with preserved structure
        4. Return True if all succeeded, False if any failed

        Args:
            s3_prefix: Prefix in S3 bucket (like a folder)
                Example: 'extracted/doc_123'
            local_dir: Where to save on local disk
                Example: '/tmp/doc_123/extracted'

        Returns:
            bool: True if successful, False if any file failed

        Example Structure:
        S3:
        s3://bucket/extracted/doc_123/
        ├── pages/
        │   ├── page_1.md
        │   └── page_2.md
        └── metadata.json

        Local Result:
        /tmp/doc_123/extracted/
        ├── pages/
        │   ├── page_1.md
        │   └── page_2.md
        └── metadata.json

        Example Usage:
        ```python
        # Download extracted pages for chunking
        success = s3_helper.download_directory(
            s3_prefix='extracted/doc_123/pages',
            local_dir='/tmp/doc_123/pages'
        )

        # Now we have locally:
        # /tmp/doc_123/pages/page_1.md
        # /tmp/doc_123/pages/page_2.md
        # etc.
        ```

        Why use pagination?
        S3 list_objects_v2 returns max 1000 objects per call.
        For directories with >1000 files, we need multiple calls.
        Pagination handles this automatically!

        Performance Notes:
        - Downloads happen sequentially (one at a time)
        - For parallel downloads, use concurrent.futures
        - Good for our use case (small number of files per document)
        """
        try:
            # ================================================================
            # STEP 1: Create Local Directory
            # ================================================================
            # Ensure destination directory exists
            # parents=True creates parent directories if needed
            # exist_ok=True doesn't error if directory exists
            # ================================================================
            Path(local_dir).mkdir(parents=True, exist_ok=True)

            # ================================================================
            # STEP 2: List All Objects with Prefix
            # ================================================================
            # S3 doesn't have true folders - just object keys with /
            # We list all objects whose key starts with s3_prefix
            #
            # Pagination:
            # S3 returns max 1000 objects per call
            # Paginator automatically makes multiple calls if needed
            #
            # Example:
            # Prefix: 'extracted/doc_123'
            # Returns:
            #   - extracted/doc_123/pages/page_1.md
            #   - extracted/doc_123/pages/page_2.md
            #   - extracted/doc_123/metadata.json
            # ================================================================
            paginator = self.s3.get_paginator('list_objects_v2')

            # Iterate through all pages of results
            for page in paginator.paginate(Bucket=self.bucket, Prefix=s3_prefix):
                # Get objects from this page (may be empty)
                for obj in page.get('Contents', []):
                    s3_key = obj['Key']

                    # ========================================================
                    # SKIP DIRECTORY MARKERS
                    # ========================================================
                    # S3 sometimes has "folder" markers (keys ending with /)
                    # These aren't real files, skip them
                    # Example: 'extracted/doc_123/pages/' ← skip this
                    # ========================================================
                    if s3_key.endswith('/'):
                        continue

                    # ========================================================
                    # CALCULATE LOCAL PATH
                    # ========================================================
                    # Remove prefix to get relative path
                    # Example:
                    #   s3_key = 'extracted/doc_123/pages/page_1.md'
                    #   s3_prefix = 'extracted/doc_123'
                    #   relative_path = 'pages/page_1.md'
                    #   local_path = '/tmp/extracted/pages/page_1.md'
                    # ========================================================
                    relative_path = s3_key[len(s3_prefix):].lstrip('/')
                    local_path = os.path.join(local_dir, relative_path)

                    # ========================================================
                    # DOWNLOAD FILE
                    # ========================================================
                    # Download this object to calculated local path
                    # download_file() handles directory creation
                    # ========================================================
                    self.download_file(s3_key, local_path)

            # ================================================================
            # LOG COMPLETION
            # ================================================================
            logger.info(f"Downloaded s3://{self.bucket}/{s3_prefix} → {local_dir}")

            return True

        except Exception as e:
            # ================================================================
            # ERROR HANDLING
            # ================================================================
            # Common errors:
            # - Prefix doesn't exist (no error, just empty results)
            # - No read permission (AccessDenied)
            # - Network timeout (RequestTimeout)
            # ================================================================
            logger.error(f"Failed to download directory {s3_prefix}: {e}")
            return False


# ============================================================================
# LOCAL FILE MANAGER CLASS
# ============================================================================
# This class manages temporary workspaces for document processing
# Think of it as a "workspace organizer" that creates and cleans up folders
# ============================================================================

class LocalFileManager:
    """
    Manages temporary local workspaces during processing.

    Why do we need temporary workspaces?
    - Each document needs isolated workspace (no file collisions)
    - Stages create intermediate files (pages, chunks, etc.)
    - Must clean up after processing (prevent disk from filling)

    Workspace Structure:
    /tmp/ray_pipeline/           ← Base directory
    ├── doc_20240222_143025_a1b2c3d4/  ← Document workspace
    │   ├── input.pdf
    │   ├── extracted/
    │   ├── chunks.json
    │   └── enriched.json
    ├── doc_20240222_143026_b2c3d4e5/  ← Another document
    │   └── ...
    └── doc_20240222_143027_c3d4e5f6/  ← Yet another
        └── ...

    Lifecycle:
    1. create_document_workspace() → Creates folder
    2. Stage processes files in folder
    3. cleanup_document_workspace() → Deletes folder

    Why /tmp?
    - Automatically cleared on reboot (no disk buildup)
    - Fast (often tmpfs = RAM disk)
    - Standard location for temporary files

    Example Usage:
    ```python
    file_mgr = LocalFileManager()

    # Create workspace
    workspace = file_mgr.create_document_workspace('doc_123')
    # Returns: Path('/tmp/ray_pipeline/doc_123')

    # Use workspace
    pdf_path = workspace / 'input.pdf'
    chunks_path = workspace / 'chunks.json'

    # Clean up when done
    file_mgr.cleanup_document_workspace('doc_123')
    # Deletes: /tmp/ray_pipeline/doc_123/
    ```
    """

    def __init__(self, base_dir: str = '/tmp/ray_pipeline'):
        """
        Initialize file manager.

        Args:
            base_dir: Root directory for all workspaces
                Default: '/tmp/ray_pipeline'
                Can override for testing: LocalFileManager('/tmp/test')

        Why configurable base_dir?
        - Testing: Use different path for tests
        - Multi-tenant: Different base per user
        - Development: Use project folder instead of /tmp
        """
        self.base_dir = Path(base_dir)

        # Create base directory if it doesn't exist
        # This runs once when LocalFileManager is instantiated
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_document_workspace(self, document_id: str) -> Path:
        """
        Create a temporary workspace for a document.

        This creates an isolated folder for processing one document.
        All intermediate files go here.

        Args:
            document_id: Unique document identifier
                Example: 'doc_20240222_143025_a1b2c3d4'

        Returns:
            Path: Path object for the workspace directory
                Example: Path('/tmp/ray_pipeline/doc_20240222_143025_a1b2c3d4')

        Why return Path object?
        Path objects are better than strings:
        - Modern Python (pathlib)
        - Cross-platform (works on Windows/Linux/Mac)
        - Convenient operators (workspace / 'input.pdf')
        - Built-in methods (exists(), mkdir(), etc.)

        Example Usage:
        ```python
        # Create workspace
        workspace = file_mgr.create_document_workspace('doc_123')

        # Build paths using / operator (clean!)
        pdf_path = workspace / 'input.pdf'
        extracted_dir = workspace / 'extracted'
        chunks_file = workspace / 'chunks.json'

        # Use paths
        with open(pdf_path, 'rb') as f:
            process_pdf(f)
        ```

        Idempotent:
        Calling this multiple times for same document_id is safe.
        If folder exists, it's reused (no error).
        """
        # ====================================================================
        # CREATE WORKSPACE DIRECTORY
        # ====================================================================
        # Combine base directory with document ID
        # Example: Path('/tmp/ray_pipeline') / 'doc_123'
        #       = Path('/tmp/ray_pipeline/doc_123')
        #
        # parents=True: Create parent directories if needed
        # exist_ok=True: Don't error if directory already exists
        # ====================================================================
        workspace = self.base_dir / document_id
        workspace.mkdir(parents=True, exist_ok=True)

        return workspace

    def cleanup_document_workspace(self, document_id: str):
        """
        Delete a document's workspace and all its contents.

        This is CRITICAL for preventing disk from filling up!
        Always call this in a finally block to ensure cleanup.

        Args:
            document_id: Document identifier whose workspace to delete

        What gets deleted:
        - The workspace directory
        - ALL files inside it (recursive)
        - ALL subdirectories inside it (recursive)

        Safety:
        - Only deletes if workspace exists (no error if missing)
        - Logs confirmation of cleanup
        - Can't delete files outside base_dir (safe)

        Example Usage:
        ```python
        workspace = file_mgr.create_document_workspace('doc_123')

        try:
            # Process document (may create many files)
            process_document(workspace)
        finally:
            # ALWAYS clean up, even if processing fails
            file_mgr.cleanup_document_workspace('doc_123')
            # Disk space is now free!
        ```

        Why in finally block?
        - Runs even if exception occurs
        - Prevents disk space leaks
        - Ensures cleanup even after errors

        Disk Space Impact:
        Without cleanup:
        - Process 100 docs → 100 × 50MB = 5GB wasted
        - Eventually disk fills → pipeline stops

        With cleanup:
        - Process 100 docs → only current doc (50MB) kept
        - Disk usage stays constant
        """
        # ====================================================================
        # BUILD WORKSPACE PATH
        # ====================================================================
        workspace = self.base_dir / document_id

        # ====================================================================
        # DELETE IF EXISTS
        # ====================================================================
        # Check if workspace exists before trying to delete
        # exists() prevents error if already cleaned up
        # ====================================================================
        if workspace.exists():
            # ================================================================
            # RECURSIVE DELETE
            # ================================================================
            # shutil.rmtree() recursively deletes directory and all contents
            # Equivalent to: rm -rf /tmp/ray_pipeline/doc_123/
            #
            # This deletes:
            # - All files in workspace
            # - All subdirectories (and their files)
            # - The workspace directory itself
            # ================================================================
            shutil.rmtree(workspace)

            # Log confirmation
            logger.info(f"Cleaned up workspace for {document_id}")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
# Small utility functions used throughout the pipeline
# ============================================================================

def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.

    Converts seconds to appropriate unit (s, m, h) for readability.

    Args:
        seconds: Duration in seconds (can be float)

    Returns:
        str: Formatted duration string

    Examples:
        format_duration(15.3) → "15.3s"
        format_duration(125.0) → "2.1m"
        format_duration(7200.5) → "2.00h"

    Why this function?
    - Logs are more readable: "Completed in 2.5m" vs "Completed in 150s"
    - Consistent formatting across all stages
    - Automatic unit selection (don't think about it)

    Usage in Pipeline:
    ```python
    start = time.time()
    process_document()
    duration = time.time() - start

    logger.info(f"Completed in {format_duration(duration)}")
    # Output: "Completed in 2.3m" (more readable than "Completed in 138s")
    ```
    """
    if seconds < 60:
        # Less than 1 minute → show seconds
        # Example: 45.7s
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        # Less than 1 hour → show minutes
        # Example: 2.5m (150 seconds)
        return f"{seconds / 60:.1f}m"
    else:
        # 1 hour or more → show hours
        # Example: 1.50h (5400 seconds)
        return f"{seconds / 3600:.2f}h"


def get_timestamp() -> str:
    """
    Get current UTC timestamp in ISO 8601 format.

    Returns consistent timestamp format used throughout pipeline.

    Returns:
        str: ISO 8601 timestamp with 'Z' suffix
        Example: "2024-02-22T14:30:25.123456Z"

    Why UTC?
    - No timezone confusion (always absolute time)
    - Consistent across regions (works globally)
    - ISO 8601 standard (widely recognized)
    - Sortable (lexicographic sort = chronological sort)

    Why 'Z' suffix?
    - 'Z' means "Zulu time" = UTC
    - Common convention in APIs
    - DynamoDB recognizes this format
    - JavaScript Date() parses it correctly

    Example Usage:
    ```python
    # Record when stage started
    started_at = get_timestamp()
    # "2024-02-22T14:30:25.123456Z"

    # Process...

    # Record when stage completed
    completed_at = get_timestamp()
    # "2024-02-22T14:32:10.987654Z"

    # Store in DynamoDB
    db.update_item({
        'started_at': started_at,
        'completed_at': completed_at
    })
    ```

    Alternative Approaches (and why we don't use them):
    ✗ Unix timestamp (1708610425) - hard to read
    ✗ Local time - timezone confusion
    ✗ Custom format - not standard
    ✓ ISO 8601 UTC - standard, readable, sortable
    """
    # datetime.utcnow() gets current time in UTC
    # .isoformat() converts to ISO 8601 format
    # + 'Z' adds timezone indicator (Zulu = UTC)
    return datetime.utcnow().isoformat() + 'Z'


def setup_logging(level: str = 'INFO'):
    """
    Configure logging for the entire pipeline.

    This sets up consistent logging format and levels across all modules.
    Should be called once at program startup (in main()).

    Args:
        level: Logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
            Default: 'INFO'

    What this does:
    1. Sets global logging level
    2. Configures log format (timestamp, module, level, message)
    3. Suppresses noisy AWS SDK logs (boto3, botocore, urllib3)

    Log Levels Explained:
    - DEBUG: Everything (function calls, variable values)
      Example: "Downloading s3://bucket/key to /tmp/file"

    - INFO: High-level progress (default)
      Example: "Stage 1 completed in 45.2s"

    - WARNING: Potential issues
      Example: "Retry attempt 2/3 for chunk embedding"

    - ERROR: Actual problems
      Example: "Stage failed: OpenAI API timeout"

    - CRITICAL: System failures
      Example: "Cannot connect to Ray cluster"

    Log Format:
    "2024-02-22 14:30:25 - ray_tasks - INFO - Stage 1 completed"
     ↑ timestamp       ↑ module     ↑ level ↑ message

    Example Usage:
    ```python
    # At program startup (main())
    setup_logging(level='INFO')

    # Now all modules can log
    logger = logging.getLogger(__name__)
    logger.info("Pipeline started")
    logger.warning("Rate limit approaching")
    logger.error("Stage failed")
    ```

    Why suppress AWS SDK logs?
    boto3 and botocore are VERY chatty:
    - Log every HTTP request
    - Log retry attempts
    - Log response parsing
    - Creates huge log files!

    We only want to see our application logs, not AWS SDK internals.
    """
    # ========================================================================
    # CONFIGURE ROOT LOGGER
    # ========================================================================
    # basicConfig sets up logging for entire Python process
    # This affects all loggers (unless they override)
    # ========================================================================
    logging.basicConfig(
        # ====================================================================
        # LOG LEVEL
        # ====================================================================
        # Convert string ('INFO') to logging constant (logging.INFO)
        # getattr gets attribute from module by name
        # Example: getattr(logging, 'INFO') → logging.INFO
        # ====================================================================
        level=getattr(logging, level.upper()),

        # ====================================================================
        # LOG FORMAT
        # ====================================================================
        # Template for every log line
        # Variables available:
        # - %(asctime)s: Timestamp (formatted by datefmt)
        # - %(name)s: Logger name (usually module name)
        # - %(levelname)s: Log level (INFO, WARNING, ERROR, etc.)
        # - %(message)s: The actual log message
        #
        # Example output:
        # "2024-02-22 14:30:25 - ray_tasks - INFO - Processing document"
        # ====================================================================
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',

        # ====================================================================
        # TIMESTAMP FORMAT
        # ====================================================================
        # How to format %(asctime)s
        # YYYY-MM-DD HH:MM:SS format (human-readable)
        # ====================================================================
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # ========================================================================
    # SUPPRESS NOISY AWS SDK LOGS
    # ========================================================================
    # boto3, botocore, and urllib3 log TOO MUCH at INFO level
    # Set them to WARNING so we only see their problems, not routine ops
    #
    # Without this:
    # DEBUG:botocore.endpoint:Making request to s3
    # DEBUG:botocore.parsers:Response body:
    # DEBUG:urllib3.connectionpool:Starting new HTTPS connection
    # ... (hundreds of lines per S3 operation!)
    #
    # With this:
    # (silence - only warnings/errors from AWS SDK)
    # ========================================================================
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


# ============================================================================
# SUMMARY FOR STUDENTS
# ============================================================================
#
# This file demonstrates several important software engineering principles:
#
# 1. ABSTRACTION
#    - Hide AWS SDK complexity behind simple interface
#    - S3Helper provides upload/download without worrying about boto3
#
# 2. ERROR HANDLING
#    - All methods return True/False (easy to check)
#    - Exceptions are caught and logged (no crashes)
#    - Calling code decides how to handle failures
#
# 3. RESOURCE MANAGEMENT
#    - LocalFileManager creates temporary workspaces
#    - Always cleanup in finally block (prevent leaks)
#    - Disk space stays constant even after 1000s of documents
#
# 4. DRY PRINCIPLE (Don't Repeat Yourself)
#    - S3 operations defined once, used everywhere
#    - Logging format defined once (setup_logging)
#    - Timestamp format consistent (get_timestamp)
#
# 5. TESTABILITY
#    - Easy to mock S3Helper for tests (no real S3 needed)
#    - LocalFileManager can use test directory
#    - Each function has single responsibility (easy to test)
#
# Common Patterns Demonstrated:
#
# ✓ Wrapper Pattern (S3Helper wraps boto3)
# ✓ Builder Pattern (S3Helper.upload_directory builds paths)
# ✓ Singleton Pattern (one logging config)
# ✓ Resource Acquisition Is Initialization (RAII via finally)
# ✓ Defensive Programming (check exists before delete)
#
# Questions for Students:
#
# 1. Why return True/False instead of raising exceptions?
#    → Easier to use, calling code decides how to handle failure
#
# 2. Why use Path objects instead of strings?
#    → Modern, cross-platform, convenient operators
#
# 3. Why always cleanup in finally block?
#    → Runs even if exception occurs, prevents disk leaks
#
# 4. Why suppress boto3 logs?
#    → Too noisy, creates huge log files, hard to find our logs
#
# 5. Why use UTC timestamps?
#    → No timezone confusion, consistent globally, sortable
#
# =============================================================================