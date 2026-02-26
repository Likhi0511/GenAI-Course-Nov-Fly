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


def run_step(script_name, description, extra_args=None):
    """Run a single deployment step script. Returns True on success."""
    print("\n" + "="*70)
    print(f"  Running: {description}")
    print("="*70 + "\n")

    cmd = [sys.executable, script_name] + (extra_args or [])
    try:
        subprocess.run(cmd, check=True)
        print(f"\n✅ {description} — SUCCESS\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} — FAILED (exit code {e.returncode})\n")
        return False


def main():
    print("\n" + "="*70)
    print("  RAG PIPELINE DEPLOYMENT ORCHESTRATOR")
    print("="*70)
    print("\nThis executes 4 steps:")
    print("  Step 1 : Deploy CloudFormation         (~20 min — EKS cluster creation)")
    print("  Step 1b: Setup EKS                     (~8 min  — KubeRay + RayCluster)")
    print("  Step 2 : Download Clinical Trial PDFs")
    print("  Step 3 : Upload PDFs to S3")
    print("\nTotal time: ~30 minutes")
    print("\nNote: Steps 1 + 1b replace what CloudFormation did alone on ECS.")
    print("      ECS auto-wired services; EKS needs KubeRay installed separately.")
    print("="*70 + "\n")

    response = input("Continue? (y/n): ")
    if response.strip().lower() != 'y':
        print("Aborted.")
        return

    # ------------------------------------------------------------------
    # Step 1: Deploy CloudFormation
    # ------------------------------------------------------------------
    # Creates: VPC, EKS cluster, node group, IRSA, S3, DynamoDB, Lambda.
    # Waits for CREATE_COMPLETE before returning.
    # Note: unlike ECS, this does NOT start any containers yet —
    # that happens in Step 1b via KubeRay.
    if not run_step("step1_deploy_cloudformation.py", "Step 1: Deploy CloudFormation"):
        print("⚠️  CloudFormation deployment failed!")
        print("Fix the issue and re-run: python step1_deploy_cloudformation.py")
        return

    # ------------------------------------------------------------------
    # Step 1b: Setup EKS (KubeRay operator + RayCluster)
    # ------------------------------------------------------------------
    # ECS: CloudFormation auto-created ECS services + service discovery
    #      + Step Scaling + CloudWatch metric Lambda in one shot.
    # EKS: CloudFormation only creates the cluster. This step does:
    #   - Configure kubectl for the new cluster
    #   - Install cert-manager + KubeRay operator via Helm
    #   - Apply namespace / ServiceAccount (IRSA) / RBAC
    #   - Copy API keys from AWS Secrets Manager into a K8s Secret
    #   - Deploy RayCluster manifest (head + workers, autoscaling enabled)
    #   - Wait for head pod Ready
    if not run_step("step1b_setup_eks.py", "Step 1b: Setup EKS (KubeRay + RayCluster)", extra_args=["--yes"]):
        print("⚠️  EKS setup failed!")
        print("Fix the issue and re-run: python step1b_setup_eks.py")
        return

    # ------------------------------------------------------------------
    # Step 2: Download Clinical Trials
    # ------------------------------------------------------------------
    # Downloads PDFs to local disk — does not need AWS.
    if not run_step("step2_download_clinical_trials.py", "Step 2: Download Clinical Trials"):
        print("⚠️  Download failed!")
        print("Retry: python step2_download_clinical_trials.py")
        print("Then continue: python step3_upload_to_s3.py")
        return

    # ------------------------------------------------------------------
    # Step 3: Upload to S3
    # ------------------------------------------------------------------
    # Reads bucket name from CloudFormation outputs — no hard-coded value.
    # Lambda trigger fires on each upload → creates PENDING DynamoDB records
    # → ray_orchestrator.py (running in head pod) picks them up.
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
    print("  ✓ CloudFormation stack (VPC, EKS cluster, S3, DynamoDB, Lambda)")
    print("  ✓ KubeRay operator + RayCluster deployed on EKS")
    print("  ✓ Clinical trial PDFs uploaded to S3")
    print("  ✓ Lambda auto-created PENDING records in DynamoDB")
    print("  ✓ ray_orchestrator.py running inside head pod\n")
    print("The orchestrator polls DynamoDB every 30s and distributes")
    print("work across Ray workers via ThreadPoolExecutor.")
    print("\nMonitor:")
    print("  kubectl get pods -n ray-pipeline")
    print("  kubectl logs -f -n ray-pipeline -l ray.io/node-type=head")
    print("  aws dynamodb scan --table-name ray-document-pipeline-control\n")
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