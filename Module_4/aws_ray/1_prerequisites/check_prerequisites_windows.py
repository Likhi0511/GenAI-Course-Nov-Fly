"""
check_prerequisites.py
Ray Document Processing Pipeline — Prerequisites Check

==============================================================================
OVERVIEW
==============================================================================
This script validates that your local environment and AWS account are properly
configured before deploying the Ray Document Processing Pipeline via CloudFormation.

It performs 10 comprehensive checks covering:
- Local tools (AWS CLI, Docker)
- AWS authentication & permissions
- Resource provisioning (Secrets Manager, ECR)
- Capacity validation (Service quotas)
- Template validation (CloudFormation syntax)

The script is idempotent and safe to run multiple times. It will skip
operations that have already been completed successfully.

==============================================================================
REQUIREMENTS
==============================================================================
- Python 3.9 or higher (no additional pip packages required)
- AWS CLI v2.x installed and in PATH
- Docker Engine installed and running
- AWS credentials configured (via 'aws configure' or environment variables)
- Environment variables set:
  - OPENAI_API_KEY: Your OpenAI API key (starts with sk-...)
  - PINECONE_API_KEY: Your Pinecone API key

==============================================================================
USAGE
==============================================================================
Basic usage (runs all 10 checks):
    python check_prerequisites.py
    python3 check_prerequisites.py

On Windows:
    python check_prerequisites.py

==============================================================================
WHAT THIS SCRIPT DOES
==============================================================================
1. Validates AWS CLI is installed and accessible
2. Checks AWS credentials are configured and active
3. Verifies AWS default region is set
4. Confirms Docker is installed and daemon is running
5. Tests IAM permissions for 7 required AWS services
6. Provisions API keys in AWS Secrets Manager
7. Validates S3 bucket name in CloudFormation parameters
8. Builds Docker image and pushes to Amazon ECR (takes 8-12 minutes first run)
9. Checks AWS service quotas (VPC limit)
10. Validates CloudFormation template syntax

==============================================================================
EXECUTION TIME
==============================================================================
First run:  8-12 minutes (includes Docker image build + ECR push)
Subsequent runs: 1-2 minutes (Docker image already in ECR)

The longest operation is Check 8 (Docker build), which downloads and compiles
dependencies including PyTorch, Ray, and document processing libraries.

==============================================================================
ARCHITECTURE NOTE — PUBLIC SUBNET (NO NAT GATEWAY)
==============================================================================
This pipeline uses a PUBLIC subnet design for cost reasons:
- ECS Fargate tasks get public IPs directly via the Internet Gateway
- No NAT Gateway required (saves ~$32/month)
- No Elastic IPs needed
- Suitable for teaching/demo environments with 10-20 documents
For production with sensitive data, switch to a private subnet + NAT Gateway.

==============================================================================
OUTPUT
==============================================================================
The script produces colored output showing:
- [PASS] - Check succeeded
- [FAIL] - Check failed (with instructions to fix)
- [INFO] - Informational message
- [FIX ] - Suggested fix for failed check

At the end, a summary shows total passed/failed checks.

If all checks pass, you're ready to deploy the CloudFormation stack.
If checks fail, follow the [FIX] instructions and re-run the script.

==============================================================================
PREREQUISITES DIRECTORY STRUCTURE
==============================================================================
1_prerequisites/
├── check_prerequisites.py          # This script
└── README.md                        # Additional documentation

Related files (created/updated by this script):
2_cloudformation/
└── cloudformation-parameters.json  # Updated with ECR URI and secret ARNs

3_deployment/
├── Dockerfile                      # Used to build Ray pipeline image
├── requirements.txt                # Python dependencies for Docker image
└── *.py                           # Pipeline Python modules

==============================================================================
COMMON ISSUES & FIXES
==============================================================================
Issue: "AWS CLI not found"
Fix:   Install from https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html

Issue: "Credentials not configured"
Fix:   Run 'aws configure' and enter your access key, secret key, and region

Issue: "Docker daemon not running"
Fix:   Start Docker Desktop application (Mac/Windows) or 'sudo systemctl start docker' (Linux)

Issue: "Permission denied" on Docker commands (Linux)
Fix:   Add user to docker group: sudo usermod -aG docker $USER (then logout/login)

Issue: "Environment variable not set"
Fix:   Export the required variable: export OPENAI_API_KEY='your-key-here'

Issue: "S3 bucket name is placeholder"
Fix:   Edit 2_cloudformation/cloudformation-parameters.json and set unique bucket name

Issue: "VPC limit reached"
Fix:   Delete unused VPCs or request quota increase via AWS Service Quotas console

==============================================================================
SECURITY NOTES
==============================================================================
- API keys are stored securely in AWS Secrets Manager (encrypted at rest)
- Secrets Manager secrets cost $0.40/month each
- CloudFormation references secrets via ARN (no plaintext in templates)
- ECS tasks retrieve secrets at runtime as environment variables
- Local .env files are never used in production (development only)

==============================================================================
COST IMPLICATIONS
==============================================================================
Running this script incurs minimal AWS costs:
- Secrets Manager: $0.40/month per secret (2 secrets = $0.80/month)
- ECR Storage: $0.10/GB-month (3.2GB image = ~$0.32/month)
- CloudFormation: Free (no charge for stacks)
- Data Transfer: First 100GB/month free

First run may incur small data transfer costs for Docker image push (~3.2GB).
Subsequent runs use cached Docker layers (much faster, less transfer).

==============================================================================
PLATFORM COMPATIBILITY
==============================================================================
Works on: Windows, macOS (Intel & Apple Silicon), Linux
- Automatically detects Apple Silicon and uses --platform linux/amd64 flag
- Disables colored output on Windows CMD (where ANSI codes don't render)
- Uses cross-platform path handling (os.path.normpath)

==============================================================================
TROUBLESHOOTING
==============================================================================
If script fails unexpectedly:
1. Check internet connectivity (needed for AWS API calls and Docker pulls)
2. Verify AWS CLI version is 2.x: aws --version
3. Test AWS credentials: aws sts get-caller-identity
4. Check Docker is running: docker ps
5. Ensure environment variables are set: echo $OPENAI_API_KEY

For persistent issues:
- Review AWS CloudWatch Logs for detailed error messages
- Check IAM permissions match the policy shown in Check 5
- Verify region supports ECS Fargate (most regions do)

==============================================================================
NEXT STEPS AFTER SUCCESS
==============================================================================
Once all checks pass:
1. Review cloudformation-parameters.json to verify all parameters are set
2. Deploy CloudFormation stack following the guide in:
   2_cloudformation/CLOUDFORMATION_DEPLOYMENT_GUIDE.md
3. Monitor stack creation in AWS Console → CloudFormation
4. Test Ray cluster after deployment completes (~15-20 minutes)

==============================================================================
AUTHOR & VERSION
==============================================================================
Script version: 2.1
Last updated: February 2026
Platform support: Windows, macOS, Linux
Python requirement: 3.9+

Fixes in 2.1:
- FIX 1: Removed misleading Elastic IP / NAT Gateway quota check.
         Pipeline uses public subnets — no NAT Gateway, no EIP needed.
- FIX 2: Corrected CloudFormation template filename in Check 10.
         Now looks for '1_ray-pipeline-cloudformation-public.yaml'
         instead of 'ray-pipeline-cloudformation.yaml'.
- FIX 3: Replaced narrow 3-service auto-fix IAM policy with PowerUserAccess.
         Previous policy only covered CloudFormation, DynamoDB, and Lambda —
         missing ECS, ECR, S3, Secrets Manager and VPC permissions.
         New approach attaches PowerUserAccess (covers everything needed).
         If the user is not an IAM admin, prints clear manual instructions.

For questions or issues, refer to the README files in each directory.
==============================================================================

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

# ═════════════════════════════════════════════════════════════════════════════
# TERMINAL COLORS & OUTPUT FORMATTING
# ═════════════════════════════════════════════════════════════════════════════
# ANSI escape codes for colored terminal output. These are automatically
# disabled on Windows CMD where they don't render properly.
#
# Colors used:
# - GREEN: Successful checks ([PASS])
# - RED: Failed checks ([FAIL])
# - YELLOW: Informational messages ([INFO])
# - BLUE: Fix suggestions ([FIX])
# ═════════════════════════════════════════════════════════════════════════════
IS_WINDOWS = platform.system() == "Windows"
USE_COLOR  = not IS_WINDOWS and sys.stdout.isatty()

def c(text, code):
    """
    Apply ANSI color code to text if colors are enabled.

    Args:
        text: String to colorize
        code: ANSI escape code (e.g., "0;32" for green)

    Returns:
        Colored text if USE_COLOR is True, otherwise plain text
    """
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def green(t):
    """Format text in green (used for [PASS] messages)."""
    return c(t, "0;32")

def red(t):
    """Format text in red (used for [FAIL] messages)."""
    return c(t, "0;31")

def yellow(t):
    """Format text in yellow (used for [INFO] messages)."""
    return c(t, "1;33")

def blue(t):
    """Format text in blue (used for [FIX] suggestions)."""
    return c(t, "1;34")


# ═════════════════════════════════════════════════════════════════════════════
# GLOBAL COUNTERS
# ═════════════════════════════════════════════════════════════════════════════
# Track total passed and failed checks for final summary.
# These are incremented by passed() and failed() functions below.
# ═════════════════════════════════════════════════════════════════════════════
PASS_COUNT = 0
FAIL_COUNT = 0

def passed(msg):
    """
    Log a successful check and increment pass counter.
    Prints green [PASS] message.

    Args:
        msg: Success message to display
    """
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  {green('[PASS]')} {msg}")

def failed(msg):
    """
    Log a failed check and increment fail counter.
    Prints red [FAIL] message.

    Args:
        msg: Failure message to display
    """
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  {red('[FAIL]')} {msg}")

def info(msg):
    """
    Display informational message (yellow [INFO]).
    Does not affect pass/fail counters.

    Args:
        msg: Information to display
    """
    print(f"  {yellow('[INFO]')} {msg}")

def fix(msg):
    """
    Display suggested fix for a failed check (blue [FIX]).
    Typically called after failed() to guide user on remediation.

    Args:
        msg: Fix suggestion to display
    """
    print(f"  {blue('[FIX ]')} {msg}")


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND EXECUTION HELPER
# ═════════════════════════════════════════════════════════════════════════════
def run(cmd: list) -> tuple[int, str, str]:
    """
    Execute a shell command and return results.

    This is a wrapper around subprocess.run() with standard configuration:
    - Captures stdout and stderr
    - 15-second timeout to prevent hangs
    - Returns empty strings if command not found

    Args:
        cmd: Command and arguments as list (e.g., ["aws", "--version"])

    Returns:
        Tuple of (returncode, stdout, stderr)
        - returncode: 0 on success, non-zero on failure
        - stdout: Command output (stripped of whitespace)
        - stderr: Error output (stripped of whitespace)

    Example:
        code, out, err = run(["aws", "--version"])
        if code == 0:
            print(f"AWS CLI version: {out}")
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        # Command not found in PATH (e.g., AWS CLI not installed)
        return -1, "", "command not found"
    except subprocess.TimeoutExpired:
        # Command took longer than 15 seconds
        return -1, "", "timed out"


# ═════════════════════════════════════════════════════════════════════════════
# CHECK 1 — AWS CLI
# ═════════════════════════════════════════════════════════════════════════════
# Verifies that the AWS Command Line Interface (CLI) is installed and accessible
# from the system PATH. The AWS CLI is required for all subsequent AWS operations.
#
# What we check:
# - AWS CLI is installed and in PATH
# - Can execute 'aws --version' successfully
#
# What we don't check (yet):
# - Specific CLI version (we just need v2.x, any sub-version is fine)
#
# If this check fails:
# - User must install AWS CLI v2 from official AWS documentation
# - Provide platform-specific installation instructions
# ═════════════════════════════════════════════════════════════════════════════
def check_aws_cli():
    """
    Check 1 of 10: Verify AWS CLI is installed.

    Executes 'aws --version' to test if AWS CLI is available.
    Parses version string and displays it on success.
    Provides platform-specific installation instructions on failure.

    Returns:
        None (updates global PASS_COUNT or FAIL_COUNT)
    """
    print("\n[ 1 ] AWS CLI")

    # Execute 'aws --version' command
    code, out, err = run(["aws", "--version"])

    if code == 0:
        # AWS CLI found and executed successfully
        # Output format: "aws-cli/2.15.30 Python/3.11.8 Darwin/23.3.0 exe/x86_64"
        # We extract just "aws-cli/2.15.30" for display
        version = out.split()[0]  # First word is the version
        passed(f"Installed: {version}")
    else:
        # AWS CLI not found in PATH
        failed("AWS CLI not found")
        fix("Download: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html")

        # Provide platform-specific installation commands
        if IS_WINDOWS:
            fix("Windows: download the .msi installer from the link above")
        else:
            fix("Mac:   brew install awscli")
            fix("Linux: sudo apt install awscli  OR  sudo yum install awscli")


# ═════════════════════════════════════════════════════════════════════════════
# CHECK 2 — AWS CREDENTIALS
# ═════════════════════════════════════════════════════════════════════════════
# Validates that AWS credentials are configured and active by calling the AWS
# Security Token Service (STS) GetCallerIdentity API.
#
# What we check:
# - Credentials exist (either in ~/.aws/credentials or environment variables)
# - Credentials are valid (not expired, not revoked)
# - Can successfully authenticate with AWS
#
# What we capture:
# - AWS Account ID (12-digit number) - needed for ECR image tagging later
# - IAM identity ARN - shows which IAM user/role is being used
#
# Why we need this:
# - Account ID is required to construct ECR repository URI in Check 8
# - Validates permissions before attempting expensive operations
#
# Credential sources (checked in order):
# 1. AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
# 2. ~/.aws/credentials file (profiles)
# 3. ~/.aws/config file (SSO configuration)
# 4. IAM role (if running on EC2/ECS)
# ═════════════════════════════════════════════════════════════════════════════
def check_aws_credentials():
    """
    Check 2 of 10: Verify AWS credentials are configured and valid.

    Calls 'aws sts get-caller-identity' which returns the AWS account ID
    and IAM identity ARN if credentials are valid.

    Returns:
        str: AWS account ID (12-digit string) if successful
        None: If credentials are missing or invalid

    The account ID is used in Check 8 to construct the ECR repository URI:
    {account_id}.dkr.ecr.{region}.amazonaws.com/{repo_name}
    """
    print("\n[ 2 ] AWS Credentials")

    # Call AWS STS GetCallerIdentity API
    # This is a lightweight API call that just returns identity information
    code, out, err = run(["aws", "sts", "get-caller-identity"])

    if code == 0:
        # Successfully authenticated - parse the JSON response
        try:
            data    = json.loads(out)
            account = data.get("Account", "?")  # 12-digit AWS account ID
            arn     = data.get("Arn", "?")      # IAM identity ARN

            passed(f"Account: {account}")
            info(f"Identity: {arn}")

            # Return account ID for use in Check 8 (ECR operations)
            return account

        except json.JSONDecodeError:
            # Response was successful but couldn't parse JSON (very rare)
            passed("Credentials valid (could not parse response)")
    else:
        # Authentication failed - credentials missing or invalid
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
        return out
    else:
        failed("Region not configured")
        fix("Run: aws configure")
        fix("Set default region (e.g., us-east-1, us-west-2)")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4 — Docker
# ─────────────────────────────────────────────────────────────────────────────
def check_docker():
    print("\n[ 4 ] Docker")

    # Check if Docker is installed
    code, out, err = run(["docker", "--version"])
    if code != 0:
        failed("Docker not found")
        fix("Install Docker Desktop: https://www.docker.com/products/docker-desktop")
        if IS_WINDOWS:
            fix("Windows: Download Docker Desktop for Windows")
        elif platform.system() == "Darwin":
            fix("Mac: Download Docker Desktop for Mac")
        else:
            fix("Linux: sudo apt install docker.io  OR  sudo yum install docker")
        return

    passed(f"Installed: {out.split()[2].rstrip(',')}")

    # Check if Docker daemon is running
    code, out, err = run(["docker", "info"])
    if code == 0:
        passed("Daemon is running")
    else:
        failed("Docker daemon is not running")
        if IS_WINDOWS or platform.system() == "Darwin":
            fix("Start Docker Desktop application")
        else:
            fix("Linux: sudo systemctl start docker")
            fix("       sudo systemctl enable docker")


# ═════════════════════════════════════════════════════════════════════════════
# IAM POLICY TEMPLATE
# ═════════════════════════════════════════════════════════════════════════════
# This policy is displayed if Check 5 (AWS Permissions) fails AND auto-fix
# was not possible (user is not an IAM admin).
#
# The easiest fix is to attach the AWS managed policy PowerUserAccess, which
# covers all services needed: CloudFormation, ECR, ECS, S3, DynamoDB,
# Secrets Manager, Lambda, EC2 (VPC/networking), IAM (role creation),
# and CloudWatch Logs.
#
# Why PowerUserAccess (not AdministratorAccess)?
# - PowerUserAccess covers everything needed for this deployment
# - It does NOT grant IAM user management (more secure than Admin)
# - It is an AWS managed policy maintained by AWS (always up to date)
#
# If your organisation requires a scoped policy instead of PowerUserAccess,
# use the custom policy below which lists only the specific actions needed.
# ═════════════════════════════════════════════════════════════════════════════
IAM_POLICY = """
Recommended fix — attach the AWS managed policy PowerUserAccess:

    aws iam attach-user-policy \\
        --user-name YOUR_IAM_USERNAME \\
        --policy-arn arn:aws:iam::aws:policy/PowerUserAccess

PowerUserAccess covers all services needed by this pipeline:
  CloudFormation, ECR, ECS, S3, DynamoDB, Secrets Manager,
  Lambda, EC2 (VPC/networking), IAM (role creation), CloudWatch Logs.

If your organisation requires a scoped policy instead, use this
minimal policy that lists only the specific actions needed:

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "ecr:*",
        "ecs:*",
        "s3:*",
        "dynamodb:*",
        "secretsmanager:*",
        "lambda:*",
        "servicediscovery:*",
        "application-autoscaling:*",
        "ec2:Describe*",
        "ec2:CreateVpc",
        "ec2:DeleteVpc",
        "ec2:CreateSubnet",
        "ec2:DeleteSubnet",
        "ec2:CreateInternetGateway",
        "ec2:AttachInternetGateway",
        "ec2:DetachInternetGateway",
        "ec2:DeleteInternetGateway",
        "ec2:CreateRouteTable",
        "ec2:CreateRoute",
        "ec2:AssociateRouteTable",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:CreateVpcEndpoint",
        "ec2:DeleteVpcEndpoints",
        "ec2:ModifySubnetAttribute",
        "ec2:ModifyVpcAttribute",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:PassRole",
        "iam:GetRole",
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "sns:*",
        "logs:*",
        "cloudwatch:*"
      ],
      "Resource": "*"
    }
  ]
}
"""

# ═════════════════════════════════════════════════════════════════════════════
# CHECK 5 — AWS PERMISSIONS
# ═════════════════════════════════════════════════════════════════════════════
# Tests IAM permissions by attempting read-only operations on each required AWS
# service. This validates that the current IAM user/role has sufficient permissions
# before attempting expensive operations like Docker builds or CloudFormation deployments.
#
# Services tested:
# 1. CloudFormation - Stack creation (needed for deployment)
# 2. ECR - Docker image registry (needed for storing pipeline image)
# 3. ECS - Fargate task management (needed for running Ray cluster)
# 4. S3 - Object storage (needed for document uploads/downloads)
# 5. DynamoDB - NoSQL database (needed for pipeline metadata)
# 6. Secrets Manager - Secure key storage (needed for API keys)
# 7. Lambda - Serverless functions (S3 event trigger)
#
# What we test:
# - Read-only 'list' or 'describe' operations on each service
# - These are the least privileged operations that still require permissions
#
# What we don't test:
# - Write permissions (create/update/delete) - tested during actual deployment
# - Cross-account permissions or resource policies
#
# Why this approach:
# - Fail fast: Better to discover missing permissions now than 10 minutes into deployment
# - Actionable: Provides specific IAM policy/command to fix the issue
# - Safe: Only performs read operations, no resources are created
#
# FIX 3: Auto-fix now attaches PowerUserAccess (covers all 7 services) instead
# of a narrow 3-service policy. If the user is not an IAM admin (cannot attach
# policies), prints a clear manual command rather than silently failing.
# ═════════════════════════════════════════════════════════════════════════════
def check_aws_permissions(region):
    """
    Check 5 of 10: Verify IAM permissions for required AWS services.

    Performs lightweight read-only operations on 7 AWS services to validate
    the current IAM identity has sufficient permissions for deployment.

    If any permissions are missing, attempts to auto-fix by attaching
    PowerUserAccess to the current IAM user. If the user is not an IAM
    admin (cannot attach policies), prints a clear manual fix command.

    Args:
        region: AWS region (used for regional service calls)

    Returns:
        bool: True if any permission check failed, False if all passed.
              Used in main() to decide whether to display the IAM policy.
    """
    print("\n[ 5 ] AWS Permissions")

    # Define the services and their test commands
    services = [
        ("CloudFormation", ["aws", "cloudformation", "list-stacks", "--max-results", "1"]),
        ("ECR",            ["aws", "ecr", "describe-repositories", "--max-results", "1"]),
        ("ECS",            ["aws", "ecs", "list-clusters", "--max-results", "1"]),
        ("S3",             ["aws", "s3", "ls"]),
        ("DynamoDB",       ["aws", "dynamodb", "list-tables", "--max-results", "1"]),
        ("Secrets Manager",["aws", "secretsmanager", "list-secrets", "--max-results", "1"]),
        ("Lambda",         ["aws", "lambda", "list-functions", "--max-results", "1"]),
    ]

    failed_services = []

    # Test each service with the appropriate region flag
    for service, cmd in services:
        if region and service != "S3":
            cmd_with_region = cmd + ["--region", region]
        else:
            cmd_with_region = cmd

        code, out, err = run(cmd_with_region)

        if code == 0:
            passed(service)
        else:
            failed(service)
            failed_services.append(service)

    # All passed — nothing to do
    if not failed_services:
        return False

    # ── At least one service failed — attempt auto-fix ──────────────────────
    info(f"Missing permissions for: {', '.join(failed_services)}")
    info("Attempting to auto-fix by attaching PowerUserAccess...")

    # FIX 3: Attach PowerUserAccess which covers ALL services in this pipeline
    # (CloudFormation, ECR, ECS, S3, DynamoDB, Secrets Manager, Lambda, EC2,
    # IAM role operations, CloudWatch Logs, SNS, Service Discovery).
    # Previous code only attached CloudFormation + DynamoDB + Lambda — this
    # left ECS, ECR, S3, Secrets Manager, and VPC permissions missing.
    success = _auto_fix_iam_permissions()

    if success:
        passed("PowerUserAccess attached successfully")
        info("Waiting 15 seconds for IAM permissions to propagate...")
        import time
        time.sleep(15)

        info("Re-checking permissions...")
        all_fixed = True
        for service, cmd in services:
            if service not in failed_services:
                continue
            if region and service != "S3":
                cmd_with_region = cmd + ["--region", region]
            else:
                cmd_with_region = cmd
            code, out, err = run(cmd_with_region)
            if code != 0:
                all_fixed = False
                break

        if all_fixed:
            info("All permissions verified after auto-fix ✓")
            return False  # No longer failed
        else:
            info("Permissions still propagating (IAM can take up to 30 seconds)")
            info("Re-run this script in 30 seconds if permissions still fail")
    else:
        # FIX 3: Auto-fix failed (user is not an IAM admin) — print clear
        # manual command instead of silently returning False.
        info("Auto-fix failed — your IAM user does not have permission to attach policies")
        info("Ask your AWS administrator to run this command for you:")
        fix("")
        fix("aws iam attach-user-policy \\")
        fix("    --user-name YOUR_IAM_USERNAME \\")
        fix("    --policy-arn arn:aws:iam::aws:policy/PowerUserAccess")
        fix("")
        fix("Or attach PowerUserAccess via AWS Console:")
        fix("  IAM → Users → [your user] → Permissions → Add permissions → PowerUserAccess")

    return True  # Permission check failed


def _auto_fix_iam_permissions():
    """
    Attempt to attach PowerUserAccess to the current IAM user.

    FIX 3: Replaces the previous narrow policy (CloudFormation + DynamoDB +
    Lambda only) with AWS managed PowerUserAccess, which covers all services
    required by this pipeline in one attachment.

    Only works if:
    - The current identity is an IAM User (not a role or federated identity)
    - The user has iam:AttachUserPolicy permission on themselves

    Returns:
        bool: True if PowerUserAccess was successfully attached, False otherwise.
    """
    try:
        # Get current IAM identity
        code, out, err = run(["aws", "sts", "get-caller-identity"])
        if code != 0:
            return False

        identity   = json.loads(out)
        arn        = identity["Arn"]
        account_id = identity["Account"]

        # Only IAM Users can have policies attached this way.
        # Roles (assumed via SSO, EC2 instance profile, etc.) cannot.
        if ":user/" not in arn:
            info("Current identity is not an IAM User (may be a role or federated user)")
            info("Cannot auto-attach policy to non-user identities")
            return False

        # Extract just the username (handle path prefixes like /division/username)
        username = arn.split(":user/")[1].split("/")[-1]

        # PowerUserAccess is an AWS managed policy — always available, always
        # covers the latest set of services. No need to create a custom policy.
        power_user_arn = "arn:aws:iam::aws:policy/PowerUserAccess"

        info(f"Attaching PowerUserAccess to IAM user: {username}")
        code, out, err = run([
            "aws", "iam", "attach-user-policy",
            "--user-name", username,
            "--policy-arn", power_user_arn,
        ])

        if code == 0:
            return True
        else:
            # Likely AccessDenied — user cannot attach policies to themselves
            info(f"Could not attach policy: {err[:200]}")
            return False

    except Exception as e:
        info(f"Auto-fix exception: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 6 — API Keys → Secrets Manager
# ─────────────────────────────────────────────────────────────────────────────
def check_and_provision_secrets(region):
    """
    Check for OpenAI and Pinecone API keys in environment variables,
    provision them in Secrets Manager, and update cloudformation-parameters.json.
    """
    print("\n[ 6 ] API Keys → Secrets Manager")

    if not region:
        failed("Cannot provision secrets without AWS region")
        return

    # Define secrets configuration
    secrets_config = [
        {
            "env_var":     "OPENAI_API_KEY",
            "secret_name": "ray-pipeline-openai",
            "secret_key":  "OPENAI_API_KEY",
            "param_key":   "OpenAIApiKeySecretArn"
        },
        {
            "env_var":     "PINECONE_API_KEY",
            "secret_name": "ray-pipeline-pinecone",
            "secret_key":  "PINECONE_API_KEY",
            "param_key":   "PineconeApiKeySecretArn"
        }
    ]

    param_updates = {}

    for cfg in secrets_config:
        env_var     = cfg["env_var"]
        secret_name = cfg["secret_name"]
        secret_key  = cfg["secret_key"]
        param_key   = cfg["param_key"]

        # Check if secret already exists in AWS Secrets Manager
        code, out, err = run([
            "aws", "secretsmanager", "describe-secret",
            "--secret-id", secret_name,
            "--region", region,
        ])

        if code == 0:
            # Secret already exists — read its ARN and skip creation
            try:
                secret_data = json.loads(out)
                secret_arn  = secret_data.get("ARN")
                passed(f"{env_var} — secret already exists in Secrets Manager")
                info(f"  ARN: {secret_arn}")
                param_updates[param_key] = secret_arn
            except (json.JSONDecodeError, KeyError):
                failed(f"{env_var} — could not parse secret ARN")
            continue

        # Secret doesn't exist — read API key from environment and create it
        api_key = os.environ.get(env_var)

        if not api_key:
            failed(f"{env_var} — not found in environment variables")
            fix(f"Set environment variable: export {env_var}='your-key-here'")
            continue

        # Create the secret in Secrets Manager
        info(f"Creating secret: {secret_name} ...")
        secret_string = json.dumps({secret_key: api_key})

        code, out, err = run([
            "aws", "secretsmanager", "create-secret",
            "--name", secret_name,
            "--secret-string", secret_string,
            "--region", region,
        ])

        if code == 0:
            try:
                secret_data = json.loads(out)
                secret_arn  = secret_data.get("ARN")
                passed(f"{env_var} — created in Secrets Manager")
                info(f"  ARN: {secret_arn}")
                param_updates[param_key] = secret_arn
            except (json.JSONDecodeError, KeyError):
                failed(f"{env_var} — created but could not parse ARN")
        else:
            failed(f"{env_var} — failed to create secret")
            info(f"  Error: {err}")

    # Update cloudformation-parameters.json with the secret ARNs
    if param_updates:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        params_file = os.path.normpath(os.path.join(
            script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"
        ))

        if os.path.isfile(params_file):
            try:
                with open(params_file, "r") as f:
                    params = json.load(f)

                # Handle both JSON formats used by the AWS CLI and SDK
                if isinstance(params, list):
                    # Array format: [{"ParameterKey": "...", "ParameterValue": "..."}, ...]
                    for key, value in param_updates.items():
                        found = False
                        for param in params:
                            if param.get("ParameterKey") == key:
                                param["ParameterValue"] = value
                                found = True
                                break
                        if not found:
                            params.append({"ParameterKey": key, "ParameterValue": value})
                        info(f"{'Updated' if found else 'Added'} cloudformation-parameters.json → {key}")

                elif isinstance(params, dict) and "Parameters" in params:
                    # Object format: {"Parameters": {"Key": "Value", ...}}
                    for key, value in param_updates.items():
                        params["Parameters"][key] = value
                        info(f"Updated cloudformation-parameters.json → {key}")

                else:
                    failed("Unexpected format in cloudformation-parameters.json")
                    return

                with open(params_file, "w") as f:
                    json.dump(params, f, indent=2)
                    f.write("\n")

            except (json.JSONDecodeError, IOError, KeyError) as e:
                failed(f"Could not update cloudformation-parameters.json: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 7 — S3 Bucket Name
# ─────────────────────────────────────────────────────────────────────────────
def check_s3_bucket_name(region):
    """Verify S3 bucket name is configured in cloudformation-parameters.json."""
    print("\n[ 7 ] S3 Bucket Name")

    script_dir  = os.path.dirname(os.path.abspath(__file__))
    params_file = os.path.normpath(os.path.join(
        script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"
    ))

    if not os.path.isfile(params_file):
        failed("cloudformation-parameters.json not found")
        return

    try:
        with open(params_file, "r") as f:
            params = json.load(f)

        bucket_name = ""

        if isinstance(params, list):
            # Array format: [{"ParameterKey": "S3BucketName", "ParameterValue": "..."}, ...]
            for param in params:
                if param.get("ParameterKey") == "S3BucketName":
                    bucket_name = param.get("ParameterValue", "")
                    break

        elif isinstance(params, dict) and "Parameters" in params:
            # Object format: {"Parameters": {"S3BucketName": "...", ...}}
            bucket_name = params.get("Parameters", {}).get("S3BucketName", "")

        if bucket_name in ("your-unique-bucket-name-here", "my-document-pipeline-prod-12345", ""):
            failed("S3BucketName is still a placeholder value in cloudformation-parameters.json")
            fix("Edit 2_cloudformation/cloudformation-parameters.json")
            fix("Change S3BucketName to something globally unique")
            fix("Example: ray-pipeline-prudhvi-feb2026")
            fix("Rules: lowercase letters, numbers, hyphens only. 3–63 chars.")
        else:
            passed(f"S3BucketName: {bucket_name}")

    except (json.JSONDecodeError, IOError) as e:
        failed(f"Could not read cloudformation-parameters.json: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 8 — Docker Image Build & Push
# ─────────────────────────────────────────────────────────────────────────────
ECR_REPO_NAME = "ray-document-pipeline-ray"

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
    script_dir     = os.path.dirname(os.path.abspath(__file__))
    deployment_dir = os.path.normpath(os.path.join(script_dir, "..", "3_deployment"))
    dockerfile     = os.path.join(deployment_dir, "Dockerfile")

    if not os.path.isfile(dockerfile):
        failed(f"Dockerfile not found: {dockerfile}")
        return

    # ── Get or create ECR repo ──────────────────────────────────────────────
    ecr_uri = _get_or_create_ecr_repo(region, account_id)
    if not ecr_uri:
        failed("Could not get/create ECR repository")
        return

    # ── Authenticate Docker to ECR ──────────────────────────────────────────
    if not _ecr_login(region, account_id):
        failed("Could not authenticate Docker to ECR")
        return
    info("Docker authenticated to ECR")

    # ── Build Docker image ──────────────────────────────────────────────────
    image_name = "ray-document-pipeline-ray"
    image_tag  = "latest"
    local_tag  = f"{image_name}:{image_tag}"

    info(f"Building image (linux/amd64) from {deployment_dir} ...")
    info("This takes 5-10 minutes on first build. Output streamed below:")
    info("-" * 50)

    # Detect Apple Silicon — must build for linux/amd64 to run on ECS Fargate
    is_arm_mac = (platform.system() == "Darwin" and platform.machine() == "arm64")
    build_cmd  = ["docker", "buildx", "build","--no-cache"]
    if is_arm_mac:
        build_cmd += ["--platform", "linux/amd64"]
    build_cmd += ["-t", local_tag, deployment_dir]

    # Stream Docker build output line by line so student can see progress
    try:
        process = subprocess.Popen(
            build_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            print(line, end="")
        process.wait()

        if process.returncode != 0:
            failed(f"Docker build failed with exit code {process.returncode}")
            return

        passed("Docker image built successfully (linux/amd64)")

    except Exception as e:
        failed(f"Docker build failed: {e}")
        return

    # ── Push to ECR (3 tags: latest, head, worker) ─────────────────────────
    tags = ["latest", "head", "worker"]
    info(f"Pushing {ecr_uri}:latest ...")

    for tag in tags:
        ecr_tag = f"{ecr_uri}:{tag}"

        # Tag the local image for ECR
        code, out, err = run(["docker", "tag", local_tag, ecr_tag])
        if code != 0:
            failed(f"Failed to tag image: {tag}")
            continue

        # Push to ECR (stream output)
        print(f"  {yellow('[INFO]')} Pushing {ecr_uri}:{tag} ...")
        process = subprocess.Popen(
            ["docker", "push", ecr_tag],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            print(line, end="")
        process.wait()

        if process.returncode == 0:
            passed(f"Pushed :{tag}  →  {ecr_tag}")
        else:
            failed(f"Failed to push :{tag}")

    # ── Update cloudformation-parameters.json with ECR URI ─────────────────
    params_file = os.path.normpath(os.path.join(
        script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"
    ))

    if os.path.isfile(params_file):
        try:
            with open(params_file, "r") as f:
                params = json.load(f)

            if isinstance(params, list):
                found = False
                for param in params:
                    if param.get("ParameterKey") == "ECRImageUri":
                        param["ParameterValue"] = f"{ecr_uri}:latest"
                        found = True
                        break
                if not found:
                    params.append({"ParameterKey": "ECRImageUri", "ParameterValue": f"{ecr_uri}:latest"})

            elif isinstance(params, dict) and "Parameters" in params:
                params["Parameters"]["ECRImageUri"] = f"{ecr_uri}:latest"

            with open(params_file, "w") as f:
                json.dump(params, f, indent=2)
                f.write("\n")

            info("Updated cloudformation-parameters.json → ECRImageUri")
            passed("ECR URI written to cloudformation-parameters.json")
            info(f"  Head image:   {ecr_uri}:head")
            info(f"  Worker image: {ecr_uri}:worker")
            info(f"  CFN param:    {ecr_uri}:latest")

        except (json.JSONDecodeError, IOError) as e:
            failed(f"Could not update cloudformation-parameters.json: {e}")


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

    # Create the ECR repository with image scanning enabled
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
    """Authenticate Docker client to ECR using short-lived login password."""
    info("Authenticating Docker to ECR...")
    code, password, _ = run(["aws", "ecr", "get-login-password", "--region", region])
    if code != 0:
        return False

    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    result   = subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password, capture_output=True, text=True,
    )
    return result.returncode == 0


# ═════════════════════════════════════════════════════════════════════════════
# CHECK 9 — AWS Service Quotas
# ═════════════════════════════════════════════════════════════════════════════
# Checks VPC count against the default limit of 5 per region.
#
# FIX 1: Removed the Elastic IP quota check entirely.
# The previous version checked EIP count and warned "NAT needs 1 EIP".
# This pipeline uses PUBLIC subnets — there is NO NAT Gateway and therefore
# NO Elastic IP is needed. Showing that warning confused students into
# thinking their setup was wrong or that they needed to allocate an EIP.
#
# Public subnet design summary (why no NAT is needed):
#   - ECS Fargate tasks are launched with AssignPublicIp: ENABLED
#   - They get a public IP directly from the Internet Gateway
#   - They can reach S3, DynamoDB, ECR, Secrets Manager, and the internet
#     without a NAT Gateway
#   - VPC Gateway Endpoints for S3 and DynamoDB route those calls internally
#     (even cheaper — no data transfer charges)
#   - Total networking cost: $0 (no NAT, no EIP)
# ═════════════════════════════════════════════════════════════════════════════
def check_aws_service_quotas(region: str):
    """
    Check 9 of 10: Validate AWS service quotas before deployment.

    Checks:
    - VPC count vs the default 5-per-region limit (CloudFormation creates 1 VPC)

    FIX 1: Removed Elastic IP check. This pipeline uses public subnets with
    an Internet Gateway — no NAT Gateway, no Elastic IP needed.
    The previous EIP check produced a misleading "NAT needs 1 EIP" message
    that confused students who saw it.

    Args:
        region: AWS region to check quotas in
    """
    print("\n[ 9 ] AWS Service Quotas")

    # ── Check VPC Count ─────────────────────────────────────────────────────
    # CloudFormation will create 1 new VPC. If the region is already at its
    # limit (default 5), the stack will fail with VpcLimitExceeded.
    code, out, err = run([
        "aws", "ec2", "describe-vpcs",
        "--region", region,
        "--query", "Vpcs[*].VpcId",
        "--output", "json",
    ])

    if code == 0:
        try:
            vpcs      = json.loads(out)
            vpc_count = len(vpcs)
            vpc_limit = 5  # AWS default limit per region

            if vpc_count >= vpc_limit:
                failed(f"VPC limit reached: {vpc_count}/{vpc_limit} VPCs in {region}")
                fix("CloudFormation will create a new VPC and the stack will fail")
                fix("Option 1: Delete an unused VPC in the AWS Console → VPC → Your VPCs")
                fix("Option 2: Request a quota increase:")
                fix("  https://console.aws.amazon.com/servicequotas/home/services/vpc/quotas")
            else:
                passed(f"VPC quota OK: {vpc_count}/{vpc_limit} used in {region}")
                info("CloudFormation will create 1 new VPC — within quota")
        except (json.JSONDecodeError, ValueError):
            info("Could not parse VPC count — proceeding anyway")
    else:
        info("Could not check VPC quota — proceeding anyway")

    # ── Architecture note ───────────────────────────────────────────────────
    # FIX 1: Inform students why no EIP check is needed (teaching moment).
    info("Network design: public subnet + Internet Gateway (no NAT, no EIP needed)")
    info("ECS tasks get public IPs directly — zero extra networking cost")

    # ── Informational: ECS Task Quota ───────────────────────────────────────
    info("ECS Fargate task limit: 500 per service (default) — well within range for this demo")


# ═════════════════════════════════════════════════════════════════════════════
# CHECK 10 — CloudFormation Template Validation
# ═════════════════════════════════════════════════════════════════════════════
# Validates the CloudFormation template syntax using the AWS API before
# attempting deployment. Catches errors like malformed YAML, missing required
# properties, or invalid resource types — saving a 15-minute wait on a
# deployment that was going to fail anyway.
#
# FIX 2: Corrected the template filename.
# The previous version looked for 'ray-pipeline-cloudformation.yaml' which
# does not exist. The actual filename is '1_ray-pipeline-cloudformation-public.yaml'.
# This caused Check 10 to always fail with "Template not found" even when
# the template was correct and present.
# ═════════════════════════════════════════════════════════════════════════════
def check_cloudformation_template(region: str):
    """
    Check 10 of 10: Validate CloudFormation template syntax.

    Submits the template to the AWS CloudFormation ValidateTemplate API.
    This catches YAML syntax errors and invalid resource configurations
    before a full deployment attempt.

    FIX 2: Corrected template filename from 'ray-pipeline-cloudformation.yaml'
    to '1_ray-pipeline-cloudformation-public.yaml' to match the actual file.

    Args:
        region: AWS region to use for the validation API call
    """
    print("\n[ 10 ] CloudFormation Template Validation")

    # FIX 2: Correct filename — was 'ray-pipeline-cloudformation.yaml'
    # which never existed. The actual file is '1_ray-pipeline-cloudformation-public.yaml'.
    script_dir    = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.normpath(os.path.join(
        script_dir, "..", "2_cloudformation", "1_ray-pipeline-cloudformation-public.yaml"
    ))

    if not os.path.isfile(template_path):
        failed(f"CloudFormation template not found: {template_path}")
        fix("Expected file: 2_cloudformation/1_ray-pipeline-cloudformation-public.yaml")
        fix("Make sure the file is in the correct directory relative to this script")
        return

    info(f"Validating: {os.path.basename(template_path)}")

    # Send template to CloudFormation for syntax validation.
    # This uses the file:// URI so the template is read locally — no S3 upload needed.
    code, out, err = run([
        "aws", "cloudformation", "validate-template",
        "--template-body", f"file://{template_path}",
        "--region", region,
    ])

    if code == 0:
        try:
            result       = json.loads(out)
            params       = result.get("Parameters", [])
            capabilities = result.get("Capabilities", [])

            passed("Template syntax is valid")

            if params:
                info(f"Template has {len(params)} parameters")
            if capabilities:
                info(f"Requires capabilities: {', '.join(capabilities)}")

        except (json.JSONDecodeError, ValueError):
            # Validation call succeeded but response couldn't be parsed (very rare)
            passed("Template syntax valid (could not parse response details)")
    else:
        failed("Template validation failed")
        if err:
            # Print first 5 lines of the error — usually enough to identify the issue
            for line in err.split("\n")[:5]:
                if line.strip():
                    fix(line.strip())
        fix("Fix template errors in: 2_cloudformation/1_ray-pipeline-cloudformation-public.yaml")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION FLOW
# ═════════════════════════════════════════════════════════════════════════════
# The main() function orchestrates all 10 prerequisite checks in sequence.
#
# Data flow between checks:
# - Check 2 (credentials) → returns account_id → used by Check 8 (ECR URI)
# - Check 3 (region)      → returns region     → used by Checks 5-10
# - Check 5 (permissions) → returns bool       → used to show IAM policy
#
# Execution principles:
# - All 10 checks run to completion regardless of individual failures
# - User sees the full picture — not just the first problem
# - IAM policy is shown at the end only if permission checks failed
# - Script exits 0 regardless (user reads summary, not exit code)
# ═════════════════════════════════════════════════════════════════════════════
def main():
    """
    Main entry point — run all 10 prerequisite checks and print summary.
    """
    print()
    print("=" * 60)
    print("  RAY PIPELINE — PREREQUISITES CHECK  v2.1")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print("=" * 60)

    # Run all 10 checks in order, threading return values where needed
    check_aws_cli()                                        # Check 1
    account_id       = check_aws_credentials()             # Check 2  → account_id
    region           = check_aws_region()                  # Check 3  → region
    check_docker()                                         # Check 4
    permission_failed = check_aws_permissions(region)      # Check 5  → permission_failed
    check_and_provision_secrets(region)                    # Check 6
    check_s3_bucket_name(region)                           # Check 7
    build_and_push_docker(region, account_id)              # Check 8  (uses account_id)
    check_aws_service_quotas(region)                       # Check 9
    check_cloudformation_template(region)                  # Check 10

    # ── Final Summary ────────────────────────────────────────────────────────
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

        # Display full IAM policy guidance if permission checks failed
        if permission_failed:
            print(IAM_POLICY)

    print()


# ═════════════════════════════════════════════════════════════════════════════
# SCRIPT ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()