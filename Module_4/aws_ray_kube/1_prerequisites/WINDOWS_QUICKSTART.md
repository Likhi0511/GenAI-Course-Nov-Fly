# EKS Ray Pipeline — Windows Quickstart

> **Prefer PowerShell** (Win 10/11). CMD works but has no colour output.  
> Run all commands in the **same terminal window** so environment variables persist.

---

## Step 0 — Install tools (one-time)

Open **PowerShell as Administrator** and run:

```powershell
# AWS CLI
winget install Amazon.AWSCLI

# Docker Desktop  (restart required after install)
winget install Docker.DockerDesktop

# kubectl
winget install Kubernetes.kubectl

# helm
winget install Helm.Helm

# Restart PowerShell after all installs, then verify:
aws --version
docker --version
kubectl version --client
helm version --short
```

> **No winget?** Download installers manually:
> - AWS CLI: https://awscli.amazonaws.com/AWSCLIV2.msi
> - Docker Desktop: https://www.docker.com/products/docker-desktop
> - kubectl: https://kubernetes.io/docs/tasks/tools/install-kubectl-windows/
> - helm: https://github.com/helm/helm/releases (download the Windows zip)

---

## Step 1 — Configure AWS CLI

```powershell
aws configure
# Enter: Access Key ID, Secret Access Key, region (us-east-1), output (json)

# Confirm it works:
aws sts get-caller-identity
# Should show your Account ID, UserId, and Arn
```

---

## Step 2 — Set API keys

**PowerShell:**
```powershell
$env:OPENAI_API_KEY  = "sk-..."
$env:PINECONE_API_KEY = "pcsk_..."

# Confirm they're set:
echo $env:OPENAI_API_KEY
echo $env:PINECONE_API_KEY
```

**CMD (if you must use CMD):**
```cmd
set OPENAI_API_KEY=sk-...
set PINECONE_API_KEY=pcsk_...
```

> ⚠️ These are session-only. If you close the terminal, re-run the `set` /
> `$env:` commands before running the scripts again.

---

## Step 3 — Start Docker Desktop

Open **Docker Desktop** from the Start menu and wait for it to show
"Docker Desktop is running" in the system tray.

Then confirm Docker is ready:
```powershell
docker ps
# Should show an empty table, NOT "error during connect"
```

---

## Step 4 — Navigate to the right folder

```powershell
cd Module_4\aws_ray\1_prerequisites

# Confirm you're in the right place:
dir
# Should show: check_prerequisites.py  check_prerequisites_windows.py  backup\
```

---

## Step 5 — Run prerequisites check

```powershell
python check_prerequisites.py
```

This does 10 checks automatically:
- Validates AWS CLI, credentials, region, Docker
- Checks kubectl + helm are installed  ← new EKS requirement
- Stores API keys in AWS Secrets Manager
- **Builds the Docker image and pushes to ECR** (~8-12 min first run)
- Validates `eks-cluster.yaml` syntax

> **Apple Silicon note:** Not applicable on Windows — `check_prerequisites.py`
> only adds `--platform linux/amd64` on Mac ARM. Windows is already x86_64.

---

## Step 6 — Deploy CloudFormation

```powershell
cd ..\2_cloudformation

python step1_deploy_cloudformation.py
```

Creates: VPC, EKS cluster, node group, IRSA, S3, DynamoDB, Lambda.  
**Takes ~20 minutes.** The script waits and shows progress.

---

## Step 7 — Setup EKS  ← New step (no ECS equivalent)

```powershell
python step1b_setup_eks.py
```

This is what CloudFormation did automatically on ECS but requires a
separate step on EKS. It:
- Configures `kubectl` to talk to the new cluster
- Installs cert-manager + KubeRay operator via Helm
- Creates the Kubernetes namespace, ServiceAccount (IRSA), and RBAC
- Copies API keys from Secrets Manager into a Kubernetes Secret
- Deploys the RayCluster manifest (head + workers, autoscales to 10)
- Waits for the Ray head pod to be Ready

**Takes ~8 minutes.**

---

## Step 8 — Download clinical trial PDFs

```powershell
python step2_download_clinical_trials.py
```

Downloads 20 PDFs to `clinical_trials_20\` folder in the current directory.

---

## Step 9 — Upload PDFs to S3

```powershell
python step3_upload_to_s3.py
```

Uploads PDFs → S3 → Lambda fires → DynamoDB PENDING records created →
`ray_orchestrator.py` (running in head pod) picks them up automatically.

---

## OR — Run steps 6–9 in one shot

```powershell
python orchestrator.py
```

---

## Monitor

```powershell
# See all Ray pods (head + workers)
kubectl get pods -n ray-pipeline

# Stream orchestrator logs (same as "aws logs tail" on ECS)
kubectl logs -f -n ray-pipeline -l ray.io/node-type=head

# Check document processing status
aws dynamodb scan --table-name ray-document-pipeline-control

# Ray Dashboard (port-forward — no LoadBalancer needed)
kubectl port-forward svc/ray-dashboard 8265:8265 -n ray-pipeline
# Then open http://localhost:8265
```

---

## Tear down

```powershell
cd Module_4\aws_ray\2_cloudformation
python -c "
import subprocess, sys
r = input('Delete entire stack? This removes EKS, DynamoDB, S3. Type yes: ')
if r == 'yes':
    subprocess.run(['./deploy.sh', '--destroy'], shell=True, check=True)
else:
    print('Aborted')
"
```

Or directly:
```powershell
# Windows uses 'sh deploy.sh' since .sh files don't run natively
# Install Git for Windows — it ships with Git Bash which can run .sh files
# Then in Git Bash:
bash deploy.sh --destroy
```

---

## Common Windows issues

| Error | Fix |
|-------|-----|
| `'kubectl' is not recognized` | Close and reopen PowerShell after `winget install` — PATH needs to refresh |
| `'helm' is not recognized` | Same — reopen PowerShell |
| `error during connect: Docker Desktop is not running` | Open Docker Desktop from Start menu and wait for it to fully start |
| `Unable to locate credentials` | Run `aws configure` — credentials weren't saved |
| `Access is denied` on winget | Run PowerShell as Administrator |
| `helm: execution of scripts is disabled` | Run: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `Python was not found` | Install from https://python.org — tick "Add Python to PATH" during install |
| API keys gone after reopen | Re-run the `$env:` commands — they don't persist across sessions |

---

## Folder structure reference

```
Module_4\
  aws_ray\
    1_prerequisites\
      check_prerequisites.py      ← Run from here (Step 5)
    2_cloudformation\
      eks-cluster.yaml
      ray-cluster.yaml
      k8s-supporting.yaml
      step1_deploy_cloudformation.py   ← Steps 6-9 run from here
      step1b_setup_eks.py
      step2_download_clinical_trials.py
      step3_upload_to_s3.py
      orchestrator.py
    3_deployment\
      Dockerfile
      ray_orchestrator.py
      ray_tasks.py
      config.py
      (all other pipeline Python files)
```