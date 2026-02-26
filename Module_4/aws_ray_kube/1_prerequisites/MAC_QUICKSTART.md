# EKS Ray Pipeline — Mac Quickstart

> Works on both **Intel** and **Apple Silicon (M1/M2/M3)** Macs.  
> Use **Terminal** or **iTerm2**. Run all commands in the **same terminal window**
> so environment variables persist.

---

## Step 0 — Install tools (one-time)

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install everything needed
brew install awscli kubectl helm

# Verify:
aws --version
kubectl version --client --short
helm version --short
```

Then install **Docker Desktop** from https://www.docker.com/products/docker-desktop  
(pick the right version — **Apple Chip** for M1/M2/M3, **Intel Chip** for older Macs)

---

## Step 1 — Configure AWS CLI

```bash
aws configure
# Enter: Access Key ID, Secret Access Key, region (us-east-1), output (json)

# Confirm it works:
aws sts get-caller-identity
# Should show your Account ID, UserId, and Arn
```

---

## Step 2 — Set API keys

```bash
export OPENAI_API_KEY="sk-..."
export PINECONE_API_KEY="pcsk_..."

# Confirm they're set:
echo $OPENAI_API_KEY
echo $PINECONE_API_KEY
```

> ⚠️ These are session-only. If you close the terminal, re-run the `export`
> commands before running the scripts again.
>
> To make them permanent, add them to `~/.zshrc` (zsh, default on modern Macs)
> or `~/.bash_profile` (bash):
> ```bash
> echo 'export OPENAI_API_KEY="sk-..."' >> ~/.zshrc
> echo 'export PINECONE_API_KEY="pcsk_..."' >> ~/.zshrc
> source ~/.zshrc
> ```

---

## Step 3 — Start Docker Desktop

Open **Docker Desktop** from Applications (or Spotlight → `Docker`) and wait
for the whale icon in the menu bar to stop animating.

Then confirm Docker is ready:
```bash
docker ps
# Should show an empty table, NOT "Cannot connect to the Docker daemon"
```

---

## Step 4 — Navigate to the right folder

```bash
cd Module_4/aws_ray/1_prerequisites

# Confirm you're in the right place:
ls
# Should show: check_prerequisites.py  check_prerequisites_windows.py  backup/
```

---

## Step 5 — Run prerequisites check

```bash
python3 check_prerequisites.py
```

This does 10 checks automatically:
- Validates AWS CLI, credentials, region, Docker
- Checks `kubectl` + `helm` are installed  ← new EKS requirement
- Stores API keys in AWS Secrets Manager
- **Builds the Docker image and pushes to ECR** (~8-12 min first run)
- Validates `eks-cluster.yaml` syntax

> **Apple Silicon note:** `check_prerequisites.py` automatically adds
> `--platform linux/amd64` to the Docker build on M1/M2/M3 Macs.
> This ensures the image runs correctly on EKS (x86_64 EC2 nodes).
> You don't need to do anything — it's handled for you.

---

## Step 6 — Deploy CloudFormation

```bash
cd ../2_cloudformation

python3 step1_deploy_cloudformation.py
```

Creates: VPC, EKS cluster, node group, IRSA, S3, DynamoDB, Lambda.  
**Takes ~20 minutes.** The script waits and shows progress.

---

## Step 7 — Setup EKS  ← New step (no ECS equivalent)

```bash
python3 step1b_setup_eks.py
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

```bash
python3 step2_download_clinical_trials.py
```

Downloads 20 PDFs to `clinical_trials_20/` folder in the current directory.

---

## Step 9 — Upload PDFs to S3

```bash
python3 step3_upload_to_s3.py
```

Uploads PDFs → S3 → Lambda fires → DynamoDB PENDING records created →
`ray_orchestrator.py` (running in head pod) picks them up automatically.

---

## OR — Run steps 6–9 in one shot

```bash
python3 orchestrator.py
```

---

## Monitor

```bash
# See all Ray pods (head + workers)
kubectl get pods -n ray-pipeline

# Stream orchestrator logs (same as "aws logs tail" on ECS)
kubectl logs -f -n ray-pipeline -l ray.io/node-type=head

# Check document processing status in DynamoDB
aws dynamodb scan --table-name ray-document-pipeline-control

# Ray Dashboard (port-forward — no LoadBalancer needed)
kubectl port-forward svc/ray-dashboard 8265:8265 -n ray-pipeline
# Then open http://localhost:8265
```

---

## Tear down

```bash
cd Module_4/aws_ray/2_cloudformation
bash deploy.sh --destroy
# Type 'yes' when prompted
# Takes ~15 min — removes EKS cluster, DynamoDB tables, S3 bucket, Lambda
```

---

## Common Mac issues

| Error | Fix |
|-------|-----|
| `brew: command not found` | Install Homebrew — see Step 0 |
| `Cannot connect to the Docker daemon` | Open Docker Desktop from Applications and wait for it to fully start |
| `Unable to locate credentials` | Run `aws configure` — credentials weren't saved |
| `error: exec: "docker buildx": executable file not found` | Update Docker Desktop to latest version (buildx ships with it) |
| `kubectl: command not found` | Run `brew install kubectl` then open a new terminal tab |
| `helm: command not found` | Run `brew install helm` then open a new terminal tab |
| API keys gone after reopen | Re-run the `export` commands, or add them to `~/.zshrc` permanently (see Step 2) |
| `zsh: permission denied: ./deploy.sh` | Run `chmod +x deploy.sh` first |
| Slow Docker build on Apple Silicon | Normal — cross-compiling to linux/amd64 takes longer. First build is ~12 min, subsequent builds use cached layers (~2 min) |

---

## Folder structure reference

```
Module_4/
  aws_ray/
    1_prerequisites/
      check_prerequisites.py      ← Run from here (Step 5)
    2_cloudformation/
      eks-cluster.yaml
      ray-cluster.yaml
      k8s-supporting.yaml
      deploy.sh
      step1_deploy_cloudformation.py   ← Steps 6-9 run from here
      step1b_setup_eks.py
      step2_download_clinical_trials.py
      step3_upload_to_s3.py
      orchestrator.py
    3_deployment/
      Dockerfile
      ray_orchestrator.py
      ray_tasks.py
      config.py
      (all other pipeline Python files)
```