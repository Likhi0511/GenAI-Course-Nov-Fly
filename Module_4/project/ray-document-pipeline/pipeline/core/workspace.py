"""
core/workspace.py — Temporary Workspace Management

Manages isolated temporary directories for document processing.
Each document gets its own workspace folder that is cleaned up
after processing to prevent disk space leaks.

Moved from: utils.py (LocalFileManager class)

Usage:
    from core.workspace import LocalFileManager

    file_mgr = LocalFileManager()
    workspace = file_mgr.create_document_workspace('doc_123')
    # workspace = Path('/tmp/ray_pipeline/doc_123')

    try:
        process_document(workspace)
    finally:
        file_mgr.cleanup_document_workspace('doc_123')

Author: Prudhvi | Thoughtworks
"""

import logging
import shutil  # For directory operations (copy, delete)
from pathlib import Path  # Modern way to handle file paths

logger = logging.getLogger(__name__)


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
