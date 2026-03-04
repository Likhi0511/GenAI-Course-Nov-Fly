"""
steps — Deployment Orchestration (Run from Laptop)

Numbered scripts that deploy the pipeline infrastructure in sequence:

  orchestrator.py       — Runs all 3 steps end-to-end with confirmation prompt
  step1_deploy_stack.py — Upload CFN template to S3, create/update stack, wait
  step2_download_pdfs.py — Download clinical trial PDFs from ClinicalTrials.gov
  step3_upload_to_s3.py — Read bucket name from stack outputs, sync PDFs to S3

Execution order:
  step1 (~10-15 min) → step2 (~1 min) → step3 (~30s)

After step3, the S3 event trigger fires a Lambda that creates PENDING
records in DynamoDB. The Ray orchestrator picks them up automatically.

Can be run individually or via orchestrator.py which chains all three.

Usage:
    cd deploy/steps
    python orchestrator.py        # all 3 steps
    python step1_deploy_stack.py  # just CloudFormation

Author: Prudhvi | Thoughtworks
"""
