#!/usr/bin/env python3
"""
Orchestrator: Run All Deployment Steps
Executes each step module in sequence.

FIX 6b (orchestrator side): Removed the blind time.sleep(120) between
step1 and step2. step1 now waits for the full stack to be ready before
returning, so no sleep is needed here. The sleep was also too short — the
stack takes 10-15 min, not 2 min.

Usage:
    python orchestrator.py
"""

import subprocess
import sys


def run_step(script_name, description):
    """Run a single deployment step script. Returns True on success."""
    print("\n" + "="*70)
    print(f"  Running: {description}")
    print("="*70 + "\n")

    try:
        subprocess.run([sys.executable, script_name], check=True)
        print(f"\n✅ {description} — SUCCESS\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} — FAILED (exit code {e.returncode})\n")
        return False


def main():
    print("\n" + "="*70)
    print("  RAG PIPELINE DEPLOYMENT ORCHESTRATOR")
    print("="*70)
    print("\nThis executes 3 steps:")
    print("  Step 1: Deploy CloudFormation  (~10-15 min, waits for completion)")
    print("  Step 2: Download 10 Clinical Trial PDFs")
    print("  Step 3: Upload PDFs to S3")
    print("\nTotal time: ~15-20 minutes")
    print("="*70 + "\n")

    response = input("Continue? (y/n): ")
    if response.strip().lower() != 'y':
        print("Aborted.")
        return

    # ------------------------------------------------------------------
    # Step 1: Deploy CloudFormation
    # ------------------------------------------------------------------
    # This step now blocks until the stack reaches CREATE_COMPLETE.
    # No sleep needed after it — the bucket is guaranteed to exist when
    # this function returns.
    if not run_step("step1_deploy_cloudformation.py", "Step 1: Deploy CloudFormation"):
        print("⚠️  CloudFormation deployment failed!")
        print("Fix the issue and re-run: python step1_deploy_cloudformation.py")
        return

    # ------------------------------------------------------------------
    # Step 2: Download Clinical Trials
    # ------------------------------------------------------------------
    # Downloads PDFs to local disk — does not need AWS, runs in parallel
    # with any remaining stack operations (there are none at this point).
    if not run_step("step2_download_clinical_trials.py", "Step 2: Download Clinical Trials"):
        print("⚠️  Download failed!")
        print("Retry: python step2_download_clinical_trials.py")
        print("Then continue: python step3_upload_to_s3.py")
        return

    # ------------------------------------------------------------------
    # Step 3: Upload to S3
    # ------------------------------------------------------------------
    # Reads the actual bucket name from CloudFormation outputs — no
    # hard-coded bucket name. Stack is already fully ready from Step 1.
    if not run_step("step3_upload_to_s3.py", "Step 3: Upload PDFs to S3"):
        print("⚠️  Upload failed!")
        print("Retry: python step3_upload_to_s3.py")
        return

    # ------------------------------------------------------------------
    # All done
    # ------------------------------------------------------------------
    print("\n" + "="*70)
    print("  ✅ DEPLOYMENT COMPLETE!")
    print("="*70 + "\n")
    print("What was deployed:")
    print("  ✓ CloudFormation stack (VPC, ECS, S3, DynamoDB, Lambda)")
    print("  ✓ Clinical trial PDFs uploaded to S3")
    print("  ✓ Lambda auto-created PENDING records in DynamoDB")
    print("  ✓ Ray cluster initializing on ECS\n")
    print("The orchestrator will start picking up documents automatically.")
    print("\nMonitor:")
    print("  aws dynamodb scan --table-name ray-document-pipeline-control")
    print("  aws logs tail /ecs/ray-document-pipeline/ray-head --follow\n")
    print("Test questions once processing completes:")
    print("  • What is the Remdesivir trial about?")
    print("  • How many participants in the Pfizer vaccine trial?")
    print("  • Compare the COVID vaccine protocols\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()