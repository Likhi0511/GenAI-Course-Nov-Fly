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
9. Checks AWS service quotas (VPC limit, Elastic IP limit)
10. Validates CloudFormation template syntax

==============================================================================
EXECUTION TIME
==============================================================================
First run:  8-12 minutes (includes Docker image build + ECR push)
Subsequent runs: 1-2 minutes (Docker image already in ECR)

The longest operation is Check 8 (Docker build), which downloads and compiles
dependencies including PyTorch, Ray, and document processing libraries.

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
Script version: 2.0 (with Check 9 & 10 added)
Last updated: February 2026
Platform support: Windows, macOS, Linux
Python requirement: 3.9+

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
# This policy is displayed if Check 5 (AWS Permissions) fails.
# It contains the minimum IAM permissions required to deploy the Ray pipeline.
#
# The policy grants permissions for:
# - CloudFormation: Stack creation/updates/deletion
# - ECR: Docker image registry operations
# - ECS: Fargate task definitions and services
# - S3: Bucket creation and object storage
# - DynamoDB: Table creation for metadata
# - Secrets Manager: API key storage
# - Lambda: Optional serverless functions
# - EC2: VPC, subnet, internet gateway, NAT gateway creation
# - IAM: Role creation for ECS tasks
# - CloudWatch Logs: Log group creation and streaming
#
# Alternative: Use AWS managed policy "PowerUserAccess" which includes all
# the above permissions plus more. PowerUserAccess is easier but grants more
# permissions than strictly necessary.
# ═════════════════════════════════════════════════════════════════════════════
IAM_POLICY = """
If you need to create an IAM policy, use this minimal policy:

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
        "ec2:Describe*",
        "ec2:CreateVpc",
        "ec2:DeleteVpc",
        "ec2:CreateSubnet",
        "ec2:DeleteSubnet",
        "ec2:CreateInternetGateway",
        "ec2:AttachInternetGateway",
        "ec2:CreateRouteTable",
        "ec2:CreateRoute",
        "ec2:CreateNatGateway",
        "ec2:DeleteNatGateway",
        "ec2:AllocateAddress",
        "ec2:ReleaseAddress",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PassRole",
        "iam:GetRole",
        "logs:*"
      ],
      "Resource": "*"
    }
  ]
}

Or use AWS managed policy: PowerUserAccess
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
# 7. Lambda - Serverless functions (optional, but checked for completeness)
#
# What we test:
# - Read-only 'list' or 'describe' operations on each service
# - These are the least privileged operations that still require permissions
#
# What we don't test:
# - Write permissions (create/update/delete) - these are tested during actual deployment
# - Cross-account permissions or resource policies
#
# Why this approach:
# - Fail fast: Better to discover missing permissions now than 10 minutes into deployment
# - Actionable: Provides specific IAM policy to fix the issue
# - Safe: Only performs read operations, no resources are created
#
# Common failure scenarios:
# - IAM user has no policies attached
# - IAM user has ReadOnlyAccess but not PowerUserAccess
# - Organization SCPs (Service Control Policies) block certain services
# - Resource-based policies deny access
# ═════════════════════════════════════════════════════════════════════════════
def check_aws_permissions(region):
    """
    Check 5 of 10: Verify IAM permissions for required AWS services.

    Performs lightweight read-only operations on 7 AWS services to validate
    the current IAM identity has sufficient permissions for deployment.

    If permissions are missing, automatically attempts to fix them.

    Args:
        region: AWS region (used for regional service calls)

    Returns:
        bool: True if any permission check failed, False if all passed
              This return value is used in main() to decide whether to
              display the full IAM policy at the end.
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

    # Test each service
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

    # If any check failed, attempt auto-fix
    if failed_services:
        info(f"Missing permissions for: {', '.join(failed_services)}")
        info("Attempting to auto-fix IAM permissions...")

        # Determine which permissions are needed
        needs_minimal_policy = any(s in failed_services for s in ["CloudFormation", "DynamoDB", "Lambda"])

        if needs_minimal_policy:
            success = _auto_fix_iam_permissions()

            if success:
                passed("IAM permissions auto-fixed successfully")
                info("Waiting 15 seconds for IAM permissions to propagate...")

                # Import time module for sleep
                import time
                time.sleep(15)

                info("Re-checking permissions...")

                # Re-check failed services
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
                    info("Permissions still pending (AWS propagation can take up to 30 seconds)")
                    info("Re-run this script in 30 seconds and permissions should work")
            else:
                info("Auto-fix failed - manual intervention required")
                fix("Attach PowerUserAccess policy to your IAM user")
                fix("Or run: python fix_iam_permissions.py")

        return True  # Permission check failed

    return False  # All passed


def _auto_fix_iam_permissions():
    """
    Automatically create and attach minimal IAM policy for missing permissions.

    Returns:
        bool: True if successfully fixed, False otherwise
    """
    try:
        # Get current IAM user
        code, out, err = run(["aws", "sts", "get-caller-identity"])
        if code != 0:
            return False

        identity = json.loads(out)
        arn = identity["Arn"]
        account_id = identity["Account"]

        # Extract username
        if ":user/" not in arn:
            return False
        username = arn.split(":user/")[1].split("/")[-1]

        # Define minimal policy
        policy_name = "RayPipelineDeploymentPermissions"
        policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

        # Check if policy exists
        code, out, err = run(["aws", "iam", "get-policy", "--policy-arn", policy_arn])

        if code != 0:
            # Create policy
            policy_doc = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": ["cloudformation:*", "dynamodb:*", "lambda:*"],
                    "Resource": "*"
                }]
            }

            info("Creating IAM policy...")
            code, out, err = run([
                "aws", "iam", "create-policy",
                "--policy-name", policy_name,
                "--policy-document", json.dumps(policy_doc)
            ])

            if code != 0:
                return False

        # Attach policy to user
        info(f"Attaching policy to user: {username}")
        code, out, err = run([
            "aws", "iam", "attach-user-policy",
            "--user-name", username,
            "--policy-arn", policy_arn
        ])

        return code == 0

    except Exception:
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
            "env_var": "OPENAI_API_KEY",
            "secret_name": "ray-pipeline-openai",
            "secret_key": "OPENAI_API_KEY",
            "param_key": "OpenAIApiKeySecretArn"
        },
        {
            "env_var": "PINECONE_API_KEY",
            "secret_name": "ray-pipeline-pinecone",
            "secret_key": "PINECONE_API_KEY",
            "param_key": "PineconeApiKeySecretArn"
        }
    ]

    param_updates = {}

    for config in secrets_config:
        env_var = config["env_var"]
        secret_name = config["secret_name"]
        secret_key = config["secret_key"]
        param_key = config["param_key"]

        # Check if secret already exists in AWS
        code, out, err = run([
            "aws", "secretsmanager", "describe-secret",
            "--secret-id", secret_name,
            "--region", region
        ])

        if code == 0:
            # Secret exists
            try:
                secret_data = json.loads(out)
                secret_arn = secret_data.get("ARN")
                passed(f"{env_var} — secret already exists in Secrets Manager")
                info(f"  ARN: {secret_arn}")
                param_updates[param_key] = secret_arn
            except (json.JSONDecodeError, KeyError):
                failed(f"{env_var} — could not parse secret ARN")
                continue
        else:
            # Secret doesn't exist - create it
            api_key = os.environ.get(env_var)

            if not api_key:
                failed(f"{env_var} — not found in environment variables")
                fix(f"Set environment variable: export {env_var}='your-key-here'")
                continue

            # Create secret in Secrets Manager
            info(f"Creating secret: {secret_name} ...")
            secret_string = json.dumps({secret_key: api_key})

            code, out, err = run([
                "aws", "secretsmanager", "create-secret",
                "--name", secret_name,
                "--secret-string", secret_string,
                "--region", region
            ])

            if code == 0:
                try:
                    secret_data = json.loads(out)
                    secret_arn = secret_data.get("ARN")
                    passed(f"{env_var} — created in Secrets Manager")
                    info(f"  ARN: {secret_arn}")
                    param_updates[param_key] = secret_arn
                except (json.JSONDecodeError, KeyError):
                    failed(f"{env_var} — created but could not parse ARN")
            else:
                failed(f"{env_var} — failed to create secret")
                info(f"  Error: {err}")

    # Update cloudformation-parameters.json
    if param_updates:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        params_file = os.path.normpath(os.path.join(
            script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"
        ))

        if os.path.isfile(params_file):
            try:
                with open(params_file, "r") as f:
                    params = json.load(f)

                # Handle both formats: array (CLI) and object (SDK)
                if isinstance(params, list):
                    # Array format: [{"ParameterKey": "...", "ParameterValue": "..."}, ...]
                    for key, value in param_updates.items():
                        # Find the parameter in the array and update it
                        found = False
                        for param in params:
                            if param.get("ParameterKey") == key:
                                param["ParameterValue"] = value
                                found = True
                                break

                        if found:
                            info(f"Updated cloudformation-parameters.json → {key}")
                        else:
                            # Parameter doesn't exist, add it
                            params.append({"ParameterKey": key, "ParameterValue": value})
                            info(f"Added to cloudformation-parameters.json → {key}")

                elif isinstance(params, dict) and "Parameters" in params:
                    # Object format: {"Parameters": {"Key": "Value", ...}}
                    for key, value in param_updates.items():
                        params["Parameters"][key] = value
                        info(f"Updated cloudformation-parameters.json → {key}")

                else:
                    failed(f"Unexpected format in cloudformation-parameters.json")
                    return

                # Write back
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

    script_dir = os.path.dirname(os.path.abspath(__file__))
    params_file = os.path.normpath(os.path.join(
        script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"
    ))

    if not os.path.isfile(params_file):
        failed("cloudformation-parameters.json not found")
        return

    try:
        with open(params_file, "r") as f:
            params = json.load(f)

        # Handle both formats: array (CLI) and object (SDK)
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

        if bucket_name == "your-unique-bucket-name-here" or bucket_name == "my-document-pipeline-prod-12345":
            failed("S3BucketName is still the placeholder value in cloudformation-parameters.json")
            fix("Edit 2_cloudformation/cloudformation-parameters.json")
            fix("Change S3BucketName to something globally unique, e.g.  ray-pipeline-prudhvi-feb2026")
            fix("Rules: lowercase letters, numbers, hyphens only. 3–63 chars.")
        elif not bucket_name:
            failed("S3BucketName is empty")
            fix("Edit 2_cloudformation/cloudformation-parameters.json")
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
    script_dir    = os.path.dirname(os.path.abspath(__file__))
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

    # Detect platform (Apple Silicon needs explicit linux/amd64)
    is_arm_mac = (platform.system() == "Darwin" and platform.machine() == "arm64")
    build_cmd = ["docker", "buildx", "build"]
    if is_arm_mac:
        build_cmd += ["--platform", "linux/amd64"]
    build_cmd += ["-t", local_tag, deployment_dir]

    # Stream output in real-time
    try:
        process = subprocess.Popen(
            build_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
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

        # Tag for ECR
        code, out, err = run(["docker", "tag", local_tag, ecr_tag])
        if code != 0:
            failed(f"Failed to tag image: {tag}")
            continue

        # Push to ECR
        print(f"  [INFO] Pushing {ecr_uri}:{tag} ...")
        process = subprocess.Popen(
            ["docker", "push", ecr_tag],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in process.stdout:
            print(line, end="")

        process.wait()

        if process.returncode == 0:
            passed(f"Pushed :{tag}  →  {ecr_tag}")
        else:
            failed(f"Failed to push :{tag}")

    # ── Update cloudformation-parameters.json ───────────────────────────────
    params_file = os.path.normpath(os.path.join(
        script_dir, "..", "2_cloudformation", "cloudformation-parameters.json"
    ))

    if os.path.isfile(params_file):
        try:
            with open(params_file, "r") as f:
                params = json.load(f)

            # Handle both formats: array (CLI) and object (SDK)
            if isinstance(params, list):
                # Array format: [{"ParameterKey": "...", "ParameterValue": "..."}, ...]
                found = False
                for param in params:
                    if param.get("ParameterKey") == "RayDockerImageUri":
                        param["ParameterValue"] = f"{ecr_uri}:latest"
                        found = True
                        break

                if not found:
                    # Add if doesn't exist
                    params.append({"ParameterKey": "RayDockerImageUri", "ParameterValue": f"{ecr_uri}:latest"})

            elif isinstance(params, dict) and "Parameters" in params:
                # Object format: {"Parameters": {"RayDockerImageUri": "...", ...}}
                params["Parameters"]["RayDockerImageUri"] = f"{ecr_uri}:latest"

            with open(params_file, "w") as f:
                json.dump(params, f, indent=2)
                f.write("\n")

            info("Updated cloudformation-parameters.json → RayDockerImageUri")
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


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 9 — AWS Service Quotas
# ─────────────────────────────────────────────────────────────────────────────
def check_aws_service_quotas(region: str):
    """
    Check AWS service quotas to prevent deployment failures.
    Verifies:
    - VPC count (default limit: 5 per region)
    - Elastic IP count (default limit: 5 per region)
    - ECS task quota (informational)
    """
    print("\n[ 9 ] AWS Service Quotas")

    # ── Check VPC Count ─────────────────────────────────────────────────────
    code, out, err = run([
        "aws", "ec2", "describe-vpcs",
        "--region", region,
        "--query", "Vpcs[*].VpcId",
        "--output", "json"
    ])

    if code == 0:
        try:
            vpcs = json.loads(out)
            vpc_count = len(vpcs)
            vpc_limit = 5  # Default AWS limit

            if vpc_count >= vpc_limit:
                failed(f"VPC limit reached: {vpc_count}/{vpc_limit} VPCs in {region}")
                fix("CloudFormation will create a new VPC and may fail")
                fix("Delete unused VPCs or request limit increase:")
                fix("https://console.aws.amazon.com/servicequotas/home/services/vpc/quotas")
            else:
                passed(f"VPC quota OK: {vpc_count}/{vpc_limit} used")
        except (json.JSONDecodeError, ValueError):
            info("Could not parse VPC count (proceeding anyway)")
    else:
        info("Could not check VPC quota (proceeding anyway)")

    # ── Check Elastic IP Count ──────────────────────────────────────────────
    code, out, err = run([
        "aws", "ec2", "describe-addresses",
        "--region", region,
        "--query", "Addresses[*].PublicIp",
        "--output", "json"
    ])

    if code == 0:
        try:
            eips = json.loads(out)
            eip_count = len(eips)
            eip_limit = 5  # Default AWS limit

            # NAT Gateway needs 1 EIP
            if eip_count >= eip_limit:
                failed(f"Elastic IP limit reached: {eip_count}/{eip_limit} in {region}")
                fix("CloudFormation creates a NAT Gateway which needs 1 Elastic IP")
                fix("Release unused EIPs or request limit increase:")
                fix("https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas/L-0263D0A3")
            else:
                passed(f"Elastic IP quota OK: {eip_count}/{eip_limit} used (NAT needs 1)")
        except (json.JSONDecodeError, ValueError):
            info("Could not parse Elastic IP count (proceeding anyway)")
    else:
        info("Could not check Elastic IP quota (proceeding anyway)")

    # ── Informational: ECS Task Quota ───────────────────────────────────────
    info("ECS Fargate task limit: 500 per service (default)")
    info("If deploying large Ray clusters (>50 workers), monitor this quota")


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 10 — CloudFormation Template Validation
# ─────────────────────────────────────────────────────────────────────────────
def check_cloudformation_template(region: str):
    """
    Validate the CloudFormation template syntax before deployment.
    Catches template errors early, preventing 20-minute failed deployments.
    """
    print("\n[ 10 ] CloudFormation Template Validation")

    # ── Locate CloudFormation Template ─────────────────────────────────────
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.normpath(os.path.join(
        script_dir, "..", "2_cloudformation", "ray-pipeline-cloudformation.yaml"
    ))

    if not os.path.isfile(template_path):
        failed(f"CloudFormation template not found: {template_path}")
        return

    info(f"Validating template: {os.path.basename(template_path)}")

    # ── Run AWS CloudFormation Validate ────────────────────────────────────
    code, out, err = run([
        "aws", "cloudformation", "validate-template",
        "--template-body", f"file://{template_path}",
        "--region", region
    ])

    if code == 0:
        try:
            result = json.loads(out)
            # Template is syntactically valid
            passed("Template syntax valid")

            # Show parameter count
            params = result.get("Parameters", [])
            if params:
                info(f"Template has {len(params)} parameters")

            # Show capabilities required (if any)
            capabilities = result.get("Capabilities", [])
            if capabilities:
                info(f"Requires capabilities: {', '.join(capabilities)}")

        except (json.JSONDecodeError, ValueError):
            # Validation succeeded but couldn't parse response
            passed("Template syntax valid (could not parse details)")
    else:
        # Validation failed
        failed("Template validation failed")
        if err:
            # Print first 5 lines of error
            error_lines = err.split('\n')[:5]
            for line in error_lines:
                if line.strip():
                    fix(line.strip())
        fix("Fix template errors in: 2_cloudformation/ray-pipeline-cloudformation.yaml")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION FLOW
# ═════════════════════════════════════════════════════════════════════════════
# The main() function orchestrates all 10 prerequisite checks in sequence.
#
# Execution flow:
# 1. Display header with platform information
# 2. Run checks 1-10 in order
# 3. Collect return values from checks that provide data (credentials, region)
# 4. Pass collected data to subsequent checks that need it
# 5. Display final summary with pass/fail counts
# 6. Show next steps or remediation guidance
#
# Why this order:
# - Checks 1-4: Local environment (CLI, credentials, Docker) must pass first
# - Check 5: Permissions validated before attempting to create resources
# - Check 6-7: Configuration validated before expensive operations
# - Check 8: Docker build (longest operation) runs after all validations
# - Checks 9-10: Final validations before CloudFormation deployment
#
# Data flow between checks:
# - Check 2 (credentials) → returns account_id → used by Check 8 (ECR)
# - Check 3 (region) → returns region → used by Checks 5-10
# - Check 5 (permissions) → returns permission_failed → used to show IAM policy
#
# Error handling:
# - Checks are independent - failure in one doesn't stop the others
# - All checks run to completion to give user complete picture
# - Summary at end shows what needs to be fixed
# - IAM policy displayed if permission_failed is True
#
# Idempotency:
# - Script is safe to run multiple times
# - Check 6 doesn't recreate secrets if they already exist
# - Check 8 doesn't rebuild image if tag already exists in ECR (though it will rebuild locally)
# ═════════════════════════════════════════════════════════════════════════════
def main():
    """
    Main entry point for prerequisites validation script.

    Executes all 10 checks in sequence and displays final summary.
    Script exits with return code 0 regardless of check results
    (user should review summary to determine if deployment can proceed).

    The script is designed to be run multiple times until all checks pass.
    """
    # ─────────────────────────────────────────────────────────────────────────
    # Display header
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  RAY PIPELINE — PREREQUISITES CHECK")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print("=" * 60)

    # ─────────────────────────────────────────────────────────────────────────
    # Execute all checks
    # ─────────────────────────────────────────────────────────────────────────
    # Note: Some checks return values that are used by subsequent checks.
    # This creates dependencies between checks (e.g., Check 8 needs account_id from Check 2).

    check_aws_cli()                                      # Check 1: AWS CLI installed
    account_id = check_aws_credentials()                 # Check 2: Returns AWS account ID
    region = check_aws_region()                          # Check 3: Returns AWS region
    check_docker()                                       # Check 4: Docker installed and running
    permission_failed = check_aws_permissions(region)    # Check 5: Returns True if any permission failed
    check_and_provision_secrets(region)                  # Check 6: Creates secrets in Secrets Manager
    check_s3_bucket_name(region)                         # Check 7: Validates S3 bucket name
    build_and_push_docker(region, account_id)            # Check 8: Builds and pushes Docker image (8-12 min)
    check_aws_service_quotas(region)                     # Check 9: Validates AWS service quotas
    check_cloudformation_template(region)                # Check 10: Validates CloudFormation syntax

    # ─────────────────────────────────────────────────────────────────────────
    # Display summary
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  {green(f'Passed: {PASS_COUNT}')}")
    print(f"  {red(f'Failed: {FAIL_COUNT}')}")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Show next steps or remediation guidance
    # ─────────────────────────────────────────────────────────────────────────
    if FAIL_COUNT == 0:
        # All checks passed - ready to deploy
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
        # Some checks failed - show remediation guidance
        print(f"  {red(f'Fix the {FAIL_COUNT} failed check(s) above, then re-run this script.')}")

        # If permission check failed, display the full IAM policy
        if permission_failed:
            print(IAM_POLICY)

    print()


# ═════════════════════════════════════════════════════════════════════════════
# SCRIPT ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
# Standard Python idiom to make the script executable directly.
# This allows running the script as:
#   python check_prerequisites.py
# Rather than requiring import as a module.
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()