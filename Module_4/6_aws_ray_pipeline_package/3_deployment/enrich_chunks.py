"""
================================================================================
CHUNK ENRICHMENT PIPELINE - EXTENSIVELY COMMENTED VERSION
================================================================================

This script:
1. Reads chunked document (JSON output from semantic chunker)
2. Enriches each chunk with metadata (AWS Comprehend + custom patterns)
3. Saves enriched chunks to new JSON file

WHAT THIS SCRIPT DOES:
──────────────────────

    Input: chunks_output.json
           ↓
    [Load & Validate]
           ↓
    [Enrich with Metadata]
           ↓
    [Save to New File]
           ↓
    Output: chunks_output_enriched_metadata.json

USAGE:
──────
    # Command line (simplest)
    python enrich_chunks.py chunks_output.json

    # Programmatic
    from enrich_chunks import ChunkEnrichmentPipeline
    pipeline = ChunkEnrichmentPipeline()
    pipeline.process('chunks_output.json')

Author: Prudhvi
Created: 2025-01-05
Version: 1.0.0 (Educational)
"""

# ============================================================================
# IMPORTS - External Dependencies
# ============================================================================

# JSON handling
# Used to: Read input file, write output file, parse/serialize data
import json

# Operating system interface
# Used to: Check file existence, create directories, get file sizes
import os

# System-specific parameters
# Used to: Command-line argument parsing (though not directly here)
import sys

# Object-oriented filesystem paths
# Used to: Parse filenames, extract stems, construct paths
# Example: Path('file.json').stem → 'file' (without extension)
from pathlib import Path

# Type hints for better code documentation
# Dict = dictionary type
# List = list type
# Optional = can be None
from typing import Dict, List, Optional

# Logging framework
# Used to: Track progress, log errors, debug issues
import logging

# Date and time utilities
# Used to: Timestamp when enrichment was performed
from datetime import datetime

# Import our custom metadata enricher
# This is the core enrichment engine that calls AWS Comprehend
# and extracts patterns
from metadata_enricher import MetadataEnricher


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Configure logging for this module
#
# Why logging instead of print()?
# - Timestamps: Know when each event occurred
# - Levels: INFO (normal), WARNING (issues), ERROR (failures)
# - Formatting: Consistent output structure
# - Production-ready: Can redirect to files, external services
#
# Format breakdown:
#   %(asctime)s      → 2025-01-05 10:30:15
#   %(levelname)s    → INFO, WARNING, ERROR
#   %(message)s      → Your log message
#
# Example output:
#   2025-01-05 10:30:15 | INFO | Loading chunks from: chunks_output.json
logging.basicConfig(
    level=logging.INFO,  # Only show INFO and above (not DEBUG)
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create logger instance for this module
# __name__ will be 'enrich_chunks' when imported
# This helps identify which module produced each log message
logger = logging.getLogger(__name__)


# ============================================================================
# CHUNK ENRICHMENT PIPELINE CLASS
# ============================================================================

class ChunkEnrichmentPipeline:
    """
    End-to-end pipeline for enriching chunked documents.

    ARCHITECTURE:
    ─────────────

    This class orchestrates the entire enrichment process:

    1. INITIALIZATION (__init__)
       - Set up AWS Comprehend connection
       - Configure enrichment parameters
       - Initialize MetadataEnricher

    2. LOADING (load_chunks)
       - Read JSON file
       - Extract chunks array
       - Validate file format

    3. VALIDATION (validate_chunk)
       - Check required fields exist
       - Ensure content_only is not empty
       - Log warnings for invalid chunks

    4. ENRICHMENT (enrich_chunks)
       - Iterate through all chunks
       - Call MetadataEnricher for each
       - Track progress with logging
       - Handle errors gracefully

    5. SAVING (save_enriched_chunks)
       - Build output structure
       - Add metadata and statistics
       - Write to JSON file
       - Report file size

    6. ORCHESTRATION (process)
       - Execute steps 2-5 in sequence
       - Handle overall errors
       - Print final statistics

    WHY A CLASS?
    ────────────
    - Encapsulation: All related functionality together
    - State management: Store configuration (region, thresholds)
    - Reusability: Create once, process many files
    - Testability: Easy to mock and test

    Input Format Expected
    ---------------------
    {
        "chunks": [
            {
                "id": "chunk_001",
                "text": "Context: ...\n\nContent...",
                "content_only": "Content without context",
                "metadata": {
                    "source": "page_001.md",
                    "page_number": 1
                }
            }
        ]
    }

    Output Format Generated
    -----------------------
    {
        "metadata": {
            "enriched_at": "2025-01-05T10:30:00",
            "total_chunks": 100
        },
        "chunks": [
            {
                "id": "chunk_001",
                "text": "...",
                "content_only": "...",
                "metadata": {
                    "source": "page_001.md",
                    "page_number": 1,
                    "entities": {...},      # NEW
                    "key_phrases": [...],   # NEW
                    "monetary_values": [...] # NEW
                }
            }
        ],
        "statistics": {
            "enrichment_stats": {...}
        }
    }

    Usage Example
    -------------
    ```python
    # Create pipeline
    pipeline = ChunkEnrichmentPipeline(
        region_name='us-east-1',
        enable_comprehend=True,
        enable_patterns=True
    )

    # Process file (auto-generates output name)
    pipeline.process('chunks_output.json')

    # Or specify custom output
    pipeline.process('input.json', 'output.json')
    ```
    """

    def __init__(
        self,
        region_name: str = 'us-east-1',
        enable_comprehend: bool = True,
        enable_patterns: bool = True,
        confidence_threshold: float = 0.7,
        batch_size: int = 100
    ):
        """
        Initialize the enrichment pipeline.

        This constructor sets up the entire enrichment infrastructure:
        1. Stores configuration parameters
        2. Creates MetadataEnricher instance
        3. Connects to AWS Comprehend (if enabled)

        INITIALIZATION FLOW:
        ───────────────────

        __init__ called
            ↓
        Store parameters (region, thresholds, etc.)
            ↓
        Create MetadataEnricher
            ↓
        MetadataEnricher connects to AWS
            ↓
        Ready to process chunks!

        Parameters
        ----------
        region_name : str, default='us-east-1'
            AWS region for Comprehend service

            Common regions:
            - 'us-east-1': US East (N. Virginia) - Default, cheapest
            - 'us-west-2': US West (Oregon)
            - 'eu-west-1': Europe (Ireland)
            - 'ap-southeast-1': Asia Pacific (Singapore)

            Why it matters:
            - Data sovereignty: Keep data in your region
            - Latency: Closer region = faster response
            - Cost: Some regions cost more

            Example:
                pipeline = ChunkEnrichmentPipeline(region_name='us-west-2')

        enable_comprehend : bool, default=True
            Whether to use AWS Comprehend for NER and key phrases

            True:  Full enrichment (entities + phrases + patterns)
                   Cost: ~$0.001 per chunk
                   Quality: Best

            False: Pattern extraction only (regex)
                   Cost: $0 (free)
                   Quality: Good for financial patterns only

            Use False when:
            - Testing without AWS credentials
            - Cost is critical
            - Only need financial patterns

            Example:
                # Testing mode (no AWS)
                pipeline = ChunkEnrichmentPipeline(enable_comprehend=False)

        enable_patterns : bool, default=True
            Whether to use custom regex patterns for extraction

            True:  Extract financial patterns ($XX, XX%, QX YYYY)
                   Cost: $0 (free)
                   Quality: 100% accurate for exact formats

            False: Rely only on AWS Comprehend
                   Cost: No change
                   Quality: May miss some financial formats

            Recommendation: Always True (it's free and helpful!)

            Example:
                # AWS Comprehend only
                pipeline = ChunkEnrichmentPipeline(enable_patterns=False)

        confidence_threshold : float, default=0.7
            Minimum confidence score to accept entities

            Range: 0.0 to 1.0
            - 0.0: Accept everything (even low confidence)
            - 0.5: Accept 50%+ confidence
            - 0.7: Accept 70%+ confidence (default, recommended)
            - 0.9: Accept 90%+ confidence (very strict)

            Trade-off:
            - Lower threshold: More entities, some wrong
            - Higher threshold: Fewer entities, more accurate

            Example:
                # Very strict (only high-confidence entities)
                pipeline = ChunkEnrichmentPipeline(confidence_threshold=0.9)

            Real-world impact:
                Threshold 0.7: "Morgan Stanley" (0.99) ✓ included
                               "MS" (0.65) ✗ excluded
                Threshold 0.6: Both included
                Threshold 0.8: Only "Morgan Stanley" included

        batch_size : int, default=100
            How often to show progress updates

            Progress shown every batch_size chunks

            Examples:
            - batch_size=10:  Update every 10 chunks (verbose)
            - batch_size=100: Update every 100 chunks (default)
            - batch_size=1000: Update every 1000 chunks (minimal)

            Impact:
            - Smaller: More frequent updates, more logs
            - Larger: Less frequent updates, cleaner output

            Recommendation: 100 for most use cases

            Example:
                # More frequent updates
                pipeline = ChunkEnrichmentPipeline(batch_size=50)

        Raises
        ------
        Exception
            If AWS Comprehend initialization fails
            (e.g., invalid credentials, wrong region)

        Examples
        --------
        # Default configuration
        pipeline = ChunkEnrichmentPipeline()

        # Custom region
        pipeline = ChunkEnrichmentPipeline(region_name='eu-west-1')

        # Testing without AWS
        pipeline = ChunkEnrichmentPipeline(enable_comprehend=False)

        # High confidence + frequent updates
        pipeline = ChunkEnrichmentPipeline(
            confidence_threshold=0.9,
            batch_size=50
        )
        """
        # STEP 1: Store all configuration parameters as instance variables
        # These will be used throughout the pipeline

        # AWS region (e.g., 'us-east-1')
        # Used when creating AWS Comprehend client
        self.region_name = region_name

        # Feature flags (boolean on/off switches)
        # Control which enrichment methods to use
        self.enable_comprehend = enable_comprehend  # AWS Comprehend on/off
        self.enable_patterns = enable_patterns      # Regex patterns on/off

        # Quality control parameter
        # Only accept entities with confidence >= this value
        self.confidence_threshold = confidence_threshold

        # Progress tracking parameter
        # How often to print progress updates
        self.batch_size = batch_size

        # STEP 2: Log initialization start
        # Let user know we're setting up
        logger.info("Initializing MetadataEnricher...")

        # STEP 3: Create MetadataEnricher instance
        # This is the core engine that does the actual enrichment
        #
        # What happens here:
        # 1. MetadataEnricher.__init__ is called
        # 2. If enable_comprehend=True, connects to AWS
        # 3. Compiles regex patterns
        # 4. Sets up statistics tracking
        #
        # If this fails (e.g., bad AWS credentials), an exception is raised
        self.enricher = MetadataEnricher(
            region_name=region_name,                # Pass AWS region
            enable_comprehend=enable_comprehend,    # Pass Comprehend flag
            enable_patterns=enable_patterns,        # Pass patterns flag
            confidence_threshold=confidence_threshold  # Pass threshold
        )

        # STEP 4: Log successful initialization
        # ✓ symbol shows success visually
        logger.info("✓ MetadataEnricher initialized")

        # At this point:
        # - Configuration stored
        # - AWS connection established (if enabled)
        # - Regex patterns compiled
        # - Ready to process chunks!

    @staticmethod
    def generate_output_filename(input_file: str) -> str:
        """
        Generate output filename from input filename automatically.

        This is a STATIC METHOD (no self parameter) because it doesn't
        need access to instance variables. It's a pure utility function.

        NAMING PATTERN:
        ───────────────

        Input:  <name>.json
        Output: <name>_enriched_metadata.json

        WHY THIS PATTERN?
        ─────────────────
        1. Descriptive: Clear what file contains
        2. Preserves original: Input not overwritten
        3. Same directory: Easy to find
        4. Consistent: Always follows same pattern

        ALGORITHM:
        ──────────

        1. Parse input path into components
           '/path/to/chunks_output.json'
               ↓
           parent: '/path/to'
           stem: 'chunks_output' (no extension)

        2. Construct new filename
           stem + '_enriched_metadata' + '.json'
               ↓
           'chunks_output_enriched_metadata.json'

        3. Combine with original directory
           parent / new_filename
               ↓
           '/path/to/chunks_output_enriched_metadata.json'

        Parameters
        ----------
        input_file : str
            Input filename (can be relative or absolute path)

            Examples:
            - 'chunks.json'
            - './data/chunks.json'
            - '/home/user/chunks.json'

        Returns
        -------
        str
            Generated output filename in same directory

            Examples:
            - 'chunks_enriched_metadata.json'
            - './data/chunks_enriched_metadata.json'
            - '/home/user/chunks_enriched_metadata.json'

        Examples
        --------
        >>> generate_output_filename('chunks_output.json')
        'chunks_output_enriched_metadata.json'

        >>> generate_output_filename('./data/doc.json')
        './data/doc_enriched_metadata.json'

        >>> generate_output_filename('/home/user/test.json')
        '/home/user/test_enriched_metadata.json'

        Edge Cases
        ----------
        - No directory: 'file.json' → 'file_enriched_metadata.json'
        - Multiple dots: 'file.v2.json' → 'file.v2_enriched_metadata.json'
        - No extension: 'file' → 'file_enriched_metadata.json'
        """
        # STEP 1: Convert string path to Path object
        # Path object provides convenient methods for path manipulation
        # Example: '/path/to/file.json' becomes Path object
        input_path = Path(input_file)

        # STEP 2: Extract filename without extension
        # .stem property returns filename without extension
        #
        # Examples:
        #   'file.json' → 'file'
        #   'document.txt' → 'document'
        #   'file.tar.gz' → 'file.tar' (only removes last extension)
        #
        # Why we need this:
        #   To add '_enriched_metadata' before the extension
        input_stem = input_path.stem

        # STEP 3: Extract parent directory
        # .parent property returns directory containing the file
        #
        # Examples:
        #   '/path/to/file.json' → '/path/to'
        #   './data/file.json' → './data'
        #   'file.json' → '.' (current directory)
        #
        # Why we need this:
        #   To put output file in same directory as input
        input_dir = input_path.parent

        # STEP 4: Construct new filename
        # Format: <original_name>_enriched_metadata.json
        #
        # Using f-string for clean string formatting
        # {input_stem} gets replaced with actual value
        #
        # Example:
        #   input_stem = 'chunks_output'
        #   output_filename = 'chunks_output_enriched_metadata.json'
        output_filename = f"{input_stem}_enriched_metadata.json"

        # STEP 5: Combine directory and filename
        # Path's / operator joins paths correctly for any OS
        #
        # On Unix/Linux/Mac: / as separator
        # On Windows: \ as separator
        # Path handles this automatically!
        #
        # Examples:
        #   Path('/path/to') / 'file.json' → '/path/to/file.json'
        #   Path('./data') / 'file.json' → './data/file.json'
        output_path = input_dir / output_filename

        # STEP 6: Convert Path object back to string
        # API functions expect strings, not Path objects
        # str() converts Path to string representation
        #
        # Example:
        #   Path('/path/to/file.json') → '/path/to/file.json' (string)
        return str(output_path)

    def load_chunks(self, input_file: str) -> List[Dict]:
        """
        Load chunks from JSON file with validation.

        This method:
        1. Checks file exists
        2. Reads JSON content
        3. Extracts chunks array
        4. Validates format
        5. Returns chunks list

        FILE FORMAT HANDLING:
        ────────────────────

        We support TWO input formats:

        Format 1 (Preferred): Dictionary with 'chunks' key
        {
            "chunks": [chunk1, chunk2, ...],
            "statistics": {...}  ← Optional
        }

        Format 2 (Simple): Direct array
        [chunk1, chunk2, ...]

        Why support both?
        - Format 1: Our standard output format
        - Format 2: Simpler for testing

        VALIDATION CHECKS:
        ─────────────────

        1. File exists? (FileNotFoundError if not)
        2. Valid JSON? (JSONDecodeError if malformed)
        3. Correct structure? (ValueError if wrong format)
        4. Has chunks? (ValueError if empty/missing)

        Parameters
        ----------
        input_file : str
            Path to input JSON file
            Can be relative ('chunks.json') or absolute ('/path/to/chunks.json')

        Returns
        -------
        List[Dict]
            List of chunk dictionaries
            Each chunk has: id, text, content_only, metadata

        Raises
        ------
        FileNotFoundError
            If input file doesn't exist
            Message: "Input file not found: <path>"

        json.JSONDecodeError
            If file is not valid JSON
            Message: "Expecting value: line X column Y"

        ValueError
            If file structure is wrong
            Message: "Invalid input format. Expected dict with 'chunks' key..."

        Examples
        --------
        # Load chunks
        chunks = pipeline.load_chunks('chunks_output.json')
        print(f"Loaded {len(chunks)} chunks")

        # Handle errors
        try:
            chunks = pipeline.load_chunks('missing.json')
        except FileNotFoundError:
            print("File not found!")
        """
        # STEP 1: Log what we're doing
        # This appears in console as:
        # 2025-01-05 10:30:00 | INFO | Loading chunks from: chunks_output.json
        logger.info(f"Loading chunks from: {input_file}")

        # STEP 2: Check if file exists
        # os.path.exists() returns True if file exists, False otherwise
        #
        # Why check before opening?
        # - Better error message (our custom message vs Python's)
        # - Explicit check makes code clearer
        # - Can handle error gracefully
        if not os.path.exists(input_file):
            # File doesn't exist!
            # Raise FileNotFoundError with descriptive message
            # This will stop execution and show error to user
            raise FileNotFoundError(f"Input file not found: {input_file}")

        # STEP 3: Open and read JSON file
        #
        # with statement ensures file is closed even if error occurs
        # 'r' mode = read mode (not write)
        # encoding='utf-8' = handle international characters properly
        #
        # json.load() parses JSON and returns Python objects:
        #   JSON object {} → Python dict
        #   JSON array [] → Python list
        #   JSON string "" → Python str
        #   JSON number → Python int/float
        #   JSON true/false → Python True/False
        #   JSON null → Python None
        with open(input_file, 'r', encoding='utf-8') as f:
            # Load entire JSON file into memory
            # For large files (>100MB), this could be slow
            # For typical use (<10MB), this is fine
            data = json.load(f)

        # STEP 4: Extract chunks from data
        # We support two formats (see docstring)
        # Use isinstance() to check data type

        # Check Format 1: Dictionary with 'chunks' key
        if isinstance(data, dict) and 'chunks' in data:
            # Format 1 detected!
            # Example: {"chunks": [...], "statistics": {...}}
            # Extract just the chunks array
            chunks = data['chunks']

        # Check Format 2: Direct array
        elif isinstance(data, list):
            # Format 2 detected!
            # Example: [chunk1, chunk2, ...]
            # Use entire data as chunks
            chunks = data

        # Neither format matched
        else:
            # Invalid format!
            # Raise ValueError with helpful message
            # This tells user what format we expect
            raise ValueError(
                "Invalid input format. Expected dict with 'chunks' key or list of chunks"
            )

        # STEP 5: Log success with chunk count
        # f-string formatting with :, for thousands separator
        # Example: 1000 → "1,000", 1000000 → "1,000,000"
        logger.info(f"✓ Loaded {len(chunks):,} chunks")

        # STEP 6: Return chunks list
        # This list will be iterated in enrich_chunks()
        return chunks

    def validate_chunk(self, chunk: Dict, index: int) -> bool:
        """
        Validate that chunk has all required fields.

        This is a DEFENSIVE PROGRAMMING practice:
        - Catch bad data early
        - Provide helpful error messages
        - Prevent downstream failures

        VALIDATION CHECKS:
        ─────────────────

        Check 1: Required fields present
            ['id', 'text', 'content_only', 'metadata']
            All must exist in chunk dictionary

        Check 2: content_only not empty
            Must have actual content to analyze
            Empty string or whitespace-only is invalid

        WHY VALIDATE?
        ────────────

        Without validation:
            Bad chunk → MetadataEnricher → Exception → Pipeline stops

        With validation:
            Bad chunk → Logged warning → Skipped → Pipeline continues

        Better user experience!

        Parameters
        ----------
        chunk : Dict
            Chunk dictionary to validate
            Should have: id, text, content_only, metadata

        index : int
            Chunk position in list (1-based for user display)
            Used in error messages to identify problematic chunk
            Example: "Chunk 42 missing required field 'id'"

        Returns
        -------
        bool
            True if chunk is valid and can be processed
            False if chunk is invalid and should be skipped

        Side Effects
        ------------
        Logs warning messages for invalid chunks
        Messages include: index, chunk id (if present), problem

        Examples
        --------
        # Valid chunk
        chunk = {
            'id': 'chunk_001',
            'text': 'Context: ...\n\nMorgan Stanley...',
            'content_only': 'Morgan Stanley reported...',
            'metadata': {'page': 5}
        }
        valid = pipeline.validate_chunk(chunk, 1)
        # Returns: True

        # Invalid chunk (missing content_only)
        chunk = {
            'id': 'chunk_002',
            'text': 'Some text',
            'metadata': {'page': 6}
        }
        valid = pipeline.validate_chunk(chunk, 2)
        # Returns: False
        # Logs: "Chunk 2 missing required field 'content_only'. Skipping."

        # Invalid chunk (empty content_only)
        chunk = {
            'id': 'chunk_003',
            'text': 'Text',
            'content_only': '',  # Empty!
            'metadata': {'page': 7}
        }
        valid = pipeline.validate_chunk(chunk, 3)
        # Returns: False
        # Logs: "Chunk 3 (id: chunk_003) has empty content_only. Skipping."
        """
        # STEP 1: Define required fields
        # These are the MINIMUM fields needed for enrichment
        #
        # Why each field is required:
        # - 'id': Unique identifier for tracking
        # - 'text': Full text with context (for reference)
        # - 'content_only': Text to analyze (without context header)
        # - 'metadata': Place to add enriched metadata
        required_fields = ['id', 'text', 'content_only', 'metadata']

        # STEP 2: Check each required field exists
        # Loop through each field name
        for field in required_fields:
            # Check if field is in chunk dictionary
            # 'field in chunk' returns True if key exists, False otherwise
            if field not in chunk:
                # Field is missing!
                # Log warning with helpful message
                #
                # Warning level (not error) because:
                # - We can skip this chunk
                # - Pipeline can continue
                # - Not fatal to overall process
                logger.warning(
                    f"Chunk {index} missing required field '{field}'. Skipping."
                )
                # Return False = invalid chunk, skip it
                return False

        # STEP 3: Check content_only is not empty
        # chunk.get('content_only', '') returns:
        #   - chunk['content_only'] if it exists
        #   - '' (empty string) if it doesn't (shouldn't happen, we checked above)
        #
        # Why check this?
        # - Empty string: Nothing to analyze
        # - Whitespace only: "   \n\t  " → also useless
        #
        # Two conditions (both must be true to be invalid):
        # 1. not chunk['content_only'] → True if empty string
        # 2. not chunk['content_only'].strip() → True if only whitespace
        #
        # Examples:
        #   '' → not True and not ''.strip() → Skip
        #   '   ' → not False but not '   '.strip() → Skip
        #   'text' → not False and not False → OK
        if not chunk['content_only'] or not chunk['content_only'].strip():
            # Content is empty or whitespace-only!
            # Log warning with chunk ID for easier debugging
            logger.warning(
                f"Chunk {index} (id: {chunk['id']}) has empty content_only. Skipping."
            )
            # Return False = invalid chunk, skip it
            return False

        # STEP 4: All checks passed!
        # Chunk is valid and ready for enrichment
        # Return True = valid chunk, process it
        return True

    def enrich_chunks(
        self,
        chunks: List[Dict],
        show_progress: bool = True
    ) -> List[Dict]:
        """
        Enrich all chunks with metadata.

        This is the CORE PROCESSING LOOP:
        - Iterate through all chunks
        - Validate each chunk
        - Call MetadataEnricher
        - Track progress
        - Handle errors gracefully

        PROCESSING FLOW:
        ───────────────

        For each chunk:
            ↓
        1. Validate (has required fields?)
            ↓ Yes
        2. Enrich (call MetadataEnricher)
            ↓
        3. Handle errors (if any)
            ↓
        4. Add to results
            ↓
        5. Log progress (every batch_size chunks)

        ERROR HANDLING STRATEGY:
        ───────────────────────

        Fail fast (BAD):
            Error on chunk 10 → Stop → Lose chunks 11-1000

        Continue on error (GOOD - what we do):
            Error on chunk 10 → Log warning → Keep original → Continue
            Result: 999 enriched + 1 original (not enriched)

        This is RESILIENT processing!

        Parameters
        ----------
        chunks : List[Dict]
            List of chunks to enrich
            Each chunk should have: id, text, content_only, metadata

        show_progress : bool, default=True
            Whether to print progress updates
            True: Print every batch_size chunks
            False: Silent processing (good for batch scripts)

        Returns
        -------
        List[Dict]
            List of enriched chunks (same order as input)
            Successfully enriched chunks have new metadata fields
            Failed chunks returned as-is (original, not enriched)

        Side Effects
        ------------
        - Logs progress every batch_size chunks
        - Logs warnings for validation failures
        - Logs errors for enrichment failures
        - Updates self.enricher.stats

        Performance
        -----------
        Time per chunk: ~100-150ms (with Comprehend)
        1000 chunks: ~2-3 minutes
        Rate limit: 20 TPS (transactions per second)

        Examples
        --------
        # Process with progress
        enriched = pipeline.enrich_chunks(chunks, show_progress=True)
        # Output: Progress: 100/1000 (10.0%)
        #         Progress: 200/1000 (20.0%)
        #         ...

        # Silent processing
        enriched = pipeline.enrich_chunks(chunks, show_progress=False)
        # Output: (nothing)
        """
        # STEP 1: Log enrichment start with configuration
        # Show total chunk count and which features are enabled
        logger.info(f"Starting enrichment of {len(chunks)} chunks...")

        # Log Comprehend status
        # Ternary operator: condition ? true_value : false_value
        # Same as: if self.enable_comprehend: 'ENABLED' else: 'DISABLED'
        logger.info(f"Comprehend: {'ENABLED' if self.enable_comprehend else 'DISABLED'}")

        # Log patterns status
        logger.info(f"Patterns: {'ENABLED' if self.enable_patterns else 'DISABLED'}")

        # STEP 2: Initialize result tracking
        # We need TWO pieces of information:

        # List to store enriched chunks
        # Will contain same number of chunks as input
        # (Some enriched, some original if validation/enrichment failed)
        enriched_chunks = []

        # Counter for chunks that couldn't be processed
        # Includes:
        # - Validation failures (missing fields, empty content)
        # - Enrichment failures (AWS errors, exceptions)
        skipped_count = 0

        # STEP 3: Main processing loop
        # enumerate() gives us both index and item
        # enumerate(list, 1) starts counting from 1 (not 0)
        #
        # Why start from 1?
        # - User-friendly: "Processing chunk 1, 2, 3..." (not 0, 1, 2)
        # - Matches "Chunk 1 of 100" display
        #
        # Loop variable i = chunk number (1-based)
        # Loop variable chunk = chunk dictionary
        for i, chunk in enumerate(chunks, 1):
            # STEP 3a: Validate chunk
            # validate_chunk() returns True if valid, False if invalid
            #
            # Why validate?
            # - Catch malformed chunks early
            # - Provide helpful error messages
            # - Prevent downstream crashes
            if not self.validate_chunk(chunk, i):
                # Validation failed!
                # Increment skip counter
                skipped_count += 1

                # Add ORIGINAL chunk to results (not enriched)
                # This preserves the chunk even though we couldn't process it
                # Better than losing the chunk entirely
                enriched_chunks.append(chunk)

                # Continue to next chunk (skip enrichment)
                # 'continue' jumps to next iteration of loop
                continue

            # STEP 3b: Enrich chunk (if validation passed)
            # Wrap in try-except to handle any errors gracefully
            try:
                # Call MetadataEnricher to add metadata
                # This does the actual work:
                # 1. Calls AWS Comprehend for entities
                # 2. Calls AWS Comprehend for key phrases
                # 3. Extracts custom patterns via regex
                # 4. Merges all metadata into chunk
                #
                # Time: ~100-150ms per chunk
                # Cost: ~$0.001 per chunk
                enriched = self.enricher.enrich_chunk(chunk)

                # Success! Add enriched chunk to results
                enriched_chunks.append(enriched)

            except Exception as e:
                # Enrichment failed!
                # Possible reasons:
                # - AWS throttling (too many requests)
                # - Network error
                # - Invalid credentials
                # - Malformed chunk (edge case validation missed)
                # - AWS service outage

                # Log error with details
                # Include chunk index and ID for debugging
                # Include error message to understand what went wrong
                logger.error(f"Error enriching chunk {i} (id: {chunk['id']}): {e}")

                # Add ORIGINAL chunk (not enriched)
                # Same strategy as validation failure
                # Preserve data even if we can't enrich it
                enriched_chunks.append(chunk)

                # Increment skip counter
                # This chunk is counted as "failed to enrich"
                skipped_count += 1

            # STEP 3c: Progress update (every batch_size chunks)
            # Only if show_progress is True
            #
            # Modulo operator % gives remainder of division
            # i % batch_size == 0 means i is multiple of batch_size
            # Examples with batch_size=100:
            #   100 % 100 = 0 → Show progress
            #   150 % 100 = 50 → Don't show
            #   200 % 100 = 0 → Show progress
            if show_progress and i % self.batch_size == 0:
                # Calculate percentage complete
                # (current / total) * 100
                # Example: (100 / 1000) * 100 = 10.0%
                pct = (i / len(chunks)) * 100

                # Log progress with both count and percentage
                # .1f formats float with 1 decimal place
                # Example: "Progress: 100/1000 (10.0%)"
                logger.info(f"Progress: {i}/{len(chunks)} ({pct:.1f}%)")

        # STEP 4: Log completion summary
        # Show how many succeeded vs failed
        logger.info(f"✓ Enrichment complete!")
        logger.info(f"  - Successfully enriched: {len(chunks) - skipped_count}")
        logger.info(f"  - Skipped/Failed: {skipped_count}")

        # STEP 5: Return all chunks (enriched + original)
        # Length of enriched_chunks equals length of input chunks
        # Order preserved (chunk i in input → chunk i in output)
        return enriched_chunks

    def save_enriched_chunks(
        self,
        enriched_chunks: List[Dict],
        output_file: str,
        include_statistics: bool = True
    ):
        """
        Save enriched chunks to JSON file with metadata.

        This method creates a STRUCTURED output file with:
        1. Metadata: When enriched, configuration, counts
        2. Chunks: The actual enriched chunks
        3. Statistics: Enrichment stats (optional)

        OUTPUT FILE STRUCTURE:
        ─────────────────────

        {
            "metadata": {                    ← File-level info
                "enriched_at": "2025-01-05T10:30:00",
                "total_chunks": 1000,
                "enrichment_config": {...}
            },
            "chunks": [                      ← Enriched chunks
                {...},
                {...},
                ...
            ],
            "statistics": {                  ← Enrichment stats
                "enrichment_stats": {...}
            }
        }

        WHY THIS STRUCTURE?
        ──────────────────
        - metadata: Know when/how chunks were enriched
        - chunks: The actual data
        - statistics: Monitor quality and costs

        FILE SIZE EXAMPLE:
        ─────────────────
        Input: chunks_output.json (1 MB)
        Output: chunks_output_enriched_metadata.json (3-5 MB)

        Why larger? Added metadata for each chunk!

        Parameters
        ----------
        enriched_chunks : List[Dict]
            List of enriched chunk dictionaries

        output_file : str
            Path where to save output file
            Will create directories if they don't exist

        include_statistics : bool, default=True
            Whether to include enrichment statistics in output
            True: Add statistics section
            False: Omit statistics (smaller file)

        Side Effects
        ------------
        - Creates output file (overwrites if exists)
        - Creates directories (if needed)
        - Logs file path and size

        Examples
        --------
        # Save with statistics
        pipeline.save_enriched_chunks(
            enriched_chunks,
            'output/enriched.json',
            include_statistics=True
        )

        # Save without statistics (smaller file)
        pipeline.save_enriched_chunks(
            enriched_chunks,
            'output/enriched.json',
            include_statistics=False
        )
        """
        # STEP 1: Log what we're doing
        logger.info(f"Saving enriched chunks to: {output_file}")

        # STEP 2: Create output directory if needed
        # os.path.dirname() extracts directory from path
        # Examples:
        #   './output/file.json' → './output'
        #   'file.json' → '' (empty string = current directory)
        #   '/path/to/file.json' → '/path/to'
        output_dir = os.path.dirname(output_file)

        # Check if directory path exists AND is not empty
        # Why check both?
        # - Empty string means current directory (always exists)
        # - Non-empty string needs existence check
        if output_dir and not os.path.exists(output_dir):
            # Directory doesn't exist, create it!
            # makedirs creates all intermediate directories
            # Examples:
            #   'a/b/c' creates a, then a/b, then a/b/c
            os.makedirs(output_dir)
            # Log directory creation
            logger.info(f"Created output directory: {output_dir}")

        # STEP 3: Build output data structure
        # This is the JSON that will be written to file
        #
        # Structure has THREE sections:
        # 1. metadata: File-level information
        # 2. chunks: The enriched chunks
        # 3. statistics: Enrichment statistics (optional)
        output_data = {
            # Section 1: File metadata
            "metadata": {
                # When enrichment was performed
                # ISO format: 2025-01-05T10:30:00.123456
                # isoformat() converts datetime to ISO string
                "enriched_at": datetime.now().isoformat(),

                # How many chunks in file
                # Helps validate file integrity
                "total_chunks": len(enriched_chunks),

                # Configuration used for enrichment
                # Helps reproduce results or understand how enriched
                "enrichment_config": {
                    "region_name": self.region_name,
                    "comprehend_enabled": self.enable_comprehend,
                    "patterns_enabled": self.enable_patterns,
                    "confidence_threshold": self.confidence_threshold
                }
            },
            # Section 2: The actual enriched chunks
            # This is the main payload
            "chunks": enriched_chunks
        }

        # STEP 4: Add statistics if requested
        # Conditional section addition
        # Only added if include_statistics=True
        if include_statistics:
            # Get statistics from MetadataEnricher
            # Returns dict with:
            # - chunks_processed
            # - comprehend_calls
            # - entities_extracted
            # - etc.
            output_data["statistics"] = {
                "enrichment_stats": self.enricher.get_statistics()
            }

        # STEP 5: Write to JSON file
        # with statement ensures file is closed properly
        # 'w' mode = write mode (creates new file or overwrites existing)
        # encoding='utf-8' = handle international characters
        with open(output_file, 'w', encoding='utf-8') as f:
            # json.dump() writes Python objects as JSON
            #
            # Parameters:
            # - output_data: What to write
            # - f: Where to write (file object)
            # - indent=2: Pretty-print with 2-space indentation
            # - ensure_ascii=False: Allow non-ASCII characters (unicode)
            #
            # indent=2 makes JSON human-readable:
            # Without: {"a":{"b":"c"}}
            # With: {
            #         "a": {
            #           "b": "c"
            #         }
            #       }
            #
            # ensure_ascii=False allows:
            # - Emojis: 😀
            # - Chinese: 中文
            # - Accents: café
            # Without it, these become: \u1234 (escaped)
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        # STEP 6: Calculate and log file size
        # os.path.getsize() returns size in bytes
        file_size = os.path.getsize(output_file)

        # Convert bytes to megabytes
        # 1 MB = 1024 KB = 1024 * 1024 bytes = 1,048,576 bytes
        # So bytes / 1,048,576 = megabytes
        file_size_mb = file_size / (1024 * 1024)

        # STEP 7: Log success with details
        logger.info(f"✓ Saved enriched chunks")
        logger.info(f"  - Output file: {output_file}")
        # .2f formats float with 2 decimal places
        # Example: 2.456789 → "2.46"
        logger.info(f"  - File size: {file_size_mb:.2f} MB")

    def process(
        self,
        input_file: str,
        output_file: Optional[str] = None,
        show_progress: bool = True,
        print_statistics: bool = True
    ):
        """
        Complete end-to-end processing pipeline.

        This is the MAIN METHOD that orchestrates everything:
        1. Generate output filename (if not provided)
        2. Load chunks
        3. Enrich chunks
        4. Save enriched chunks
        5. Print statistics

        ORCHESTRATION FLOW:
        ──────────────────

        process() called
            ↓
        [Auto-generate output filename if needed]
            ↓
        [Load chunks from input file]
            ↓
        [Validate and enrich each chunk]
            ↓
        [Save enriched chunks to output file]
            ↓
        [Print statistics]
            ↓
        Done!

        ERROR HANDLING:
        ──────────────

        Any exception in any step:
        1. Logged with details
        2. Re-raised to caller
        3. Pipeline stops (fail-safe)

        This ensures we never silently fail!

        Parameters
        ----------
        input_file : str
            Input JSON file with chunks
            Required parameter

        output_file : str, optional
            Output JSON file for enriched chunks
            If None: Auto-generates <input_base>_enriched_metadata.json
            If provided: Uses specified path

        show_progress : bool, default=True
            Show progress updates during enrichment
            True: Print progress every batch_size chunks
            False: Silent processing

        print_statistics : bool, default=True
            Print enrichment statistics at end
            True: Show detailed stats
            False: Skip stats (quieter output)

        Raises
        ------
        FileNotFoundError
            If input file doesn't exist

        ValueError
            If input file has wrong format

        Exception
            Any other error during processing
            (Logged and re-raised)

        Examples
        --------
        # Simplest usage (auto-generates output)
        pipeline.process('chunks_output.json')
        # Creates: chunks_output_enriched_metadata.json

        # Custom output filename
        pipeline.process('input.json', 'my_output.json')

        # Silent processing (no progress, no stats)
        pipeline.process(
            'input.json',
            show_progress=False,
            print_statistics=False
        )

        # Only statistics, no progress
        pipeline.process(
            'input.json',
            show_progress=False,
            print_statistics=True
        )
        """
        # STEP 0: Auto-generate output filename if needed
        # Check if output_file is None (not provided)
        if output_file is None:
            # Generate output filename from input filename
            # Uses our generate_output_filename() static method
            output_file = self.generate_output_filename(input_file)
            # Log what we generated
            logger.info(f"Auto-generated output filename: {output_file}")

        # STEP 1: Print pipeline header
        # Visual separator makes logs easier to read
        # "=" * 70 creates string of 70 equal signs
        logger.info("="*70)
        logger.info("CHUNK ENRICHMENT PIPELINE - Starting")
        logger.info("="*70)

        # Log input and output files
        # Helps user verify correct files being processed
        logger.info(f"Input file:  {input_file}")
        logger.info(f"Output file: {output_file}")
        logger.info("")  # Blank line for readability

        # STEP 2: Wrap entire process in try-except
        # This catches ANY error in ANY step
        # Allows us to:
        # 1. Log detailed error
        # 2. Print failure message
        # 3. Re-raise exception (let caller handle)
        try:
            # ════════════════════════════════════════════════════════
            # STEP 3: Load chunks from input file
            # ════════════════════════════════════════════════════════
            logger.info("STEP 1: Loading chunks...")

            # Call load_chunks() method
            # Returns List[Dict] of chunks
            # May raise FileNotFoundError or ValueError
            chunks = self.load_chunks(input_file)

            # Blank line for visual separation
            logger.info("")

            # ════════════════════════════════════════════════════════
            # STEP 4: Enrich all chunks with metadata
            # ════════════════════════════════════════════════════════
            logger.info("STEP 2: Enriching chunks...")

            # Call enrich_chunks() method
            # Returns List[Dict] of enriched chunks
            # Same length as input, same order
            # May raise exceptions but catches them internally
            enriched_chunks = self.enrich_chunks(chunks, show_progress)

            # Blank line for visual separation
            logger.info("")

            # ════════════════════════════════════════════════════════
            # STEP 5: Save enriched chunks to output file
            # ════════════════════════════════════════════════════════
            logger.info("STEP 3: Saving enriched chunks...")

            # Call save_enriched_chunks() method
            # Writes JSON file with enriched chunks
            # Creates directories if needed
            self.save_enriched_chunks(enriched_chunks, output_file)

            # Blank line for visual separation
            logger.info("")

            # ════════════════════════════════════════════════════════
            # STEP 6: Print statistics (if requested)
            # ════════════════════════════════════════════════════════
            if print_statistics:
                logger.info("STEP 4: Enrichment statistics")

                # Call MetadataEnricher's print_statistics() method
                # Shows:
                # - Chunks processed
                # - API calls made
                # - Entities extracted
                # - Estimated cost
                # - etc.
                self.enricher.print_statistics()

            # ════════════════════════════════════════════════════════
            # STEP 7: Print success message
            # ════════════════════════════════════════════════════════
            logger.info("="*70)
            logger.info("CHUNK ENRICHMENT PIPELINE - Completed Successfully!")
            logger.info("="*70)

        except Exception as e:
            # ════════════════════════════════════════════════════════
            # ERROR HANDLING: Something went wrong!
            # ════════════════════════════════════════════════════════

            # Print failure header
            logger.error("="*70)
            logger.error("CHUNK ENRICHMENT PIPELINE - FAILED")
            logger.error("="*70)

            # Log the actual error message
            # This helps user understand what went wrong
            logger.error(f"Error: {e}")

            # Re-raise the exception
            # This allows caller to handle error if they want
            # Example:
            #   try:
            #       pipeline.process('file.json')
            #   except FileNotFoundError:
            #       print("File not found!")
            raise


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    """
    Command-line interface for the enrichment pipeline.

    This function makes the script usable from command line:
        python enrich_chunks.py input.json

    Uses argparse library to handle arguments and options:
    - Positional arguments: Required (input_file)
    - Optional arguments: Optional with defaults (--region, --confidence)
    - Flags: Boolean switches (--no-comprehend, --quiet)

    For full usage, see module docstring or run:
        python enrich_chunks.py --help
    """
    # Import argparse library for command-line argument parsing
    # Imported here (not at top) because only CLI needs it
    # Programmatic usage doesn't need argparse
    import argparse

    # Create argument parser
    # ArgumentParser is the main class for CLI argument handling
    #
    # Parameters:
    # - description: Shown at top of help message
    # - formatter_class: How to format help message
    #     RawDescriptionHelpFormatter preserves line breaks in epilog
    # - epilog: Shown at bottom of help message (examples)
    parser = argparse.ArgumentParser(
        description='Enrich semantic chunks with metadata using AWS Comprehend',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (auto-generates output filename)
  python enrich_chunks.py chunks_output.json
  → Creates: chunks_output_enriched_metadata.json
  
  # Specify custom output filename
  python enrich_chunks.py chunks_output.json my_enriched.json
  
  # Specify AWS region
  python enrich_chunks.py input.json --region us-west-2
  
  # Disable AWS Comprehend (patterns only, free)
  python enrich_chunks.py input.json --no-comprehend
  
  # Custom confidence threshold
  python enrich_chunks.py input.json --confidence 0.9
  
  # With path prefix
  python enrich_chunks.py ./data/chunks.json
  → Creates: ./data/chunks_enriched_metadata.json
        """
    )

    # Add input_file argument (REQUIRED)
    # This is a positional argument (no -- prefix)
    # User MUST provide this
    parser.add_argument(
        'input_file',
        help='Input JSON file with chunks (from semantic chunker)'
    )

    # Add output_file argument (OPTIONAL)
    # nargs='?' means 0 or 1 argument (optional)
    # default=None means use None if not provided
    parser.add_argument(
        'output_file',
        nargs='?',  # Make optional
        default=None,
        help='Output JSON file for enriched chunks (default: <input_base>_enriched_metadata.json)'
    )

    # Add --region option
    # This is an optional argument (-- prefix)
    # Has default value, so user doesn't need to provide
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region for Comprehend (default: us-east-1)'
    )

    # Add --no-comprehend flag
    # action='store_true' means:
    #   Flag present → True
    #   Flag absent → False
    parser.add_argument(
        '--no-comprehend',
        action='store_true',
        help='Disable AWS Comprehend (use patterns only)'
    )

    # Add --no-patterns flag
    parser.add_argument(
        '--no-patterns',
        action='store_true',
        help='Disable custom patterns (use Comprehend only)'
    )

    # Add --confidence option
    # type=float converts string to float
    # Validation added below
    parser.add_argument(
        '--confidence',
        type=float,
        default=0.7,
        help='Confidence threshold for entities (0.0-1.0, default: 0.7)'
    )

    # Add --batch-size option
    # type=int converts string to integer
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Progress update frequency (default: 100)'
    )

    # Add --quiet flag
    # Suppresses progress and statistics
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress messages'
    )

    # Parse command-line arguments
    # sys.argv contains command-line arguments
    # Returns Namespace object with argument values
    args = parser.parse_args()

    # Generate output filename if not provided
    # Same logic as in process() method
    if args.output_file is None:
        input_path = Path(args.input_file)
        input_stem = input_path.stem
        input_dir = input_path.parent
        output_filename = f"{input_stem}_enriched_metadata.json"
        args.output_file = str(input_dir / output_filename)
        logger.info(f"No output file specified. Using: {args.output_file}")

    # Validate confidence threshold
    # Must be between 0.0 and 1.0
    if not 0.0 <= args.confidence <= 1.0:
        # parser.error() prints message and exits with error code
        parser.error("Confidence threshold must be between 0.0 and 1.0")

    # Create pipeline with parsed arguments
    pipeline = ChunkEnrichmentPipeline(
        region_name=args.region,
        enable_comprehend=not args.no_comprehend,  # Invert flag
        enable_patterns=not args.no_patterns,      # Invert flag
        confidence_threshold=args.confidence,
        batch_size=args.batch_size
    )

    # Run pipeline with parsed arguments
    pipeline.process(
        input_file=args.input_file,
        output_file=args.output_file,
        show_progress=not args.quiet,  # Invert flag
        print_statistics=not args.quiet  # Invert flag
    )


# ============================================================================
# PROGRAMMATIC USAGE EXAMPLES
# ============================================================================
#
# These example functions demonstrate different usage patterns
# Comment out main() and uncomment one to run examples

# ... [Example functions remain the same - omitted for brevity]


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    """
    Script entry point.
    
    __name__ == '__main__' is True when:
    - Script run directly: python enrich_chunks.py
    
    __name__ == '__main__' is False when:
    - Script imported: from enrich_chunks import ChunkEnrichmentPipeline
    
    This allows script to work both as:
    1. Command-line tool (run main())
    2. Importable module (don't run main())
    """

    # Command line mode
    # Run CLI interface
    main()

    # Example mode (uncomment to run)
    # example_basic()
    # example_patterns_only()
    # example_custom_config()
    # example_batch_processing()