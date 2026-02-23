#!/usr/bin/env python3
"""
Step 1: Deploy CloudFormation Stack
Creates: VPC, ECS Cluster, S3 Bucket, DynamoDB, Lambda, etc.

FIX 6a: Uses 'aws cloudformation deploy' instead of 'create-stack'.
        Handles first-time create AND subsequent updates automatically.
        No more AlreadyExistsException on re-runs — safe to run multiple times.

FIX 6b: Waits for stack to reach CREATE_COMPLETE before returning.
        Previously returned immediately after submitting, then orchestrator.py
        waited only 2 minutes before uploading PDFs. Stack takes 10-15 minutes
        so uploads reliably failed with NoSuchBucket.

Usage:
    python step1_deploy_cloudformation.py
"""

import subprocess
import sys
from pathlib import Path


# Configuration
STACK_NAME    = "ray-document-pipeline"
REGION        = "us-east-1"
TEMPLATE_FILE = "1_ray-pipeline-cloudformation-public.yaml"
PARAMS_FILE   = "cloudformation-parameters.json"


def deploy_cloudformation():
    """
    Deploy (or update) the CloudFormation stack and wait for full completion.
    Returns True if the stack reached CREATE_COMPLETE / UPDATE_COMPLETE,
    False on any error.
    """
    print("\n" + "="*70)
    print("  STEP 1: DEPLOYING CLOUDFORMATION STACK")
    print("="*70 + "\n")

    # Verify required files exist before calling AWS
    if not Path(TEMPLATE_FILE).exists():
        print(f"❌ Template file not found: {TEMPLATE_FILE}")
        return False
    if not Path(PARAMS_FILE).exists():
        print(f"❌ Parameters file not found: {PARAMS_FILE}")
        return False

    print(f"Stack Name : {STACK_NAME}")
    print(f"Template   : {TEMPLATE_FILE}")
    print(f"Parameters : {PARAMS_FILE}")
    print(f"Region     : {REGION}\n")

    # ------------------------------------------------------------------
    # STEP 1A: Deploy using 'aws cloudformation deploy'
    # ------------------------------------------------------------------
    # 'deploy' calls create-stack on first run, update-stack on subsequent
    # runs — handles both cases without AlreadyExistsException.
    # --no-fail-on-empty-changeset: re-running with no changes exits 0 cleanly.
    deploy_cmd = [
        "aws", "cloudformation", "deploy",
        "--stack-name", STACK_NAME,
        "--template-file", TEMPLATE_FILE,
        "--parameter-overrides", f"file://{PARAMS_FILE}",
        "--capabilities", "CAPABILITY_NAMED_IAM",
        "--region", REGION,
        "--no-fail-on-empty-changeset",
    ]

    print("Submitting stack to CloudFormation...")
    try:
        subprocess.run(deploy_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ CloudFormation deploy failed (exit code {e.returncode})")
        print(f"   Check events: aws cloudformation describe-stack-events "
              f"--stack-name {STACK_NAME} --region {REGION}")
        return False

    # ------------------------------------------------------------------
    # STEP 1B: Wait for full stack completion
    # ------------------------------------------------------------------
    # 'deploy' returns when the change set is SUBMITTED, not when the stack
    # is DONE. We must block here — otherwise step3 runs immediately and
    # tries to upload to a bucket that does not exist yet.
    # Stack typically takes 10-15 minutes.
    print("\nWaiting for stack to reach CREATE_COMPLETE (10-15 min)...")
    print("Watch progress in another terminal:")
    print(f"  aws cloudformation describe-stack-events "
          f"--stack-name {STACK_NAME} --region {REGION}\n")

    # Try create-complete; if stack already existed it will be an update
    for waiter in ["stack-create-complete", "stack-update-complete"]:
        r = subprocess.run([
            "aws", "cloudformation", "wait", waiter,
            "--stack-name", STACK_NAME,
            "--region", REGION,
        ])
        if r.returncode == 0:
            print(f"\n✅ Stack fully deployed and ready!\n")
            break
    else:
        print(f"\n❌ Stack did not complete. Check CloudFormation Console -> Events.")
        return False

    # ------------------------------------------------------------------
    # STEP 1C: Print actual S3 bucket name (AccountId is appended by template)
    # ------------------------------------------------------------------
    try:
        r = subprocess.run([
            "aws", "cloudformation", "describe-stacks",
            "--stack-name", STACK_NAME,
            "--query", "Stacks[0].Outputs[?OutputKey=='S3BucketName'].OutputValue",
            "--output", "text",
            "--region", REGION,
        ], capture_output=True, text=True, check=True)
        bucket = r.stdout.strip()
        if bucket:
            print(f"   S3 Bucket: {bucket}")
            print(f"   (step3 reads this automatically from stack outputs)\n")
    except Exception:
        pass

    return True


def main():
    success = deploy_cloudformation()
    if success:
        print("="*70)
        print("  ✅ Step 1 Complete — stack is fully deployed")
        print("="*70 + "\n")
        print("Next: Run step2_download_clinical_trials.py\n")
        sys.exit(0)
    else:
        print("❌ Step 1 Failed\n")
        sys.exit(1)


if __name__ == "__main__":
    main()