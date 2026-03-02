"""
RAGBench (HotpotQA) Dataset Loader for RAG Evaluation
-----------------------------------------------------
This script does 3 main things:

1. Loads the RAGBench 'hotpotqa' dataset from Hugging Face.
2. Extracts the first 30 samples as a "Golden Dataset" — used to evaluate RAG pipelines.
3. Extracts the first 500 samples as a "Corpus Dataset" — used to populate a Vector DB (e.g. Pinecone).

Each corpus document is flattened and written with metadata (question, reference answer, etc.)
so it can be later embedded and retrieved.
"""

import os
import json
import logging
from pathlib import Path
from datasets import load_dataset
from typing import List, Optional

# ============ Logging Configuration ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ragbench_loader")

# ============ Configuration ============
DS_NAME = "rungalileo/ragbench"  # Hugging Face dataset repo name
CONFIG = "hotpotqa"              # Specific RAGBench subset
SPLIT = "train"                  # We use train split for both corpus and golden

OUT_DIR = Path("ragbench_hotpotqa_exports")  # Output folder for files
OUT_DIR.mkdir(parents=True, exist_ok=True)

GOLDEN_PATH = OUT_DIR / "golden_hotpotqa_30.jsonl"   # Golden evaluation dataset file
CORPUS_PATH = OUT_DIR / "rag_corpus_hotpotqa_500.jsonl"  # Corpus dataset file for Pinecone

# ===========================================================
# Helper Functions
# ===========================================================

def as_text_list(documents: Optional[List], documents_sentences: Optional[List] = None) -> List[str]:
    """
    Normalize the 'documents' field from the dataset into a list of plain text strings.

    Each RAGBench example includes 'documents' and sometimes 'documents_sentences'.
    These can appear in different shapes:
      - list[str]
      - list[dict] containing keys like 'text', 'content', etc.
      - list[list[str]] in 'documents_sentences' (each sentence as a string)

    This function ensures we always return a clean list[str] for downstream use.
    """
    if documents is None:
        return []

    # Case 1: Already a list of strings
    if documents and isinstance(documents[0], str):
        return documents

    # Case 2: list of dicts with possible keys
    candidate_keys = ("text", "content", "page_content", "body")
    out = []
    if documents and isinstance(documents[0], dict):
        for d in documents:
            txt = None
            for k in candidate_keys:
                if k in d and isinstance(d[k], str) and d[k].strip():
                    txt = d[k].strip()
                    break
            # Some dicts have a 'sentences' list instead
            if txt is None and "sentences" in d and isinstance(d["sentences"], list):
                txt = " ".join(s for s in d["sentences"] if isinstance(s, str))
            if txt:
                out.append(txt)
        if out:
            return out

    # Case 3: Fallback to documents_sentences (list of list of str)
    if documents_sentences and isinstance(documents_sentences, list):
        joined = []
        for doc_sents in documents_sentences:
            if isinstance(doc_sents, list):
                joined.append(" ".join(s for s in doc_sents if isinstance(s, str)))
        return joined

    return []

def trunc(s: str, max_chars: int = 8000) -> str:
    """Truncate any long text to avoid massive files (e.g., large documents)."""
    return s if len(s) <= max_chars else s[:max_chars]


# ===========================================================
# Step 1: Load Dataset from Hugging Face
# ===========================================================
logger.info(f"Loading dataset '{DS_NAME}' (config='{CONFIG}', split='{SPLIT}')...")
ds = load_dataset(DS_NAME, CONFIG, split=SPLIT)
logger.info(f"Loaded dataset with {len(ds)} rows and fields: {ds.features.keys()}")

# ===========================================================
# Step 2: Create GOLDEN DATASET (first 30 examples)
# ===========================================================
gold_n = min(30, len(ds))
logger.info(f"Creating golden dataset using first {gold_n} examples...")

with GOLDEN_PATH.open("w", encoding="utf-8") as f:
    for row in ds.select(range(gold_n)):
        q = row.get("question", "")
        a = row.get("response", "")
        contexts = as_text_list(row.get("documents"), row.get("documents_sentences"))

        # Prepare clean JSON object
        item = {
            "id": row.get("id"),
            "input": q,                       # Model input question
            "reference": a,                   # Ground truth answer
            "contexts": contexts,             # Supporting documents
            "dataset_name": row.get("dataset_name", "hotpotqa"),
            "source": f"{DS_NAME}/{CONFIG}",
        }

        # Write as one JSON line
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

logger.info(f"Golden dataset written to: {GOLDEN_PATH.resolve()}")

# ===========================================================
# Step 3: Create CORPUS DATASET (first 500 examples)
# ===========================================================
# Corpus will overlap with golden set so we can evaluate retrieval on those examples.
corpus_n = min(500, len(ds))
logger.info(f"Building corpus dataset from first {corpus_n} examples (including golden overlap)...")

subset = ds.select(range(corpus_n))

# Collect golden IDs for marking overlap
gold_ids = set(ds.select(range(gold_n))["id"])

with CORPUS_PATH.open("w", encoding="utf-8") as f:
    for row in subset:
        ex_id = row.get("id")
        q = row.get("question", "")
        a = row.get("response", "")
        docs = as_text_list(row.get("documents"), row.get("documents_sentences"))

        for k, doc_text in enumerate(docs):
            rec = {
                "id": f"{ex_id}_d{k}",             # Unique ID for each document
                "text": trunc(doc_text),           # Document text content
                "metadata": {
                    "example_id": ex_id,
                    "question": trunc(q, 2000),
                    "reference_answer": trunc(a, 2000),
                    "dataset": "hotpotqa",
                    "source": f"{DS_NAME}/{CONFIG}",
                    "doc_index": k,
                    "in_golden": ex_id in gold_ids  # Flag for overlap with evaluation set
                }
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

logger.info(f"Corpus dataset written to: {CORPUS_PATH.resolve()}")
logger.info("Script completed successfully!")
logger.info("-----------------------------------------------------------------")
logger.info("Golden dataset  → Used for evaluation (LangSmith, RAGAS, etc.)")
logger.info("Corpus dataset  → Used to populate vector DB (e.g., Pinecone)")
logger.info("Overlap ensured: The 30 golden examples are included in the corpus")
logger.info("-----------------------------------------------------------------")