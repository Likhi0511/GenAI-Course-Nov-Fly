#!/usr/bin/env python3
"""
Step 1b: Setup EKS — Install KubeRay + Deploy RayCluster
=========================================================

ECS vs EKS deployment comparison
----------------------------------
On ECS, CloudFormation did everything in one shot:
  - Created ECS services (head + worker)
  - Wired up service discovery automatically
  - Configured Step Scaling policies
  - ECS pulled the image and started containers

On EKS, CloudFormation only creates the infrastructure:
  - VPC, EKS cluster, node group, DynamoDB, S3, Lambda, IAM
  - The CLUSTER is running but nothing is scheduled on it yet

THIS script does the EKS equivalent of "start the Ray cluster":
  A. Configure kubectl to talk to the new cluster
  B. Install KubeRay operator via Helm
  C. Apply Kubernetes supporting resources (namespace, ServiceAccount + IRSA, RBAC)
  D. Pull API keys from AWS Secrets Manager → create Kubernetes Secret
  E. Fill placeholders in ray-cluster.yaml → apply RayCluster
  F. Wait for Ray head pod to be ready + print dashboard URL

Run this AFTER step1_deploy_cloudformation.py completes.

Usage:
    python step1b_setup_eks.py

Time: ~5-8 minutes (mostly Helm installs + image pull)
"""

import subprocess
import sys
import argparse
import json
import time
import tempfile
import os
import shutil
from pathlib import Path

try:
    import boto3
except ImportError:
    print("❌ boto3 not installed. Run: pip install boto3")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — must match eks-cluster.yaml and eks-parameters.json
# ─────────────────────────────────────────────────────────────────────────────
STACK_NAME          = "ray-document-pipeline"
REGION              = "us-east-1"
K8S_NAMESPACE       = "ray-pipeline"
KUBERAY_VERSION     = "1.1.0"
KUBERAY_NAMESPACE   = "kuberay-operator"

# Path to Kubernetes manifests — relative to this script's location in 2_cloudformation/
# Adjust if you put the manifests elsewhere
SCRIPT_DIR      = Path(__file__).parent
CFN_DIR         = SCRIPT_DIR   # step1b lives in 2_cloudformation/ alongside the templates

RAY_CLUSTER_TEMPLATE = CFN_DIR / "ray-cluster.yaml"
K8S_SUPPORTING       = CFN_DIR / "k8s-supporting.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def header(msg):
    print(f"\n{'='*70}\n  {msg}\n{'='*70}\n")

def ok(msg):
    print(f"  ✅ {msg}")

def info(msg):
    print(f"  ℹ️  {msg}")

def warn(msg):
    print(f"  ⚠️  {msg}")

def fail(msg):
    print(f"  ❌ {msg}")


def run_cmd(cmd: list, check=True, capture=False, input_text=None) -> subprocess.CompletedProcess:
    """Run a shell command. Streams output unless capture=True."""
    if capture:
        return subprocess.run(
            cmd, check=check, capture_output=True, text=True, input=input_text
        )
    else:
        return subprocess.run(cmd, check=check, input=input_text, text=True)


def cfn_output(key: str) -> str:
    """Read a CloudFormation stack output value by key."""
    cf = boto3.client("cloudformation", region_name=REGION)
    resp = cf.describe_stacks(StackName=STACK_NAME)
    for output in resp["Stacks"][0].get("Outputs", []):
        if output["OutputKey"] == key:
            return output["OutputValue"]
    raise ValueError(f"CloudFormation output '{key}' not found in stack {STACK_NAME}")


def tool_exists(name: str) -> bool:
    """Check if a CLI tool is on PATH. Uses shutil.which — works on Mac, Linux, and Windows."""
    return shutil.which(name) is not None


# ─────────────────────────────────────────────────────────────────────────────
# PRE-FLIGHT
# ─────────────────────────────────────────────────────────────────────────────
def preflight_checks():
    header("PRE-FLIGHT CHECKS")

    errors = []
    for tool in ["aws", "kubectl", "helm"]:
        if tool_exists(tool):
            ok(f"{tool} found")
        else:
            fail(f"{tool} not found — install it first")
            errors.append(tool)

    for manifest in [RAY_CLUSTER_TEMPLATE, K8S_SUPPORTING]:
        if manifest.exists():
            ok(f"{manifest.name} found")
        else:
            fail(f"Manifest not found: {manifest}")
            errors.append(str(manifest))

    if errors:
        print(f"\n❌ Pre-flight failed. Fix: {errors}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# STEP A: Configure kubectl
# ─────────────────────────────────────────────────────────────────────────────
def configure_kubectl():
    header("STEP A: Configure kubectl → EKS cluster")

    cluster_name = cfn_output("EKSClusterName")
    info(f"Cluster: {cluster_name}")

    run_cmd([
        "aws", "eks", "update-kubeconfig",
        "--name", cluster_name,
        "--region", REGION,
    ])
    ok(f"kubeconfig updated — kubectl now points to {cluster_name}")

    # Wait for nodes to be Ready
    info("Waiting for EC2 nodes to be Ready (up to 5 min)...")
    run_cmd([
        "kubectl", "wait", "--for=condition=Ready",
        "nodes", "--all", "--timeout=300s"
    ])

    result = run_cmd(["kubectl", "get", "nodes", "--no-headers"], capture=True)
    node_count = len(result.stdout.strip().split("\n"))
    ok(f"{node_count} node(s) Ready")

    return cluster_name


# ─────────────────────────────────────────────────────────────────────────────
# STEP B: cert-manager (KubeRay operator dependency)
# ─────────────────────────────────────────────────────────────────────────────
# install_cert_manager() is available if you want KubeRay admission webhooks,
# but is NOT called by default — KubeRay 1.1.0 works fine without it for this pipeline.
# To enable: uncomment the install_cert_manager() call in main() and add
#            --set webhook.enabled=true to the kuberay helm install command.
def install_cert_manager():
    header("STEP B: cert-manager (optional — for KubeRay admission webhooks)")

    result = run_cmd(
        ["kubectl", "get", "namespace", "cert-manager"],
        check=False, capture=True
    )
    if result.returncode == 0:
        ok("cert-manager already installed — skipping")
        return

    run_cmd(["helm", "repo", "add", "jetstack", "https://charts.jetstack.io", "--force-update"])
    run_cmd([
        "helm", "upgrade", "--install", "cert-manager", "jetstack/cert-manager",
        "--namespace", "cert-manager",
        "--create-namespace",
        "--set", "installCRDs=true",
        "--wait", "--timeout", "5m",
    ])
    ok("cert-manager installed")


# ─────────────────────────────────────────────────────────────────────────────
# STEP B: KubeRay operator
# ─────────────────────────────────────────────────────────────────────────────
def install_kuberay():
    header(f"STEP B: KubeRay operator v{KUBERAY_VERSION}")

    # ECS equivalent: CloudFormation creating ECS services automatically
    # KubeRay replaces: ECS services + service discovery + step scaling + CloudWatch metric Lambda
    info("KubeRay replaces all of: ECS services, service discovery, Step Scaling, Lambda metric publisher")

    result = run_cmd(
        ["helm", "status", "kuberay-operator", "-n", KUBERAY_NAMESPACE],
        check=False, capture=True
    )
    if result.returncode == 0:
        ok("KubeRay operator already installed — skipping")
    else:
        run_cmd(["helm", "repo", "add", "kuberay", "https://ray-project.github.io/kuberay-helm/", "--force-update"])
        run_cmd([
            "helm", "upgrade", "--install", "kuberay-operator", "kuberay/kuberay-operator",
            "--namespace", KUBERAY_NAMESPACE,
            "--create-namespace",
            "--version", KUBERAY_VERSION,
            "--set", f"image.tag=v{KUBERAY_VERSION}",
            "--wait", "--timeout", "5m",
        ])
        ok(f"KubeRay operator v{KUBERAY_VERSION} installed")

    # Verify the RayCluster CRD was registered
    result = run_cmd(
        ["kubectl", "get", "crd", "rayclusters.ray.io"],
        check=False, capture=True
    )
    if result.returncode == 0:
        ok("RayCluster CRD registered")
    else:
        fail("RayCluster CRD not found — KubeRay install may have failed")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# STEP C: Kubernetes supporting resources
# ─────────────────────────────────────────────────────────────────────────────
def apply_supporting_resources():
    header("STEP C: Namespace, ServiceAccount (IRSA), RBAC, ResourceQuota")

    ray_pod_role_arn = cfn_output("RayPodRoleArn")
    info(f"IRSA role ARN: {ray_pod_role_arn}")

    # Fill the <RAY_POD_ROLE_ARN> placeholder in k8s-supporting.yaml
    template_content = K8S_SUPPORTING.read_text()
    filled_content   = template_content.replace("<RAY_POD_ROLE_ARN>", ray_pod_role_arn)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="k8s-supporting-filled-"
    ) as tmp:
        tmp.write(filled_content)
        tmp_path = tmp.name

    try:
        run_cmd(["kubectl", "apply", "-f", tmp_path])
    finally:
        os.unlink(tmp_path)

    ok("Namespace, ServiceAccount, RBAC, ResourceQuota, PodDisruptionBudget applied")

    # Verify IRSA annotation was set correctly
    result = run_cmd([
        "kubectl", "get", "serviceaccount", "ray-pod-sa",
        "-n", K8S_NAMESPACE,
        "-o", "jsonpath={.metadata.annotations.eks\\.amazonaws\\.com/role-arn}"
    ], capture=True)

    if result.stdout.strip() == ray_pod_role_arn:
        ok(f"IRSA annotation verified: {ray_pod_role_arn}")
    else:
        warn(f"IRSA annotation mismatch. Got: {result.stdout.strip()}")


# ─────────────────────────────────────────────────────────────────────────────
# STEP D: Kubernetes Secrets (from AWS Secrets Manager)
# ─────────────────────────────────────────────────────────────────────────────
def create_kubernetes_secrets():
    header("STEP D: Pull API keys from AWS Secrets Manager → Kubernetes Secret")

    # ECS equivalent: ECS task definition Secrets block
    # (ECS pulled directly from Secrets Manager at container start)
    # EKS equivalent: K8s Secret in the namespace, pods read via env var secretKeyRef
    info("ECS pulled secrets directly from Secrets Manager at container start.")
    info("EKS equivalent: copy once into a Kubernetes Secret in ray-pipeline namespace.")

    sm = boto3.client("secretsmanager", region_name=REGION)

    def get_secret(arn: str) -> str:
        resp = sm.get_secret_value(SecretId=arn)
        raw = resp["SecretString"]
        # Handle both plain string and JSON object ({"OPENAI_API_KEY": "sk-..."})
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return list(parsed.values())[0]
        except (json.JSONDecodeError, IndexError):
            pass
        return raw

    # Read ARNs from CloudFormation parameters file
    params_file = CFN_DIR / "eks-parameters.json"
    params      = json.loads(params_file.read_text())
    param_map   = {p["ParameterKey"]: p["ParameterValue"] for p in params}

    openai_arn   = param_map.get("OpenAISecretArn")
    pinecone_arn = param_map.get("PineconeSecretArn")

    if not openai_arn or not pinecone_arn:
        fail("OpenAISecretArn or PineconeSecretArn not found in eks-parameters.json")
        sys.exit(1)

    info("Fetching OpenAI key from Secrets Manager...")
    openai_key   = get_secret(openai_arn)

    info("Fetching Pinecone key from Secrets Manager...")
    pinecone_key = get_secret(pinecone_arn)

    # Create or update the Kubernetes Secret (idempotent via --dry-run=client | kubectl apply)
    # --dry-run=client generates the Secret manifest without hitting the API server,
    # then we pipe it to kubectl apply which creates or updates it safely.
    result = run_cmd([
        "kubectl", "create", "secret", "generic", "ray-pipeline-secrets",
        "--namespace", K8S_NAMESPACE,
        f"--from-literal=openai-api-key={openai_key}",
        f"--from-literal=pinecone-api-key={pinecone_key}",
        "--dry-run=client", "-o", "yaml",
    ], capture=True)

    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=result.stdout, text=True, check=True
    )

    ok("Kubernetes Secret 'ray-pipeline-secrets' created/updated in ray-pipeline namespace")


# ─────────────────────────────────────────────────────────────────────────────
# STEP E: Apply RayCluster
# ─────────────────────────────────────────────────────────────────────────────
def deploy_ray_cluster():
    header("STEP E: Deploy RayCluster (KubeRay)")

    # Read all CloudFormation outputs needed to fill ray-cluster.yaml placeholders
    s3_bucket      = cfn_output("S3BucketName")
    control_table  = cfn_output("ControlTableName")
    audit_table    = cfn_output("AuditTableName")
    metrics_table  = cfn_output("MetricsTableName")

    # Read ECR image URI from parameters file
    params_file = CFN_DIR / "eks-parameters.json"
    params      = json.loads(params_file.read_text())
    param_map   = {p["ParameterKey"]: p["ParameterValue"] for p in params}
    ecr_uri     = param_map.get("ECRImageUri", "")

    if not ecr_uri:
        fail("ECRImageUri not found in eks-parameters.json")
        fail("Run check_prerequisites.py first — it builds the image and fills this value")
        sys.exit(1)

    info(f"ECR image  : {ecr_uri}")
    info(f"S3 bucket  : {s3_bucket}")
    info(f"DynamoDB   : {control_table}")

    # Fill all <PLACEHOLDER> values in ray-cluster.yaml
    template_content = RAY_CLUSTER_TEMPLATE.read_text()
    filled_content = (
        template_content
        .replace("<ECR_IMAGE_URI>",  ecr_uri)
        .replace("<AWS_REGION>",     REGION)
        .replace("<S3_BUCKET>",      s3_bucket)
        .replace("<CONTROL_TABLE>",  control_table)
        .replace("<AUDIT_TABLE>",    audit_table)
        .replace("<METRICS_TABLE>",  metrics_table)
    )

    # Check no placeholders remain
    remaining = [line.strip() for line in filled_content.split("\n")
                 if "<" in line and ">" in line and "#" not in line.lstrip()[:1]]
    if remaining:
        warn(f"Unfilled placeholders remain:")
        for r in remaining[:5]:
            warn(f"  {r}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="ray-cluster-filled-"
    ) as tmp:
        tmp.write(filled_content)
        tmp_path = tmp.name

    try:
        run_cmd(["kubectl", "apply", "-f", tmp_path, "-n", K8S_NAMESPACE])
    finally:
        os.unlink(tmp_path)

    ok("RayCluster manifest applied")


# ─────────────────────────────────────────────────────────────────────────────
# STEP F: Wait for Ray head pod
# ─────────────────────────────────────────────────────────────────────────────
def wait_for_head():
    header("STEP F: Waiting for Ray head pod")

    # ECS equivalent: waiting for ECS service to reach RUNNING state
    info("Waiting for head pod to appear (up to 10 min — image pull + Ray init)...")

    head_pod = None
    for attempt in range(60):
        result = run_cmd([
            "kubectl", "get", "pods",
            "-n", K8S_NAMESPACE,
            "-l", "ray.io/node-type=head",
            "--no-headers",
        ], capture=True, check=False)

        lines = [l for l in result.stdout.strip().split("\n") if l]
        if lines:
            head_pod = lines[0].split()[0]
            break
        time.sleep(5)

    if not head_pod:
        fail("Head pod never appeared. Debug with:")
        fail(f"  kubectl describe raycluster ray-document-pipeline -n {K8S_NAMESPACE}")
        fail(f"  kubectl get events -n {K8S_NAMESPACE} --sort-by=.lastTimestamp")
        sys.exit(1)

    info(f"Head pod found: {head_pod}")
    info("Waiting for Ready condition (image pull can take 3-5 min first time)...")

    run_cmd([
        "kubectl", "wait", f"pod/{head_pod}",
        "--for=condition=Ready",
        "--namespace", K8S_NAMESPACE,
        "--timeout=600s",
    ])
    ok(f"Ray head pod Ready: {head_pod}")

    # Verify Ray cluster is operational
    info("Verifying Ray cluster state...")
    run_cmd([
        "kubectl", "exec", head_pod,
        "-n", K8S_NAMESPACE,
        "--", "ray", "status",
    ], check=False)

    return head_pod


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
def print_summary(head_pod: str):
    header("✅ EKS SETUP COMPLETE")

    print(f"""
  ┌─────────────────────────────────────────────────────────────────┐
  │  What was deployed (EKS equivalent of ECS CloudFormation steps) │
  │                                                                  │
  │  ✓ EKS cluster configured (kubectl ready)                       │
  │  ✓ KubeRay operator installed (replaces ECS Step Scaling)       │
  │  ✓ Namespace + ServiceAccount (IRSA) + RBAC applied             │
  │  ✓ Kubernetes Secrets created from AWS Secrets Manager          │
  │  ✓ RayCluster deployed (head + 1 worker, scales to 10)          │
  │  ✓ Ray head pod Ready                                           │
  └─────────────────────────────────────────────────────────────────┘

  Monitor pods + logs:
    kubectl get pods -n {K8S_NAMESPACE}
    kubectl logs -f {head_pod} -n {K8S_NAMESPACE}
    kubectl get raycluster -n {K8S_NAMESPACE}

  Ray Dashboard (port-forward — free, no LoadBalancer needed):
    kubectl port-forward svc/ray-dashboard 8265:8265 -n {K8S_NAMESPACE}
    Then open: http://localhost:8265

  Now run Step 2 + 3 to upload PDFs, then the orchestrator will start
  picking them up automatically.
""")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*70)
    print("  STEP 1b: EKS SETUP (KubeRay + RayCluster)")
    print("="*70)
    print("""
  This is the EKS equivalent of what CloudFormation did automatically on ECS:
    ECS: CloudFormation created ECS services + service discovery + autoscaling
    EKS: CloudFormation created the cluster, this script starts the Ray cluster

  Run this AFTER step1_deploy_cloudformation.py completes.
""")

    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt (used when called from orchestrator.py)")
    args = parser.parse_args()

    if not args.yes:
        response = input("Continue? (y/n): ")
        if response.strip().lower() != 'y':
            print("Aborted.")
            return

    preflight_checks()
    configure_kubectl()
    install_kuberay()
    apply_supporting_resources()
    create_kubernetes_secrets()
    deploy_ray_cluster()
    head_pod = wait_for_head()
    print_summary(head_pod)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)