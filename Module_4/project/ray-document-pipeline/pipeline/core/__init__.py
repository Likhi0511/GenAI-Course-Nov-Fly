"""
core — Shared infrastructure for the Ray Document Processing Pipeline.

Provides reusable components imported by stages/ and orchestration/:
  - PipelineConfig  : All env vars, resource limits, S3 prefixes
  - S3Helper        : Upload/download file & directory to/from S3
  - LocalFileManager: Temp workspace create/cleanup
  - Encoding utils  : sanitize_for_transport, read_json_robust, write_json_utf8
  - Logging utils   : setup_logging, format_duration, get_timestamp

Usage:
    from core.config    import config
    from core.s3        import S3Helper
    from core.workspace import LocalFileManager
    from core.encoding  import sanitize_for_transport, read_json_robust, write_json_utf8
    from core.logging   import setup_logging, format_duration, get_timestamp

Author: Prudhvi | Thoughtworks
"""

from core.config    import config, PipelineConfig
from core.s3        import S3Helper
from core.workspace import LocalFileManager
from core.encoding  import (
    sanitize_for_transport,
    sanitize_metadata,
    patch_urllib3_latin1,
    read_json_robust,
    write_json_utf8,
)
from core.logging   import setup_logging, format_duration, get_timestamp

__all__ = [
    "config",
    "PipelineConfig",
    "S3Helper",
    "LocalFileManager",
    "sanitize_for_transport",
    "sanitize_metadata",
    "patch_urllib3_latin1",
    "read_json_robust",
    "write_json_utf8",
    "setup_logging",
    "format_duration",
    "get_timestamp",
]
