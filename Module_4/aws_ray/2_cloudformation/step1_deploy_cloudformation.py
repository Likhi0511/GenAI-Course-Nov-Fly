#!/usr/bin/env python3
"""
Step 1: Deploy CloudFormation Stack
Creates or updates: VPC, ECS Cluster, S3 Bucket, DynamoDB, Lambda, etc.

Auto-detects whether to create or update based on whether the stack exists.

Usage:
    python step1_deploy_cloudformation.py
"""

import subprocess
import json
import sys
from pathlib import Path


# Configuration
STACK_NAME = "ray-document-pipeline"
REGION = "us-east-1"
TEMPLATE_FILE = "1_ray-pipeline-cloudformation-public.yaml"
PARAMS_FILE = "cloudformation-parameters.json"


def stack_exists():
    """Return True if the CloudFormation stack already exists."""
    result = subprocess.run(
        ["aws", "cloudformation", "describe-stacks",
         "--stack-name", STACK_NAME, "--region", REGION],
        capture_output=True, text=True
    )
    return result.returncode == 0


def deploy_cloudformation():
    """Create or update the CloudFormation stack, then wait for completion."""
    print("\n" + "="*70)
    print("  STEP 1: DEPLOYING CLOUDFORMATION STACK")
    print("="*70 + "\n")

    # Check files exist
    if not Path(TEMPLATE_FILE).exists():
        print(f"❌ Template file not found: {TEMPLATE_FILE}")
        return False

    if not Path(PARAMS_FILE).exists():
        print(f"❌ Parameters file not found: {PARAMS_FILE}")
        return False

    # Auto-detect create vs update
    exists = stack_exists()
    action = "update-stack" if exists else "create-stack"
    wait_cmd = "stack-update-complete" if exists else "stack-create-complete"

    print(f"Stack Name : {STACK_NAME}")
    print(f"Template   : {TEMPLATE_FILE}")
    print(f"Parameters : {PARAMS_FILE}")
    print(f"Region     : {REGION}")
    print(f"Action     : {action}\n")

    cmd = [
        "aws", "cloudformation", action,
        "--stack-name", STACK_NAME,
        "--template-body", f"file://{TEMPLATE_FILE}",
        "--parameters", f"file://{PARAMS_FILE}",
        "--capabilities", "CAPABILITY_NAMED_IAM",
        "--region", REGION
    ]

    print("Submitting stack to CloudFormation...")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        info = json.loads(result.stdout)
        stack_id = info.get('StackId', 'N/A')
        print(f"✅ Stack {action} initiated!")
        print(f"   Stack ID: {stack_id}\n")

    except subprocess.CalledProcessError as e:
        err = e.stderr
        if "No updates are to be performed" in err:
            print("ℹ️  Stack is already up to date — no changes needed.\n")
            return True
        print(f"❌ CloudFormation {action} failed:\n{err}")
        return False

    # Wait for completion — blocks until stack reaches stable state
    print(f"⏳ Waiting for {wait_cmd} (~10-15 min)...")
    print(f"   Monitor: aws cloudformation describe-stacks --stack-name {STACK_NAME}\n")

    wait_result = subprocess.run(
        ["aws", "cloudformation", "wait", wait_cmd,
         "--stack-name", STACK_NAME, "--region", REGION],
        capture_output=True, text=True
    )

    if wait_result.returncode != 0:
        print(f"❌ CloudFormation deploy failed (exit code {wait_result.returncode})")
        print(f"   Check events: aws cloudformation describe-stack-events --stack-name {STACK_NAME} --region {REGION}")
        return False

    print(f"✅ Stack {action.replace('-stack', '')} complete!\n")
    return True


def main():
    success = deploy_cloudformation()

    if success:
        print("="*70)
        print("  ✅ Step 1 Complete")
        print("="*70 + "\n")
        print("Next: Run step2_download_clinical_trials.py\n")
        sys.exit(0)
    else:
        print("❌ Step 1 Failed\n")
        print(f"Fix the issue and re-run: python step1_deploy_cloudformation.py")
        sys.exit(1)


if __name__ == "__main__":
    main()