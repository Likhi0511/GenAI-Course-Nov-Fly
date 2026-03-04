# Prerequisites Check — Ray Document Processing Pipeline

## Quick Start

```bash
# macOS / Linux
python3 check.py

# Windows (recommended — includes charmap fix + ANSI color support)
python check_windows.py

# Windows (alternative — if check_windows.py is unavailable)
python check.py
```

## What It Does

The script runs **10 automated checks** to validate your environment before
deploying the CloudFormation stack. It takes 1–2 minutes on repeat runs
(8–12 minutes on first run due to Docker image build).

| Check | What It Validates | Cost |
|-------|-------------------|------|
| 1. AWS CLI | Installed and in PATH | Free |
| 2. Credentials | `aws sts get-caller-identity` succeeds | Free |
| 3. Region | Default region is configured | Free |
| 4. Docker | Installed and daemon is running | Free |
| 5. IAM | Permissions for 7 AWS services | Free |
| 6. Secrets | OpenAI + Pinecone keys in Secrets Manager | $0.80/mo |
| 7. S3 Bucket | Name in parameters.json is valid & unique | Free |
| 8. Docker/ECR | Build image + push to ECR (3 tags) | ~$0.32/mo |
| 9. Quotas | VPC count vs 5-per-region limit | Free |
| 10. Template | CloudFormation YAML syntax validation | Free |

## Before You Run

### Required Tools
- **Python 3.9+** (no pip packages needed — stdlib only)
- **AWS CLI v2** — [Install guide](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html)
- **Docker Desktop** (Windows/Mac) or Docker Engine (Linux)

### Required Environment Variables
```bash
# macOS / Linux
export OPENAI_API_KEY="sk-..."
export PINECONE_API_KEY="pcsk_..."

# Windows CMD
set OPENAI_API_KEY=sk-...
set PINECONE_API_KEY=pcsk_...

# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
$env:PINECONE_API_KEY = "pcsk-..."
```

### AWS Credentials
```bash
aws configure
# Enter: Access Key ID, Secret Access Key, Region (e.g. us-east-1), Output (json)
```

## Windows-Specific Notes

### The "charmap" Error (Fixed)

On Windows, Docker build output contains Unicode progress bars (`━`, `█`, `▏`)
that crash Python's default `cp1252` codec:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 in position 47
```

**Both `check.py` and `check_windows.py` have this fix built in.** The scripts
use `encoding='utf-8'` on all subprocess calls so this error cannot occur.

`check_windows.py` adds three extra protections:
1. **`chcp 65001`** — switches the console codepage to UTF-8
2. **`PYTHONIOENCODING=utf-8`** — forces all Python I/O to UTF-8
3. **ANSI colors via ctypes** — enables colored `[PASS]`/`[FAIL]` output
   on Windows 10+ (the cross-platform version disables colors on Windows)

### Docker Desktop Won't Start?

1. Open **"Turn Windows features on or off"**
2. Enable **Windows Subsystem for Linux** and **Virtual Machine Platform**
3. Restart your PC
4. Run `wsl --update` from an admin PowerShell
5. Start Docker Desktop again

## Output Example

```
============================================================
  RAY PIPELINE — PREREQUISITES CHECK  v2.2
  Platform: Darwin 23.4.0
============================================================

[ 1 ] AWS CLI
  [PASS] Installed: 2.15.30

[ 2 ] AWS Credentials
  [PASS] Authenticated as: arn:aws:iam::123456789012:user/prudhvi

...

============================================================
  SUMMARY
============================================================
  Passed: 14
  Failed: 0

  All checks passed! Ready to deploy CloudFormation stack.
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `AWS CLI not found` | [Install AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| `Credentials not configured` | Run `aws configure` |
| `Docker daemon not running` | Start Docker Desktop (Win/Mac) or `sudo systemctl start docker` (Linux) |
| `Permission denied` on Docker | Linux: `sudo usermod -aG docker $USER` then re-login |
| `OPENAI_API_KEY not set` | `export OPENAI_API_KEY='sk-...'` |
| `S3 bucket name is placeholder` | Edit `cloudformation-parameters.json` with a unique bucket name |
| `VPC limit reached` | Delete unused VPCs or request quota increase |
| `charmap codec error` (Windows) | Use `check_windows.py` or run `chcp 65001` first |

## What Happens Next

Once all 10 checks pass:

1. The script has already provisioned your API keys in Secrets Manager
2. Your Docker image is built and pushed to ECR (3 tags: latest, head, worker)
3. `cloudformation-parameters.json` is fully populated with ARNs and URIs
4. **Deploy the stack:** Follow `deploy/cloudformation/DEPLOYMENT.md`

## File Structure

```
deploy/prerequisites/
├── __init__.py          # Package marker
├── check.py             # Cross-platform prerequisites checker
├── check_windows.py     # Windows-enhanced version (recommended for Windows)
└── README.md            # This file
```
