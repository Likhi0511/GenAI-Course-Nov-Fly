#!/usr/bin/env python3
"""
Step 3: Upload PDFs to S3
Uploads clinical trial PDFs to the S3 bucket created by CloudFormation.

FIX 4: Reads the actual bucket name from CloudFormation stack outputs instead
       of hard-coding it. The template appends AccountId to the bucket name
       (e.g. ray-ingestion-prudhvi-2026-107282186797). Hard-coding just
       "ray-ingestion-prudhvi-2026" caused every upload to fail with NoSuchBucket.

Usage:
    python step3_upload_to_s3.py
"""

import subprocess
import sys
from pathlib import Path


STACK_NAME    = "ray-document-pipeline"
REGION        = "us-east-1"
SOURCE_FOLDER = "clinical_trials_20"


def get_bucket_name_from_stack():
    """
    Read the actual S3 bucket name from CloudFormation outputs.

    FIX 4: The CloudFormation template creates the bucket as:
        <S3BucketName>-<AccountId>   e.g. ray-ingestion-prudhvi-2026-107282186797
    The AccountId suffix is added for global uniqueness.
    Hard-coding the name without AccountId causes NoSuchBucket on upload.
    Reading from stack outputs always gives the real name regardless of AccountId.
    """
    print("Reading S3 bucket name from CloudFormation stack outputs...")
    try:
        result = subprocess.run([
            "aws", "cloudformation", "describe-stacks",
            "--stack-name", STACK_NAME,
            "--query", "Stacks[0].Outputs[?OutputKey=='S3BucketName'].OutputValue",
            "--output", "text",
            "--region", REGION,
        ], capture_output=True, text=True, check=True)

        bucket_name = result.stdout.strip()

        if not bucket_name or bucket_name == "None":
            print(f"❌ Could not read S3BucketName from stack outputs.")
            print(f"   Is the stack fully deployed? Check:")
            print(f"   aws cloudformation describe-stacks --stack-name {STACK_NAME}")
            return None

        print(f"   ✓ Bucket: {bucket_name}\n")
        return bucket_name

    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to query CloudFormation stack: {e.stderr}")
        print(f"   Make sure step1 completed successfully first.")
        return None


def upload_to_s3(s3_bucket: str):
    """Upload PDFs from SOURCE_FOLDER to s3://<bucket>/input/"""
    print("\n" + "="*70)
    print("  STEP 3: UPLOADING TO S3")
    print("="*70 + "\n")

    # Verify source folder and PDFs exist
    if not Path(SOURCE_FOLDER).exists():
        print(f"❌ Source folder not found: {SOURCE_FOLDER}/")
        print(f"   Run step2_download_clinical_trials.py first\n")
        return False

    pdf_count = len(list(Path(SOURCE_FOLDER).glob("*.pdf")))
    if pdf_count == 0:
        print(f"❌ No PDFs found in {SOURCE_FOLDER}/")
        return False

    print(f"Source      : {SOURCE_FOLDER}/")
    print(f"Destination : s3://{s3_bucket}/input/")
    print(f"Files       : {pdf_count} PDFs\n")

    # aws s3 sync uploads new/changed files, skips already-uploaded ones.
    # Safe to re-run — idempotent.
    cmd = [
        "aws", "s3", "sync",
        SOURCE_FOLDER,
        f"s3://{s3_bucket}/input/",
        "--exclude", "*.md",
        "--region", REGION,
    ]

    try:
        subprocess.run(cmd, check=True)
        print(f"\n✅ Upload complete! {pdf_count} PDFs uploaded to s3://{s3_bucket}/input/\n")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Upload failed: {e}")
        print(f"   Verify the bucket exists: aws s3 ls s3://{s3_bucket}/")
        return False


def main():
    # Read the real bucket name — never hard-code it
    s3_bucket = get_bucket_name_from_stack()
    if not s3_bucket:
        sys.exit(1)

    success = upload_to_s3(s3_bucket)

    if success:
        print("="*70)
        print("  ✅ Step 3 Complete")
        print("="*70 + "\n")
        print("All PDFs uploaded. The Lambda trigger will create a DynamoDB")
        print("PENDING record for each PDF automatically.")
        print("\nMonitor the pipeline:")
        print(f"  aws dynamodb scan --table-name {STACK_NAME}-control")
        print(f"  aws logs tail /ecs/{STACK_NAME}/ray-head --follow\n")
        sys.exit(0)
    else:
        print("❌ Step 3 Failed\n")
        sys.exit(1)


if __name__ == "__main__":
    main()