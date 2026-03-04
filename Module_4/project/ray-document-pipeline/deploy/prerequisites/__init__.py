"""
prerequisites — Pre-Deployment Environment Validation

Validates local tools, AWS credentials, IAM permissions, and provisions
resources (Secrets Manager, ECR) before CloudFormation deployment.

Scripts:
  check.py         — Cross-platform (macOS, Linux, Windows) prerequisites checker
  check_windows.py — Windows-enhanced version with chcp 65001, ANSI color via
                     ctypes, and extra Docker Desktop troubleshooting tips

Both scripts run 10 checks:
  1. AWS CLI installed           6. Secrets Manager provisioned
  2. AWS credentials valid       7. S3 bucket name validated
  3. AWS region configured       8. Docker image built & pushed to ECR
  4. Docker running              9. Service quotas checked
  5. IAM permissions verified   10. CloudFormation template validated

Usage:
    python check.py                # macOS / Linux / Windows
    python check_windows.py        # Windows (recommended for Windows users)

Author: Prudhvi | Thoughtworks
"""
