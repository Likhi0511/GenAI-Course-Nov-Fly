#!/usr/bin/env python3
"""
Semantic Chunker - Main Entry Point
====================================

FUNCTIONAL MODULAR ARCHITECTURE

This is the entry point for the semantic chunker system.
All business logic is in separate modules - this file only:
1. Parses command-line arguments
2. Calls the orchestrator
3. Handles errors gracefully

WHY THIS DESIGN?
----------------
- TESTABILITY: Can test orchestrator without CLI parsing
- CLARITY: Clear entry point, all logic elsewhere
- FLEXIBILITY: Easy to add GUI, API, or other interfaces
"""

import argparse
import sys
from pathlib import Path

# Import orchestrator
from orchestrator import process_document


def main():
    """
    Main entry point with argument parsing.
    
    This function only handles:
    - CLI argument parsing
    - Calling the orchestrator
    - Top-level error handling
    
    All actual processing logic is in the orchestrator and its modules.
    """
    
    parser = argparse.ArgumentParser(
        description="Semantic document chunker with functional modular architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Basic usage:
    python open_ai_version.py --input-dir extracted_docs
  
  Custom configuration:
    python open_ai_version.py \\
        --input-dir extracted_docs \\
        --target-size 2000 \\
        --min-size 1000 \\
        --max-size 3000
  
  Disable cross-page merging:
    python open_ai_version.py --input-dir extracted_docs --no-merging
  
  Quiet mode (less verbose output):
    python open_ai_version.py --input-dir extracted_docs --quiet
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing metadata.json and pages/"
    )
    
    # Optional size parameters
    parser.add_argument(
        "--target-size",
        type=int,
        default=1500,
        help="Target chunk size in characters (default: 1500)"
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=800,
        help="Minimum chunk size in characters (default: 800)"
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=2500,
        help="Maximum chunk size in characters (default: 2500)"
    )
    
    # Optional features
    parser.add_argument(
        "--no-merging",
        dest='enable_merging',
        action='store_false',
        help="Disable cross-page boundary merging"
    )
    parser.set_defaults(enable_merging=True)
    
    # Verbosity control
    parser.add_argument(
        "--quiet",
        dest='verbose',
        action='store_false',
        help="Reduce console output (only INFO level, no DEBUG)"
    )
    parser.set_defaults(verbose=True)
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate input directory
    input_path = Path(args.input_dir)
    if not input_path.exists():
        print(f"Error: Input directory not found: {args.input_dir}", file=sys.stderr)
        sys.exit(1)
    
    if not (input_path / "metadata.json").exists():
        print(f"Error: metadata.json not found in {args.input_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Call orchestrator
    try:
        results = process_document(
            input_dir=args.input_dir,
            target_size=args.target_size,
            min_size=args.min_size,
            max_size=args.max_size,
            enable_merging=args.enable_merging,
            verbose=args.verbose
        )
        
        # Success
        if results:
            print(f"\n✓ Processing complete!")
            print(f"  Document: {results['document']}")
            print(f"  Total pages: {results['total_pages']}")
            print(f"  Total chunks: {results['total_chunks']}")
            print(f"  Output: {results['output_path']}")
            sys.exit(0)
        else:
            print("\n✗ Processing failed - see logs for details", file=sys.stderr)
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n\nProcessing interrupted by user", file=sys.stderr)
        sys.exit(130)
    
    except Exception as e:
        print(f"\n✗ Fatal error: {e}", file=sys.stderr)
        print("See log file for full traceback", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
