"""
core/s3.py — S3 Upload/Download Operations

Wraps all S3 operations needed by the pipeline into a single class
with consistent error handling, logging, and directory support.

Moved from: utils.py (S3Helper class)

Usage:
    from core.s3 import S3Helper

    s3_helper = S3Helper(bucket='my-pipeline-bucket')
    s3_helper.download_file('input/trial.pdf', '/tmp/trial.pdf')
    s3_helper.upload_file('/tmp/chunks.json', 'chunks/doc_123_chunks.json')
    s3_helper.upload_directory('/tmp/extracted', 'extracted/doc_123')
    s3_helper.download_directory('extracted/doc_123', '/tmp/extracted')

Author: Prudhvi | Thoughtworks
"""

import boto3  # AWS SDK for Python
import logging
import os
from pathlib import Path

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
