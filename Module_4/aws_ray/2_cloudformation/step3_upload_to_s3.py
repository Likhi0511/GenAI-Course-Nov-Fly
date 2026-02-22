#!/usr/bin/env python3
"""
Step 3: Upload PDFs to S3
Uploads clinical trial PDFs to S3 bucket

Usage:
    python step3_upload_to_s3.py
"""

import subprocess
import sys
from pathlib import Path


S3_BUCKET = "ray-ingestion-prudhvi-2026"
REGION = "us-east-1"
SOURCE_FOLDER = "clinical_trials_20"


def upload_to_s3():
    """Upload PDFs to S3."""
    print("\n" + "="*70)
    print("  STEP 3: UPLOADING TO S3")
    print("="*70 + "\n")
    
    # Check folder exists
    if not Path(SOURCE_FOLDER).exists():
        print(f"❌ Source folder not found: {SOURCE_FOLDER}")
        print(f"   Run step2_download_clinical_trials.py first\n")
        return False
    
    # Count PDFs
    pdf_count = len(list(Path(SOURCE_FOLDER).glob("*.pdf")))
    if pdf_count == 0:
        print(f"❌ No PDFs found in {SOURCE_FOLDER}/")
        return False
    
    print(f"Source: {SOURCE_FOLDER}/")
    print(f"Destination: s3://{S3_BUCKET}/input/")
    print(f"Files: {pdf_count} PDFs\n")
    
    # Upload to S3
    cmd = [
        "aws", "s3", "sync",
        SOURCE_FOLDER,
        f"s3://{S3_BUCKET}/input/",
        "--exclude", "*.md",
        "--region", REGION
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        print(f"✅ Upload complete! {pdf_count} PDFs uploaded\n")
        return True
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr
        if "NoSuchBucket" in error_msg:
            print(f"❌ S3 bucket doesn't exist yet!")
            print(f"   The CloudFormation stack might still be creating.")
            print(f"   Wait a few minutes and try again.\n")
            print(f"   Check bucket: aws s3 ls s3://{S3_BUCKET}/\n")
        else:
            print(f"❌ Upload failed:\n{error_msg}")
        return False


def main():
    success = upload_to_s3()
    
    if success:
        print("="*70)
        print("  ✅ Step 3 Complete")
        print("="*70 + "\n")
        print("All PDFs uploaded to S3!")
        print("CloudFormation stack will complete in ~15-20 minutes total.\n")
        print("Monitor stack:")
        print("  aws cloudformation describe-stacks --stack-name ray-document-pipeline\n")
        sys.exit(0)
    else:
        print("❌ Step 3 Failed\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
