# Troubleshooting

Common errors encountered during development and production, with root causes
and fixes. Organized by category.

---

## Encoding Errors

### `UnicodeEncodeError: 'latin-1' codec can't encode character '\uf0b7'`

**Where:** Stage 5 (load to Pinecone), during `pinecone.upsert()`

**Root cause:** Clinical/pharma PDFs contain Windows PUA (Private Use Area)
characters — typically Wingdings bullets (U+F0B7, U+F0A7) and Symbol font
glyphs. Docling correctly preserves these during extraction. When the vectors
and metadata are upserted to Pinecone, urllib3 serializes the HTTP request
body using Latin-1 encoding (per HTTP/1.1 spec RFC 2616 §2.2). Latin-1
cannot represent characters above U+00FF, so it crashes.

**Fix (3 layers, all active):**

1. **Container layer** — `Dockerfile` sets `PYTHONIOENCODING=utf-8`, `LANG=en_US.UTF-8`,
   `LC_ALL=en_US.UTF-8`. `sitecustomize.py` forces UTF-8 on `sys.stdout/stderr`
   at interpreter startup.

2. **Transport layer** — `core/encoding.py` → `patch_urllib3_latin1()` monkey-patches
   `urllib3.request.RequestMethods.urlopen` to encode request bodies as UTF-8
   instead of Latin-1 before they hit the wire.

3. **Application layer** — `core/encoding.py` → `sanitize_metadata()` replaces
   known PUA characters with named equivalents (U+F0B7 → `•`, U+F0A7 → `◆`)
   and strips anything that still can't survive a Latin-1 round-trip.

**If it still happens:** A new PUA character appeared that isn't in the
replacement map. Add it to the `PUA_REPLACEMENTS` dict in `core/encoding.py`:

```python
PUA_REPLACEMENTS = {
    "\uf0b7": "•",     # Wingdings bullet
    "\uf0a7": "◆",     # Wingdings diamond
    "\uf0fc": "✓",     # Wingdings checkmark
    "\uf0d8": "▲",     # Wingdings triangle
    "\uf0NEW": "?",    # ← Add the new character here
}
```

### `UnicodeDecodeError: 'charmap' codec can't decode byte 0x81`

**Where:** `check_prerequisites.py` on Windows, during Docker build/push

**Root cause:** Windows Python defaults to `cp1252` for subprocess I/O.
Docker build output contains Unicode progress bars (`━`, `█`, `▏`) that
`cp1252` cannot decode.

**Fix:** Use `check_windows.py` instead of `check.py`. Both scripts include
`encoding='utf-8', errors='replace'` on all subprocess calls, but
`check_windows.py` also runs `chcp 65001` and reconfigures `sys.stdout`.

**Manual workaround:**
```cmd
chcp 65001
python check.py
```

### `UnicodeDecodeError` reading JSON files with mixed encodings

**Where:** Stages 3–5, reading output from a previous stage

**Root cause:** Some PDFs produce text that includes both UTF-8 and
Windows-1252 sequences (smart quotes, em dashes). If a stage writes JSON
without explicit UTF-8 encoding, the next stage may fail to read it.

**Fix:** All JSON I/O in the pipeline uses `core/encoding.py`:
- `write_json_utf8()` — always writes with `ensure_ascii=False, encoding='utf-8'`
- `read_json_robust()` — tries UTF-8 first, falls back to `latin-1`, then `cp1252`

If you encounter this with a new file, check which stage wrote it and ensure
it uses these functions instead of raw `json.dump()`.

---

## Out of Memory (OOM)

### `RuntimeError: DataLoader worker is killed by signal: Killed (OOM)`

**Where:** Stage 1 (extract), Docling's internal OCR/table detection models

**Root cause:** Docling loads PyTorch models for table structure detection.
Combined with the PDF page content, this can exceed the ECS task memory limit.
The 16 GB worker setting handles most documents, but extremely large PDFs
(200+ pages with many tables) can exceed it.

**Fixes:**
- Increase `RayWorkerMemory` in `cloudformation-parameters.json` (valid
  Fargate values: 8192, 16384, 30720 MB)
- Set `do_table_structure=False` in `stages/extract.py` for problematic PDFs
- Split very large PDFs into page ranges before processing

### `ray.exceptions.OutOfMemoryError: Task was killed due to OOM`

**Where:** Any stage, but most common in Stage 1 (extract) and Stage 4 (embed)

**Root cause:** Ray's memory monitor kills tasks that exceed the worker's
available memory. The Ray object store also consumes memory.

**Fixes:**
- Increase worker memory (see above)
- Set `RAY_memory_monitor_refresh_ms=0` to disable Ray's memory monitor
  (not recommended for production — better to right-size memory)
- For Stage 4 (embed): reduce batch size in `stages/embed.py` from 100 to 50

### `Cannot allocate memory` in Docker build

**Where:** `check_prerequisites.py` Check 8, during `docker buildx build`

**Root cause:** Docker Desktop has a memory limit (default 2 GB on macOS).
Building the pipeline image requires ~4 GB (PyTorch, Docling, Ray).

**Fix:** Increase Docker Desktop memory limit:
- macOS: Docker Desktop → Settings → Resources → Memory → 8 GB
- Windows: Docker Desktop → Settings → Resources → Memory → 8 GB
- Linux: Docker uses host memory (unlikely to hit this)

---

## Ray Scheduling

### `ray.exceptions.RayTaskError: No available worker to run this task`

**Where:** Orchestrator, when dispatching stage tasks

**Root cause:** All Ray workers are busy processing other documents. The
orchestrator tried to submit a task but no worker was free to accept it.

**Fixes:**
- Increase `MaxWorkers` in CloudFormation parameters
- Wait for current documents to finish — the orchestrator retries automatically
- Check if workers are stuck (see "Documents stuck IN_PROGRESS" below)

### `ray.exceptions.RayActorError: connection to worker lost`

**Where:** Any `ray.get()` call in the orchestrator

**Root cause:** The ECS task running the worker was terminated (Fargate Spot
reclaim, OOM kill, or ECS rolling deployment). Ray cannot reconnect to a
dead worker.

**Fix:** This is handled automatically. The orchestrator catches
`RayActorError`, marks the document as `FAILED`, and it becomes eligible
for retry. If using Fargate Spot, this is expected and recoverable.

### `GcsClient timed out when getting address`

**Where:** Worker startup, connecting to head node

**Root cause:** The Ray worker cannot reach the head node at `ray-head.local:6379`.
This usually means the head node service hasn't started yet, or Cloud Map
DNS propagation hasn't completed.

**Fixes:**
- Wait 1–2 minutes after head service starts for DNS propagation
- Check that both services are in the same VPC/subnet
- Verify security group allows all traffic within the cluster
- Check head service logs: `aws logs tail /ecs/ray-document-pipeline/ray-head --follow`

---

## DynamoDB / Pipeline State

### Documents stuck in `IN_PROGRESS`

**Where:** DynamoDB control table, document never transitions to COMPLETED

**Root cause (most common):** The orchestrator instance that claimed the
document was terminated (ECS rolling deploy, Fargate Spot reclaim) before
it could update the status.

**Fix:** Manually reset to PENDING:

```bash
aws dynamodb update-item \
    --table-name ray-document-pipeline-control \
    --key '{"document_id": {"S": "NCT04368728_Remdesivir"}}' \
    --update-expression "SET #s = :pending, updated_at = :now" \
    --expression-attribute-names '{"#s": "status"}' \
    --expression-attribute-values '{
        ":pending": {"S": "PENDING"},
        ":now": {"S": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"} 
    }'
```

### `ConditionalCheckFailedException` in orchestrator logs

**Where:** `orchestration/dynamodb.py` → `claim_document()`

**Root cause:** Another orchestrator instance already claimed this document.
This is expected behavior during rolling deployments or when running
multiple head tasks for HA.

**Fix:** No fix needed — this is the concurrency control mechanism working
correctly. The losing instance skips the document and picks up the next one.

---

## CloudFormation

### `ROLLBACK_COMPLETE` — stack creation failed

**Where:** Step 1, after 10–15 minute wait

**Root cause:** One of the 30+ resources failed to create. Common causes:
- ECR image doesn't exist (didn't run prerequisites)
- VPC limit exceeded (Check 9 in prerequisites should catch this)
- IAM permission denied
- S3 bucket name already taken globally

**Fix:** Check the Events tab in CloudFormation console for the specific
resource that failed. Delete the stack, fix the issue, and re-run:

```bash
aws cloudformation delete-stack --stack-name ray-document-pipeline
aws cloudformation wait stack-delete-complete --stack-name ray-document-pipeline
cd deploy/steps
python step1_deploy_stack.py
```

### Template exceeds 51,200 byte limit

**Where:** Step 1, during `aws cloudformation create-stack`

**Fix:** Already handled. `step1_deploy_stack.py` uploads the template to S3
first and uses `--template-url` instead of `--template-body`. If you see
this error, you're running an old version of the deploy script.

---

## Docker / ECS

### `CannotPullContainerError: image not found`

**Where:** ECS task startup

**Root cause:** The ECR image URI in CloudFormation parameters doesn't match
what was pushed. Usually happens when prerequisites ran in a different region
or account than the deployment.

**Fix:**
```bash
# Check what's actually in ECR
aws ecr describe-images --repository-name ray-document-pipeline-ray \
    --query 'imageDetails[*].imageTags'

# Update parameters.json with correct URI and re-deploy
```

### ECS task exits with code 137

**Where:** ECS task logs show `exit code 137`

**Root cause:** Exit code 137 = SIGKILL (128 + 9). The task was killed by
the OOM killer because it exceeded its memory limit.

**Fix:** Increase memory — see OOM section above.

### ECS task exits with code 143

**Where:** ECS task logs show `exit code 143`

**Root cause:** Exit code 143 = SIGTERM (128 + 15). Normal graceful shutdown —
ECS sent SIGTERM during a deployment or scale-in. Not an error.

---

## Performance

### Stage 1 (Extract) takes 5+ minutes per document

**Expected:** 30–60 seconds for a 20-page PDF.

**Root cause:** Docling is downloading models from HuggingFace at runtime
instead of using pre-baked models from the Docker image.

**Fix:** Verify the Dockerfile model download step succeeded:

```bash
docker run --rm ray-document-pipeline-ray:latest \
    python3 -c "from docling.document_converter import DocumentConverter; print('Models OK')"
```

If it re-downloads, the `RUN python3 -m docling.utils.model_downloader` step
in the Dockerfile may have failed silently. Rebuild the image.

### Stage 5 (Load) timeout on large batches

**Expected:** 10–15 seconds for 200 vectors.

**Root cause:** Pinecone upsert timeout with very large metadata payloads.
Clinical trial chunks with full enrichment can have metadata exceeding 40 KB
per vector.

**Fix:** The pipeline already truncates metadata to Pinecone's 40 KB limit.
If you still see timeouts, reduce batch size in `stages/load.py`
(`UPSERT_BATCH_SIZE` from 100 to 50).
