"""
core/logging.py — Logging Configuration & Time Helpers

Provides consistent logging setup and human-readable time formatting
used across all pipeline stages and orchestration.

Moved from: utils.py (helper functions section)

Usage:
    from core.logging import setup_logging, format_duration, get_timestamp

    setup_logging(level='INFO')

    start = time.time()
    process()
    print(f"Completed in {format_duration(time.time() - start)}")

    timestamp = get_timestamp()  # "2024-02-22T14:30:25.123456Z"

Author: Prudhvi | Thoughtworks
"""

import logging
from datetime import datetime


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
