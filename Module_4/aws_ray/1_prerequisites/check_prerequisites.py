"""
check_prerequisites.py
Ray Document Processing Pipeline — Prerequisites Check

Works on: Windows, Mac, Linux
Requires: Python 3.9+ only (no pip installs needed)

Usage:
    python check_prerequisites.py
    python3 check_prerequisites.py
"""

import subprocess
import sys
import os
import json
import shutil
import platform

# ─────────────────────────────────────────────────────────────────────────────
# COLOURS  (disabled automatically on Windows cmd where they don't render)
# ─────────────────────────────────────────────────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"
USE_COLOR  = not IS_WINDOWS and sys.stdout.isatty()

def c(text, code): return f"\033[{code}m{text}\033[0m" if USE_COLOR else text
def green(t):  return c(t, "0;32")
def red(t):    return c(t, "0;31")
def yellow(t): return c(t, "1;33")
def blue(t):   return c(t, "1;34")

PASS_COUNT = 0
FAIL_COUNT = 0

def passed(msg):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  {green('[PASS]')} {msg}")

def failed(msg):
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  {red('[FAIL]')} {msg}")

def info(msg):  print(f"  {yellow('[INFO]')} {msg}")
def fix(msg):   print(f"  {blue('[FIX ]')} {msg}")


def run(cmd: list) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", "command not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timed out"


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1 — AWS CLI
# ─────────────────────────────────────────────────────────────────────────────
def check_aws_cli():
    print("\n[ 1 ] AWS CLI")
    code, out, err = run(["aws", "--version"])
    if code == 0:
        passed(f"Installed: {out.split()[0]}")
    else:
        failed("AWS CLI not found")
        fix("Download: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html")
        if IS_WINDOWS:
            fix("Windows: download the .msi installer from the link above")
        else:
            fix("Mac:   brew install awscli")
            fix("Linux: sudo apt install awscli  OR  sudo yum install awscli")


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2 — AWS Credentials
# ─────────────────────────────────────────────────────────────────────────────
def check_aws_credentials():
    print("\n[ 2 ] AWS Credentials")
    code, out, err = run(["aws", "sts", "get-caller-identity"])
    if code == 0:
        try:
            data    = json.loads(out)
            account = data.get("Account", "?")
            arn     = data.get("Arn", "?")
            passed(f"Account: {account}")
            info(f"Identity: {arn}")
            return account
        except json.JSONDecodeError:
            passed("Credentials valid (could not parse response)")
    else:
        failed("Credentials not configured or invalid")
        fix("Run: aws configure")
        fix("You will need: Access Key ID, Secret Access Key, region, output format")
        fix("Get keys from: AWS Console → IAM → Users → your user → Security credentials")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 3 — AWS Region
# ─────────────────────────────────────────────────────────────────────────────
def check_aws_region():
    print("\n[ 3 ] AWS Region")
    code, out, err = run(["aws", "configure", "get", "region"])
    if code == 0 and out:
        passed(f"Region: {out}")
        if out != "us-east-1":
            info("CloudFormation template targets us-east-1")
            info("That is fine — just make sure ALL resources use the same region")
        return out
    else:
        failed("Region not set")
        fix("Run: aws configure set region us-east-1")
        return "us-east-1"


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4 — Docker
# ─────────────────────────────────────────────────────────────────────────────
def check_docker():
    print("\n[ 4 ] Docker")
    if not shutil.which("docker"):
        failed("Docker not found")
        fix("Install Docker Desktop: https://www.docker.com/products/docker-desktop")
        return

    code, out, err = run(["docker", "--version"])
    if code == 0:
        passed(f"Installed: {out.split()[2].rstrip(',')}")
    else:
        failed("Docker version check failed")
        return

    code, out, err = run(["docker", "info"])
    if code == 0:
        passed("Daemon is running")
    else:
        failed("Daemon is NOT running")
        if IS_WINDOWS:
            fix("Open Docker Desktop from the Start Menu and wait for it to start")
        else:
            fix("Open Docker Desktop  OR  run: sudo systemctl start docker")


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 5 — AWS Permissions
# ─────────────────────────────────────────────────────────────────────────────
def check_aws_permissions(region: str):
    print("\n[ 5 ] AWS Permissions")
    permission_failed = False

    checks = [
        ("CloudFormation",  ["aws", "cloudformation", "list-stacks", "--region", region]),
        ("ECR",             ["aws", "ecr", "describe-repositories", "--region", region]),
        ("ECS",             ["aws", "ecs", "list-clusters", "--region", region]),
        ("S3",              ["aws", "s3", "ls"]),
        ("DynamoDB",        ["aws", "dynamodb", "list-tables", "--region", region]),
        ("Secrets Manager", ["aws", "secretsmanager", "list-secrets", "--region", region]),
        ("Lambda",          ["aws", "lambda", "list-functions", "--region", region]),
    ]

    for name, cmd in checks:
        code, out, err = run(cmd)
        if code == 0:
            passed(name)
        else:
            failed(f"{name} — AccessDenied or error")
            permission_failed = True

    if permission_failed:
        fix("Attach the IAM policy printed at the bottom of this output to your user/role")

    return permission_failed


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 6 — API Keys → Secrets Manager
#
# Logic:
#   1. Check if secret already exists in Secrets Manager → PASS (nothing to do)
#   2. Secret missing but env var set  → CREATE secret automatically → PASS
#   3. Secret missing and env var also missing → FAIL with instructions
#
# On success, ARNs are written back into cloudformation-parameters.json
# so Step 3 (CloudFormation deploy) works without any manual editing.
# ─────────────────────────────────────────────────────────────────────────────

SECRETS_CONFIG = {
    "OPENAI_API_KEY": {
        "secret_name": "ray-pipeline-openai",
        "cfn_param":   "OpenAIApiKeySecretArn",
        "env_var":     "OPENAI_API_KEY",
        "get_key_url": "https://platform.openai.com/api-keys",
        "hint":        "Needs access to: gpt-4o and text-embedding-3-small",
    },
    "PINECONE_API_KEY": {
        "secret_name": "ray-pipeline-pinecone",
        "cfn_param":   "PineconeApiKeySecretArn",
        "env_var":     "PINECONE_API_KEY",
        "get_key_url": "https://app.pinecone.io/ → API Keys",
        "hint":        "Must be on Serverless plan (free tier is fine)",
    },
}


def _get_secret_arn(secret_name: str, region: str) -> str | None:
    """Return ARN if secret exists in Secrets Manager, else None."""
    code, out, err = run([
        "aws", "secretsmanager", "describe-secret",
        "--secret-id", secret_name,
        "--region", region,
    ])
    if code == 0:
        try:
            return json.loads(out).get("ARN")
        except json.JSONDecodeError:
            return None
    return None


def _create_secret(secret_name: str, key_name: str, key_value: str, region: str) -> str | None:
    """Create secret in Secrets Manager. Returns ARN on success, None on failure."""
    secret_string = json.dumps({key_name: key_value})
    code, out, err = run([
        "aws", "secretsmanager", "create-secret",
        "--name", secret_name,
        "--secret-string", secret_string,
        "--region", region,
    ])
    if code == 0:
        try:
            return json.loads(out).get("ARN")
        except json.JSONDecodeError:
            return None
    return None


def _update_cfn_params(param_key: str, arn: str):
    """Write ARN back into cloudformation-parameters.json."""
    # Locate the params file relative to this script
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    params_path = os.path.join(script_dir, "..", "2_cloudformation", "cloudformation-parameters.json")
    params_path = os.path.normpath(params_path)

    if not os.path.exists(params_path):
        info(f"cloudformation-parameters.json not found at {params_path} — skipping auto-update")
        return

    with open(params_path, "r") as f:
        params = json.load(f)

    updated = False
    for p in params:
        if p["ParameterKey"] == param_key:
            p["ParameterValue"] = arn
            updated = True
            break

    if updated:
        with open(params_path, "w") as f:
            json.dump(params, f, indent=2)
        info(f"Updated cloudformation-parameters.json → {param_key}")
    else:
        info(f"Parameter {param_key} not found in cloudformation-parameters.json")


def check_and_provision_secrets(region: str):
    """
    For each required API key:
      - If secret already in Secrets Manager → PASS
      - If missing but env var set           → CREATE it → PASS
      - If missing and no env var            → FAIL with instructions
    ARNs are written back to cloudformation-parameters.json automatically.
    """
    print("\n[ 6 ] API Keys → Secrets Manager")

    for label, cfg in SECRETS_CONFIG.items():
        secret_name = cfg["secret_name"]
        env_var     = cfg["env_var"]
        cfn_param   = cfg["cfn_param"]

        # ── Step 1: already exists in Secrets Manager? ──────────────────────
        arn = _get_secret_arn(secret_name, region)
        if arn:
            passed(f"{label} — secret already exists in Secrets Manager")
            info(f"  ARN: {arn}")
            _update_cfn_params(cfn_param, arn)
            continue

        # ── Step 2: missing in Secrets Manager — try env var ────────────────
        key_value = os.environ.get(env_var, "").strip()
        if not key_value:
            failed(f"{label} — not in Secrets Manager and {env_var} env var not set")
            fix(f"Get key: {cfg['get_key_url']}")
            fix(f"        {cfg['hint']}")
            if IS_WINDOWS:
                fix(f"Then set: set {env_var}=YOUR-KEY-HERE  and re-run this script")
            else:
                fix(f"Then set: export {env_var}=YOUR-KEY-HERE  and re-run this script")
            continue

        # ── Step 3: env var present — create the secret ─────────────────────
        info(f"{label} — not in Secrets Manager, creating from {env_var} env var...")
        arn = _create_secret(secret_name, env_var, key_value, region)
        if arn:
            passed(f"{label} — secret created in Secrets Manager")
            info(f"  Secret name: {secret_name}")
            info(f"  ARN: {arn}")
            _update_cfn_params(cfn_param, arn)
        else:
            failed(f"{label} — could not create secret (check Secrets Manager permissions)")
            fix("Ensure your IAM user has secretsmanager:CreateSecret permission")


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 7 — S3 Bucket Name
# Reads the name from cloudformation-parameters.json and validates it
# ─────────────────────────────────────────────────────────────────────────────
def check_s3_bucket_name(region: str) -> str | None:
    print("\n[ 7 ] S3 Bucket Name")

    script_dir  = os.path.dirname(os.path.abspath(__file__))
    params_path = os.path.normpath(os.path.join(script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"))

    bucket_name = None
    if os.path.exists(params_path):
        try:
            params = json.load(open(params_path))
            for p in params:
                if p["ParameterKey"] == "S3BucketName":
                    bucket_name = p["ParameterValue"]
                    break
        except Exception:
            pass

    placeholder = not bucket_name or bucket_name == "my-document-pipeline-prod-12345"
    if placeholder:
        failed("S3BucketName is still the placeholder value in cloudformation-parameters.json")
        fix("Edit 2_cloudformation/cloudformation-parameters.json")
        fix("Change S3BucketName to something globally unique, e.g.  ray-pipeline-prudhvi-2024")
        fix("Rules: lowercase letters, numbers, hyphens only. 3–63 chars.")
        return None

    # Check if name is available
    code, out, err = run(["aws", "s3api", "head-bucket", "--bucket", bucket_name, "--region", region])
    if code == 0:
        # Bucket exists — check if WE own it (that's fine) or someone else does (problem)
        code2, out2, _ = run(["aws", "s3api", "get-bucket-location", "--bucket", bucket_name])
        if code2 == 0:
            passed(f"Bucket '{bucket_name}' exists and is owned by your account")
        else:
            failed(f"Bucket '{bucket_name}' exists but belongs to another AWS account")
            fix("Choose a different name in cloudformation-parameters.json")
            return None
    else:
        # 404 = doesn't exist yet = available
        passed(f"Bucket name '{bucket_name}' is available")

    return bucket_name


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 8 — Build Docker Image & Push to ECR
#
# Logic:
#   1. Get or create ECR repository
#   2. Build image from 3_deployment/  (same image used for both head and worker)
#   3. Tag as :head and :worker
#   4. Push both tags to ECR
#   5. Write ECR URI back into cloudformation-parameters.json (RayDockerImageUri)
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_NAME   = "ray-document-pipeline"
ECR_REPO_NAME  = f"{PROJECT_NAME}-ray"
IMAGE_TAG_HEAD   = "head"
IMAGE_TAG_WORKER = "worker"
IMAGE_TAG_LATEST = "latest"


def _get_or_create_ecr_repo(region: str, account_id: str) -> str | None:
    """Return ECR repo URI, creating it if it doesn't exist."""
    # Check if repo already exists
    code, out, _ = run([
        "aws", "ecr", "describe-repositories",
        "--repository-names", ECR_REPO_NAME,
        "--region", region,
    ])
    if code == 0:
        try:
            uri = json.loads(out)["repositories"][0]["repositoryUri"]
            info(f"ECR repo already exists: {uri}")
            return uri
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    # Create it
    info(f"Creating ECR repository: {ECR_REPO_NAME} ...")
    code, out, err = run([
        "aws", "ecr", "create-repository",
        "--repository-name", ECR_REPO_NAME,
        "--image-scanning-configuration", "scanOnPush=true",
        "--region", region,
    ])
    if code == 0:
        try:
            uri = json.loads(out)["repository"]["repositoryUri"]
            info(f"ECR repo created: {uri}")
            return uri
        except (json.JSONDecodeError, KeyError):
            pass

    return None


def _ecr_login(region: str, account_id: str) -> bool:
    """Authenticate Docker to ECR."""
    info("Authenticating Docker to ECR...")
    # Get login password
    code, password, _ = run([
        "aws", "ecr", "get-login-password", "--region", region
    ])
    if code != 0:
        return False

    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    result = subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password, capture_output=True, text=True
    )
    return result.returncode == 0


def build_and_push_docker(region: str, account_id: str):
    """
    Build the pipeline Docker image and push head + worker tags to ECR.
    Updates cloudformation-parameters.json with the ECR URI on success.
    """
    print("\n[ 8 ] Docker Image — Build & Push to ECR")

    if not account_id:
        failed("Cannot build — AWS account ID not available (check credentials)")
        return

    # ── Locate Dockerfile ───────────────────────────────────────────────────
    script_dir    = os.path.dirname(os.path.abspath(__file__))
    deployment_dir = os.path.normpath(os.path.join(script_dir, "..", "3_deployment"))
    dockerfile     = os.path.join(deployment_dir, "Dockerfile")

    if not os.path.exists(dockerfile):
        failed(f"Dockerfile not found at {dockerfile}")
        return

    # ── Get / create ECR repo ────────────────────────────────────────────────
    repo_uri = _get_or_create_ecr_repo(region, account_id)
    if not repo_uri:
        failed("Could not get or create ECR repository")
        fix("Check ECR permissions: aws ecr describe-repositories --region " + region)
        return

    # ── ECR login ────────────────────────────────────────────────────────────
    if not _ecr_login(region, account_id):
        failed("Docker ECR login failed")
        fix("Run manually: aws ecr get-login-password --region " + region +
            " | docker login --username AWS --password-stdin " +
            f"{account_id}.dkr.ecr.{region}.amazonaws.com")
        return
    info("Docker authenticated to ECR")

    # ── Build and push via buildx ─────────────────────────────────────────────
    # --platform linux/amd64 is required because:
    #   - rayproject/ray base image is linux/amd64 only
    #   - ECS Fargate runs linux/amd64
    #   - Apple Silicon (M1/M2/M3) is ARM64 — build fails without this flag
    local_tag = f"{ECR_REPO_NAME}:latest"
    info(f"Building image (linux/amd64) from {deployment_dir} ...")
    info("This takes 5-10 minutes on first build. Output streamed below:")
    info("-" * 50)

    build_result = subprocess.run(
        [
            "docker", "buildx", "build",
            "--platform", "linux/amd64",
            "--output", "type=docker",
            "--provenance=false",
            "-t", local_tag,
            "--no-cache",
            ".",
        ],
        capture_output=False,
        text=True,
        cwd=deployment_dir,   # run FROM the 3_deployment dir, same as: cd 3_deployment && docker buildx build ...
    )

    if build_result.returncode != 0:
        failed("Docker build failed — see output above")
        fix("Retry manually:")
        fix(f"  docker buildx build --platform linux/amd64 --output type=docker --provenance=false -t {local_tag} --no-cache {deployment_dir}")
        return
    passed("Docker image built successfully (linux/amd64)")

    # ── Tag and push each tag to ECR ─────────────────────────────────────────
    push_failed = False
    for tag in [IMAGE_TAG_LATEST, IMAGE_TAG_HEAD, IMAGE_TAG_WORKER]:
        remote_tag = f"{repo_uri}:{tag}"

        code, _, _ = run(["docker", "tag", local_tag, remote_tag])
        if code != 0:
            failed(f"Failed to tag as :{tag}")
            push_failed = True
            continue

        info(f"Pushing {remote_tag} ...")
        push_result = subprocess.run(
            ["docker", "push", remote_tag],
            capture_output=False,
            text=True,
        )
        if push_result.returncode != 0:
            failed(f"Failed to push :{tag}")
            push_failed = True
        else:
            passed(f"Pushed :{tag}  →  {remote_tag}")

    if push_failed:
        failed("One or more tags failed to push — check output above")
        return

    # ── Write ECR URI into cloudformation-parameters.json ───────────────────
    ecr_image_uri = f"{repo_uri}:{IMAGE_TAG_LATEST}"
    _update_cfn_params("RayDockerImageUri", ecr_image_uri)
    passed(f"ECR URI written to cloudformation-parameters.json")
    info(f"  Head image:   {repo_uri}:{IMAGE_TAG_HEAD}")
    info(f"  Worker image: {repo_uri}:{IMAGE_TAG_WORKER}")
    info(f"  CFN param:    {ecr_image_uri}")


# ─────────────────────────────────────────────────────────────────────────────
# IAM POLICY (printed only when permission checks fail)
# ─────────────────────────────────────────────────────────────────────────────
IAM_POLICY = """
Save the JSON below as  deploy-policy.json  then run:

  aws iam put-user-policy \\
    --user-name YOUR-IAM-USERNAME \\
    --policy-name RayPipelineDeploy \\
    --policy-document file://deploy-policy.json

──────────────── deploy-policy.json ────────────────
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["cloudformation:*","ecr:*","ecs:*","s3:*","dynamodb:*",
                 "lambda:*","secretsmanager:*","logs:*","cloudwatch:*","sns:*"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["iam:CreateRole","iam:DeleteRole","iam:AttachRolePolicy",
                 "iam:DetachRolePolicy","iam:PutRolePolicy","iam:DeleteRolePolicy",
                 "iam:GetRole","iam:GetRolePolicy","iam:PassRole","iam:TagRole",
                 "iam:ListRolePolicies","iam:ListAttachedRolePolicies"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["ec2:CreateVpc","ec2:DeleteVpc","ec2:CreateSubnet","ec2:DeleteSubnet",
                 "ec2:CreateInternetGateway","ec2:DeleteInternetGateway",
                 "ec2:AttachInternetGateway","ec2:DetachInternetGateway",
                 "ec2:CreateRouteTable","ec2:DeleteRouteTable","ec2:CreateRoute",
                 "ec2:DeleteRoute","ec2:AssociateRouteTable","ec2:DisassociateRouteTable",
                 "ec2:CreateNatGateway","ec2:DeleteNatGateway","ec2:AllocateAddress",
                 "ec2:ReleaseAddress","ec2:CreateSecurityGroup","ec2:DeleteSecurityGroup",
                 "ec2:AuthorizeSecurityGroupIngress","ec2:AuthorizeSecurityGroupEgress",
                 "ec2:DescribeVpcs","ec2:DescribeSubnets","ec2:DescribeRouteTables",
                 "ec2:DescribeInternetGateways","ec2:DescribeNatGateways",
                 "ec2:DescribeSecurityGroups","ec2:DescribeAvailabilityZones",
                 "ec2:ModifyVpcAttribute","ec2:CreateTags","ec2:DescribeAddresses",
                 "ec2:DescribeAddressesAttribute"],
      "Resource": "*"
    }
  ]
}
────────────────────────────────────────────────────
"""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print()
    print("=" * 60)
    print("  RAY PIPELINE — PREREQUISITES CHECK")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print("=" * 60)

    check_aws_cli()
    account_id = check_aws_credentials()
    region = check_aws_region()
    check_docker()
    permission_failed = check_aws_permissions(region)
    check_and_provision_secrets(region)
    check_s3_bucket_name(region)
    build_and_push_docker(region, account_id)

    print()
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  {green(f'Passed: {PASS_COUNT}')}")
    print(f"  {red(f'Failed: {FAIL_COUNT}')}")
    print()

    if FAIL_COUNT == 0:
        print(f"  {green('All checks passed! Ready to deploy CloudFormation stack.')}")
        print()
        print("  Everything is prepared:")
        print("  ✓ API keys stored in Secrets Manager")
        print("  ✓ Docker image built and pushed to ECR")
        print("  ✓ cloudformation-parameters.json fully populated")
        print()
        print("  NEXT: Deploy the CloudFormation stack")
        print("  See:  2_cloudformation/CLOUDFORMATION_DEPLOYMENT_GUIDE.md")
    else:
        print(f"  {red(f'Fix the {FAIL_COUNT} failed check(s) above, then re-run this script.')}")
        if permission_failed:
            print(IAM_POLICY)

    print()


if __name__ == "__main__":
    main()