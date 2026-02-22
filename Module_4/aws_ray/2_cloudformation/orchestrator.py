#!/usr/bin/env python3
"""
Orchestrator: Run All Deployment Steps
Executes each step module in sequence

Usage:
    python orchestrator.py
"""

import subprocess
import time
import sys


def run_step(step_num, script_name, description):
    """Run a deployment step."""
    print("\n" + "="*70)
    print(f"  🚀 Running: {description}")
    print("="*70 + "\n")
    
    cmd = [sys.executable, script_name]
    
    try:
        result = subprocess.run(cmd, check=True)
        print(f"\n✅ {description} - SUCCESS\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} - FAILED")
        print(f"   Exit code: {e.returncode}\n")
        return False


def main():
    print("\n" + "="*70)
    print("  🎯 RAG PIPELINE DEPLOYMENT ORCHESTRATOR")
    print("="*70)
    print("\nThis will execute 3 steps:")
    print("  1. Deploy CloudFormation (creates infrastructure)")
    print("  2. Download Clinical Trials (20 PDFs)")
    print("  3. Upload to S3 (ingestion bucket)")
    print("\nTotal time: ~20-25 minutes")
    print("="*70 + "\n")
    
    response = input("Continue? (y/n): ")
    if response.lower() != 'y':
        print("Aborted.")
        return
    
    # Step 1: Deploy CloudFormation
    if not run_step(1, "step1_deploy_cloudformation.py", "Step 1: Deploy CloudFormation"):
        print("\n⚠️  CloudFormation deployment failed!")
        print("Fix the issue and run: python step1_deploy_cloudformation.py")
        return
    
    # Wait for S3 bucket to be created
    print("\n⏳ Waiting 2 minutes for S3 bucket to be ready...")
    time.sleep(120)
    
    # Step 2: Download Clinical Trials
    if not run_step(2, "step2_download_clinical_trials.py", "Step 2: Download Clinical Trials"):
        print("\n⚠️  Download failed!")
        print("You can retry: python step2_download_clinical_trials.py")
        print("Or continue manually with: python step3_upload_to_s3.py")
        return
    
    # Step 3: Upload to S3
    if not run_step(3, "step3_upload_to_s3.py", "Step 3: Upload to S3"):
        print("\n⚠️  Upload failed!")
        print("The S3 bucket might not be ready yet.")
        print("Wait a few minutes and retry: python step3_upload_to_s3.py")
        return
    
    # All done!
    print("\n" + "="*70)
    print("  ✅ DEPLOYMENT COMPLETE!")
    print("="*70 + "\n")
    
    print("What was deployed:")
    print("  ✓ CloudFormation stack (VPC, ECS, S3, DynamoDB, Lambda)")
    print("  ✓ 20 clinical trial PDFs uploaded to S3")
    print("  ✓ Ray cluster initializing\n")
    
    print("Stack will complete in ~15-20 minutes total.")
    print("\nMonitor progress:")
    print("  aws cloudformation describe-stacks --stack-name ray-document-pipeline")
    print("  aws s3 ls s3://ray-ingestion-prudhvi-2026/input/\n")
    
    print("Once stack shows CREATE_COMPLETE, test with:")
    print("  • What is the Remdesivir trial about?")
    print("  • How many participants in Pfizer vaccine trial?")
    print("  • Compare COVID vaccine protocols\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
