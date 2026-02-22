#!/usr/bin/env python3
"""
Step 1: Deploy CloudFormation Stack
Creates: VPC, ECS Cluster, S3 Bucket, DynamoDB, Lambda, etc.

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
TEMPLATE_FILE = "1_ray-pipeline-cloudformation.yaml"
PARAMS_FILE = "cloudformation-parameters.json"


def deploy_cloudformation():
    """Deploy CloudFormation stack."""
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
    
    print(f"Stack Name: {STACK_NAME}")
    print(f"Template: {TEMPLATE_FILE}")
    print(f"Parameters: {PARAMS_FILE}")
    print(f"Region: {REGION}\n")
    
    # Deploy stack
    cmd = [
        "aws", "cloudformation", "create-stack",
        "--stack-name", STACK_NAME,
        "--template-body", f"file://{TEMPLATE_FILE}",
        "--parameters", f"file://{PARAMS_FILE}",
        "--capabilities", "CAPABILITY_NAMED_IAM",
        "--region", REGION
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        stack_info = json.loads(result.stdout)
        stack_id = stack_info['StackId']
        
        print(f"✅ Stack creation initiated!")
        print(f"   Stack ID: {stack_id}\n")
        
        print("⏳ Waiting for S3 bucket to be created (~2 minutes)...")
        print("   (Stack will continue creating in background)\n")
        
        print("Monitor progress:")
        print(f"   aws cloudformation describe-stacks --stack-name {STACK_NAME}\n")
        
        return True
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr
        if "AlreadyExistsException" in error_msg:
            print(f"⚠️  Stack '{STACK_NAME}' already exists!\n")
            print("Options:")
            print(f"  1. Delete it: aws cloudformation delete-stack --stack-name {STACK_NAME}")
            print(f"  2. Update it: (use update-stack command)")
            print(f"  3. Use different name in cloudformation-parameters.json\n")
        else:
            print(f"❌ Deployment failed:\n{error_msg}")
        return False


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
        sys.exit(1)


if __name__ == "__main__":
    main()
