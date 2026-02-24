#!/usr/bin/env python3
"""
Step 1: Deploy CloudFormation Stack
Creates: VPC, ECS Cluster, S3 Bucket, DynamoDB, Lambda, etc.

FIX: Template exceeds CloudFormation's 51,200-byte inline limit.
     We upload it to S3 first and use --template-url instead of --template-body.

Usage:
    python step1_deploy_cloudformation.py
"""

import subprocess
import json
import sys
import boto3
import os
from pathlib import Path
from datetime import datetime


# Configuration
STACK_NAME    = "ray-document-pipeline"
REGION        = "us-east-1"
TEMPLATE_FILE = "1_ray-pipeline-cloudformation-public.yaml"
PARAMS_FILE   = "cloudformation-parameters.json"


def get_account_id() -> str:
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def upload_template_to_s3(account_id: str) -> str:
    """
    Upload the CFN template to S3 and return the https:// URL.
    CloudFormation --template-body limit is 51,200 bytes.
    --template-url has no practical size limit (up to 1 MB).
    """
    # Reuse the pipeline bucket (already exists after first deploy)
    # On first deploy it won't exist yet, so we create a staging bucket
    staging_bucket = f"cfn-templates-{account_id}-{REGION}"
    key = f"{STACK_NAME}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.yaml"

    s3 = boto3.client("s3", region_name=REGION)

    # Create staging bucket if it doesn't exist
    try:
        s3.head_bucket(Bucket=staging_bucket)
    except Exception:
        print(f"   Creating staging bucket: {staging_bucket}")
        try:
            if REGION == "us-east-1":
                s3.create_bucket(Bucket=staging_bucket)
            else:
                s3.create_bucket(
                    Bucket=staging_bucket,
                    CreateBucketConfiguration={"LocationConstraint": REGION}
                )
            # Block public access
            s3.put_public_access_block(
                Bucket=staging_bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True
                }
            )
        except Exception as e:
            raise RuntimeError(f"Could not create staging bucket: {e}")

    template_path = Path(TEMPLATE_FILE)
    template_size = template_path.stat().st_size
    print(f"   Template size: {template_size:,} bytes (limit for inline: 51,200)")
    print(f"   Uploading → s3://{staging_bucket}/{key}")

    s3.upload_file(str(template_path), staging_bucket, key)

    url = f"https://{staging_bucket}.s3.{REGION}.amazonaws.com/{key}"
    print(f"   Template URL: {url}")
    return url


def stack_exists(stack_name: str):
    cf = boto3.client("cloudformation", region_name=REGION)
    try:
        resp = cf.describe_stacks(StackName=stack_name)
        return resp["Stacks"][0]["StackStatus"]
    except Exception:
        return None


def load_parameters() -> list:
    with open(PARAMS_FILE) as f:
        return json.load(f)


def deploy_cloudformation():
    print("\n" + "=" * 70)
    print("  STEP 1: DEPLOYING CLOUDFORMATION STACK")
    print("=" * 70 + "\n")

    # Pre-flight checks
    if not Path(TEMPLATE_FILE).exists():
        print(f"❌ Template file not found: {TEMPLATE_FILE}")
        return False
    if not Path(PARAMS_FILE).exists():
        print(f"❌ Parameters file not found: {PARAMS_FILE}")
        return False

    account_id = get_account_id()
    print(f"Stack Name : {STACK_NAME}")
    print(f"Template   : {TEMPLATE_FILE}")
    print(f"Parameters : {PARAMS_FILE}")
    print(f"Region     : {REGION}")
    print(f"Account    : {account_id}\n")

    # Upload template to S3
    print("Uploading template to S3 (bypasses 51KB inline limit)...")
    try:
        template_url = upload_template_to_s3(account_id)
    except Exception as e:
        print(f"❌ Failed to upload template: {e}")
        return False

    # Decide create vs update
    existing_status = stack_exists(STACK_NAME)
    if existing_status:
        print(f"\n⚠️  Stack '{STACK_NAME}' already exists (status: {existing_status})")
        action = "update-stack"
        waiter_name = "stack_update_complete"
        print("   → Running update-stack\n")
    else:
        action = "create-stack"
        waiter_name = "stack_create_complete"
        print(f"\nAction     : {action}\n")

    # Build and run command
    params = load_parameters()

    cmd = [
        "aws", "cloudformation", action,
        "--stack-name", STACK_NAME,
        "--template-url", template_url,
        "--parameters", json.dumps(params),
        "--capabilities", "CAPABILITY_NAMED_IAM",
        "--region", REGION
    ]

    print("Submitting stack to CloudFormation...")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        out = json.loads(result.stdout) if result.stdout.strip() else {}
        stack_id = out.get("StackId", "(check AWS console)")
        print(f"✅ Stack {action.replace('-stack','')} initiated!")
        print(f"   Stack ID: {stack_id}\n")

    except subprocess.CalledProcessError as e:
        err = e.stderr or e.stdout or str(e)
        if "No updates are to be performed" in err:
            print("✅ Stack is already up to date — no changes needed.\n")
            return True
        print(f"❌ CloudFormation {action} failed:\n{err}")
        return False

    # Wait for completion
    print(f"⏳ Waiting for stack to complete (~10-15 min)...")
    print(f"   Monitor: aws cloudformation describe-stacks --stack-name {STACK_NAME} --query 'Stacks[0].StackStatus'\n")

    cf = boto3.client("cloudformation", region_name=REGION)
    try:
        waiter = cf.get_waiter(waiter_name)
        waiter.wait(
            StackName=STACK_NAME,
            WaiterConfig={"Delay": 30, "MaxAttempts": 40}
        )
        print(f"\n✅ Stack completed successfully!\n")
        return True
    except Exception as e:
        # Print last few events to show what failed
        print(f"\n❌ Stack did not complete: {e}")
        try:
            events = cf.describe_stack_events(StackName=STACK_NAME)["StackEvents"]
            failed = [e for e in events if "FAILED" in e.get("ResourceStatus", "")][:5]
            if failed:
                print("\nFailed resources:")
                for ev in failed:
                    print(f"  {ev['LogicalResourceId']}: {ev.get('ResourceStatusReason','')}")
        except Exception:
            pass
        return False


def main():
    success = deploy_cloudformation()
    if success:
        print("=" * 70)
        print("  ✅ Step 1 Complete")
        print("=" * 70 + "\n")
        print("Next: Run step2_download_clinical_trials.py\n")
        sys.exit(0)
    else:
        print("\n❌ Step 1 Failed\n")
        print("Fix the issue and re-run: python step1_deploy_cloudformation.py\n")
        sys.exit(1)


if __name__ == "__main__":
    main()