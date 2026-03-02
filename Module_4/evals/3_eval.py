#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG Triad Evaluation Script using LangSmith, Pinecone, and OpenAI.

This script evaluates a Retrieval-Augmented Generation (RAG) system along three axes:
1. Retrieval relevance — how well the retrieved contexts relate to the question
2. Answer quality — how correct, complete, and fluent the model’s answer is
3. Groundedness / faithfulness — how well the answer is supported by retrieved evidence

It uses:
- Pinecone for vector-based retrieval,
- OpenAI LLM for answer generation and for evaluation,
- LangSmith for tracking datasets, runs, and evaluation results.
"""

import os
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from langsmith import Client
from langchain.smith import RunEvalConfig
from langchain.smith.evaluation.runner_utils import run_on_dataset
from langsmith.schemas import Run, Example, DataType
from langchain.evaluation import load_evaluator, EvaluatorType
from langchain.smith.evaluation.string_run_evaluator import StringRunEvaluatorChain

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.schema import Document
from langchain_core.prompts import ChatPromptTemplate
from pinecone import Pinecone

# ================================================================
# CONFIGURATION & SETUP
# ================================================================

REQUIRED_ENVS = ["OPENAI_API_KEY", "PINECONE_API_KEY"]
missing = [k for k in REQUIRED_ENVS if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing required environment variables: {missing}")

PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX", "hotpotqa-ragbench-mini")
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "hotpotqa")
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o")
RETRIEVER_K = int(os.getenv("RETRIEVER_K", "4"))

print("[INFO] Index:", PINECONE_INDEX_NAME,
      "Namespace:", NAMESPACE,
      "LLM:", OPENAI_LLM_MODEL,
      "K:", RETRIEVER_K)

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
idx = pc.Index(PINECONE_INDEX_NAME)
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

# ================================================================
# RETRIEVAL & ANSWER GENERATION
# ================================================================

def pinecone_search(query: str, top_k: int = RETRIEVER_K) -> List[Document]:
    """
    Retrieve up to top_k documents from Pinecone by embedding similarity.

    Args:
        query: the input query or question string.
        top_k: how many top documents to retrieve.

    Returns:
        A list of Document objects (with page_content and metadata) for the top matches.
    """
    vec = embeddings.embed_query(query)
    res = idx.query(vector=vec, top_k=top_k, include_metadata=True, namespace=NAMESPACE)
    docs: List[Document] = []
    for m in (res.matches or []):
        md = m.metadata or {}
        txt = md.get("text", "")
        if isinstance(txt, str) and txt.strip():
            md_out = dict(md)
            md_out["id"] = m.id
            md_out["score"] = m.score
            docs.append(Document(page_content=txt, metadata=md_out))
    return docs

answer_llm = ChatOpenAI(model=OPENAI_LLM_MODEL, temperature=0)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant. Use the provided context to answer accurately. "
               "If the context is insufficient, say you don't know."),
    ("human", "Question: {q}\n\nContext:\n{ctx}\n\nAnswer:")
])

def rag_query(user_question: str) -> Dict[str, Any]:
    """
    Perform a RAG (Retrieval + Generation) query:
    1. Retrieve relevant contexts from Pinecone,
    2. Use the LLM to generate an answer given those contexts.

    Args:
        user_question: the question string.

    Returns:
        A dict containing:
            "answer": the model’s answer (string),
            "retrieved_contexts": list of context strings retrieved,
            "retrieved_chunk_ids": IDs of the retrieved context chunks.
    """
    docs = pinecone_search(user_question, top_k=RETRIEVER_K)
    ctxs = [d.page_content for d in docs]
    joined = "\n\n---\n\n".join(ctxs)
    ans = (prompt | answer_llm).invoke({"q": user_question, "ctx": joined}).content
    return {
        "answer": ans,
        "retrieved_contexts": ctxs,
        "retrieved_chunk_ids": [d.metadata.get("id") for d in docs],
    }

def predict(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapter for the LangSmith evaluation runner: maps input to rag_query and formats output.

    Args:
        inputs: dict expected to have key "input" for the question.

    Returns:
        dict with:
            "output": answer string,
            "retrieved_contexts": list of strings,
            "retrieved_chunk_ids": list of IDs.
    """
    out = rag_query(inputs["input"])
    return {
        "output": out["answer"],
        "retrieved_contexts": out["retrieved_contexts"],
        "retrieved_chunk_ids": out["retrieved_chunk_ids"],
    }

# ================================================================
# CUSTOM RETRIEVAL-RELEVANCE EVALUATOR
# ================================================================

def retrieval_relevance_eval(
    run: Run,
    example: Example,
    inputs: Optional[dict] = None,
    outputs: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Evaluate how relevant the retrieved contexts are for the given question.

    Uses the LLM to assign a relevance score between 0 and 1, and returns a comment.

    Args:
        run: the Run object produced by a run_on_dataset invocation (contains outputs).
        example: the Example object (contains inputs, references, etc.).
        inputs: optional mapping for inputs in this evaluation context.
        outputs: optional mapping of outputs to use.
        reference_outputs: optional reference outputs mapping.

    Returns:
        dict with:
            "score": float between 0.0 and 1.0,
            "key": "retrieval_relevance",
            "comment": explanatory string from the LLM judgment.
    """
    print("###########################################")
    print("----------------------------------")
    print("run", run)
    print("----------------------------------")
    print("example", example)
    print("----------------------------------")
    print("inputs", inputs)
    print("----------------------------------")
    print("outputs", outputs)
    print("###########################################")

    q = inputs["input"] if inputs else example.inputs.get("input")
    out = outputs or run.outputs
    ctxs = out.get("retrieved_contexts", [])
    gold_relevant_docs = inputs.get("gold_relevant_docs", [])

    if not ctxs:
        return {"score": 0.0,
                "key": "retrieval_relevance",
                "comment": "No retrieved contexts"}

    judge_prompt = (
        f"Question: {q}\n\n"
        f"Retrieved contexts (first up to 5):\n"
        + "\n\n===\n\n".join(ctxs[:5])
        + "\n\nRate from 0 to 1 how relevant these contexts are for answering the question. Explain briefly."
    )
    resp = (ChatPromptTemplate.from_messages([
        ("human", judge_prompt)
    ]) | answer_llm).invoke({}).content

    score = 0.0
    first_token = resp.strip().split()[0] if resp.strip() else ""
    try:
        f = float(first_token)
        score = max(0.0, min(1.0, f))
    except ValueError:
        if "very" in resp.lower() or "relevant" in resp.lower():
            score = 0.8
        else:
            score = 0.5

    return {"score": score,
            "key": "retrieval_relevance",
            "comment": resp}



# ================================================================
# DATA LOADING & DATASET REGISTRATION
# ================================================================

def load_jsonl(path: Path) -> List[dict]:
    """
    Load a JSONL (JSON lines) file where each line is a JSON object.

    Args:
        path: Path to the file.

    Returns:
        List of dicts parsed from each non-empty line.
    """
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line.strip()) for line in f if line.strip()]





DATASET_NAME = "learn-eval"
GOLD_JSONL = Path("./ragbench_hotpotqa_exports/golden_hotpotqa_30.jsonl")

eval_data = load_jsonl(GOLD_JSONL)

client = Client()

# create_dataset & read_dataset:
# - `create_dataset` makes a new dataset in LangSmith (registering name, description).
# - `read_dataset` tries to fetch an existing dataset by name; if it doesn’t exist, we catch and then create it.
# These methods let you store and organize your examples in LangSmith.
try:
    dataset = client.read_dataset(dataset_name=DATASET_NAME)
except Exception:
    dataset = client.create_dataset(dataset_name=DATASET_NAME,
                                    description="RAG evaluation dataset")

# Clean out old examples (if any) to start fresh
old = list(client.list_examples(dataset_id=dataset.id))
if old:
    client.delete_examples([ex.id for ex in old])

for ex in eval_data:
    client.create_example(
        inputs={"input": ex["input"], "gold_relevant_docs": ex.get("contexts", [])},
        outputs={"output": ex.get("reference", "") or ""},
        dataset_id=dataset.id,
    )

# ================================================================
# QA EVALUATION & EVALUATOR SETUP
# ================================================================

eval_llm = ChatOpenAI(model=OPENAI_LLM_MODEL, temperature=0)

# load_evaluator: loads a built-in evaluator (or evaluation chain) for a given EvaluatorType,
# here we select QA-style evaluation (comparing answer vs reference).
qa_chain = load_evaluator(EvaluatorType.QA, llm=eval_llm)

# Wrap the QA evaluator into a Run-level evaluator so it can be used with run_on_dataset.
qa_eval = StringRunEvaluatorChain.from_run_and_data_type(
    evaluator=qa_chain,
    run_type="chain",
    data_type=DataType.kv,
    input_key="input",
    prediction_key="output",
    reference_key="output",
)
# Explanations:
# - StringRunEvaluatorChain is a wrapper that allows a “string-level” evaluator (qa_chain)
#   to be applied at the granularity of Runs & Examples in LangSmith.
# - `from_run_and_data_type` configures how to map the run / example structure into evaluator inputs:
#     * `run_type="chain"` means these runs are chain-type runs,
#     * `data_type=DataType.kv` indicates the dataset is key-value style (input/output),
#     * `input_key="input"` means the question argument is stored under "input",
#     * `prediction_key="output"` is where the model’s generated answer is,
#     * `reference_key="output"` means reference answers in the example are also in "output".

criteria ={
    "faithfulness": """
                       Meaning:
                       Judge whether the answer is grounded in the provided references/context (or data) and avoids unsupported claims.

                       Use when:
                       - RAG systems must cite or stay within retrieved evidence.
                       - Hallucinations must be minimized (medical/legal/financial/analytics).

                       What “good” looks like:
                       - Claims are traceable to the given context or clearly marked as assumptions.
                       - No invented facts, numbers, or names.

                       What “poor” looks like:
                       - States facts not supported by sources.
                       - Misquotes or misinterprets evidence; fabricates citations.

                       Examples:
                       - With meeting notes stating “renewal risk due to SLA breaches”:
                         Good: “Renewal is at risk due to repeated SLA breaches noted in the 2025-09-18 meeting.”
                         Poor: “Renewal closed lost last week due to pricing” (not in context).

                       Scoring guidance (1–5):
                       1 = hallucinated/unsupported; 3 = mostly grounded with minor leaps; 5 = fully supported by context.
                   """,
}

criteria_evaluators = []
for criterion, description in criteria.items():
    crit_eval_chain = load_evaluator(
        EvaluatorType.CRITERIA,
        llm=eval_llm,
        criteria={criterion: description},
    )
    crit_evaluator = StringRunEvaluatorChain.from_run_and_data_type(
        evaluator=crit_eval_chain,
        run_type="chain",
        data_type=DataType.kv,
        input_key="input",
        prediction_key="output",
        reference_key="output",
    )
    criteria_evaluators.append(crit_evaluator)



evaluation_config = RunEvalConfig(
    evaluators=[qa_eval,retrieval_relevance_eval] + criteria_evaluators
)

# ================================================================
# RUNNING THE EVALUATION
# ================================================================

unique_project = f"rag_triads__{datetime.now().strftime('%Y%m%d__%H%M%S')}"
results = run_on_dataset(
    client=client,
    dataset_name=DATASET_NAME,
    llm_or_chain_factory=predict,
    evaluation=evaluation_config,
    concurrency_level=5,
    project_name=unique_project,
    input_mapper=lambda ex: {"input": ex["input"]},
)
# Explanation:
# - `run_on_dataset` is a LangSmith utility that iterates through all examples in the dataset,
#   invokes your `predict()` (via the llm_or_chain_factory) on each, and logs the runs.
# - It also applies your evaluation_config (qa_eval, retrieval_relevance_eval) to score each run.
# - `input_mapper` maps each LangSmith Example’s inputs into the arg structure for predict().
# See LangChain docs for run_on_dataset.  [oai_citation:0‡LangChain Python API](https://api.python.langchain.com/en/latest/smith/langchain.smith.evaluation.runner_utils.run_on_dataset.html?utm_source=chatgpt.com)

# ================================================================
# PRECISION@K / RECALL@K CALCULATION
# ================================================================

def normalize_text(s: str) -> str:
    """
    Normalize text by lowercasing, trimming, and collapsing whitespace.
    """
    return " ".join((s or "").strip().lower().split())

def match_score(g: str, p: str) -> bool:
    """
    Decide whether predicted retrieved string p matches a gold string g
    by normalized equality or substring checks.
    """
    g2, p2 = normalize_text(g), normalize_text(p)
    return bool(g2 and p2 and (g2 == p2 or g2 in p2 or p2 in g2))

def precision_recall_at_k(gold: List[str], preds: List[str], k: int):
    """
    Compute precision@k and recall@k among retrieved contexts.

    Args:
        gold: list of gold (relevant) context strings or identifiers.
        preds: list of retrieved context strings (ordered).
        k: consider only the first k predictions.

    Returns:
        (precision, recall, matches) tuple:
           precision = matches / number_of_preds_considered
           recall = matches / number_of_gold
    """
    # ================================================================
    # PRECISION AND RECALL EXPLANATION (in RAG Context)
    # ================================================================
    # Precision and Recall are fundamental metrics for evaluating retrieval quality
    # in a Retrieval-Augmented Generation (RAG) system.
    #
    # In RAG:
    #   - "gold" refers to the truly relevant context passages for a given query.
    #   - "preds" are the top-k passages actually retrieved by your retriever.
    #
    #   Precision@k → Out of the top-k retrieved passages, how many were truly relevant?
    #   Recall@k    → Out of all truly relevant passages, how many did we retrieve within top-k?
    #
    #   Mathematically:
    #       Precision@k = (# of relevant docs among top-k retrieved) / (# of retrieved docs up to k)
    #       Recall@k    = (# of relevant docs among top-k retrieved) / (# of all truly relevant docs)
    #
    #   In short:
    #     • Precision measures "quality" (how clean are your retrieved contexts)
    #     • Recall measures "coverage" (did you find everything you should have)
    #
    # ----------------------------------------------------------------
    # EXAMPLES:
    #
    # Example 1: Balanced case
    #   gold = ["docA", "docB", "docC"]       # 3 truly relevant docs
    #   preds = ["docX", "docB", "docC", "docY"]
    #   k = 3  → we only consider top 3: ["docX", "docB", "docC"]
    #
    #   Relevant retrieved = {"docB", "docC"} → 2 matches
    #   Precision@3 = 2 / 3 = 0.6667   (2 correct out of 3 retrieved)
    #   Recall@3    = 2 / 3 = 0.6667   (found 2 of 3 total relevant docs)
    #
    # Example 2: High precision but lower recall
    #   gold = ["doc1", "doc2", "doc3", "doc4"]  # 4 relevant docs
    #   preds = ["doc2", "docA", "doc4"]          # retrieved 3 docs
    #   k = 3 → ["doc2", "docA", "doc4"]
    #
    #   Relevant retrieved = {"doc2", "doc4"} → 2 matches
    #   Precision@3 = 2 / 3 = 0.6667   (accurate among what we retrieved)
    #   Recall@3    = 2 / 4 = 0.5      (missed half of the truly relevant docs)
    #
    # Example 3: Retrieved nothing
    #   gold = ["g1", "g2"]
    #   preds = []
    #   → Precision@3 = 0.0 (nothing retrieved)
    #     Recall@3    = 0.0 (no relevant docs retrieved)
    #
    # Example 4: No gold (edge case)
    #   gold = []
    #   preds = ["x", "y"]
    #   → Precision@3 = 0.0 (none can be relevant)
    #     Recall@3    = 1.0 (trivial: nothing to recall)
    #
    # Example 5: Perfect retrieval
    #   gold = ["d1", "d2", "d3"]
    #   preds = ["d1", "d2", "d3"]
    #   → Precision@3 = 3 / 3 = 1.0
    #     Recall@3    = 3 / 3 = 1.0
    #
    # ----------------------------------------------------------------
    # WHY THEY MATTER IN RAG:
    #
    # 1. Precision@k tells you whether your retriever is feeding the LLM with clean,
    #    relevant context. Low precision → more irrelevant noise → higher chance of
    #    hallucinations or wrong answers.
    #
    # 2. Recall@k tells you whether your retriever found *all* the key evidence.
    #    Low recall → missing crucial facts → LLM may answer “I don’t know” or give partial info.
    #
    # 3. The tradeoff:
    #    - Increasing the number of retrieved docs (higher k) often improves recall
    #      but can decrease precision.
    #    - Decreasing k often improves precision but risks missing relevant info.
    #
    # 4. In practical RAG evaluation:
    #    - Choose k = number of documents actually fed into your LLM.
    #    - Compute Precision@k and Recall@k over your validation set.
    #    - Optionally compute F1@k = 2 * (P * R) / (P + R) to summarize both.
    #
    # Example tradeoff summary table:
    #   | Precision@3 | Recall@3 | F1@3 |
    #   |--------------|-----------|------|
    #   | 1.0          | 0.4       | 0.57 |
    #   | 0.67         | 0.67      | 0.67 |
    #   | 0.5          | 1.0       | 0.67 |
    #
    # 5. Interpretation in RAG terms:
    #    - High Precision, Low Recall → Your retriever finds only the “obvious” relevant chunks.
    #    - Low Precision, High Recall → It finds everything but also brings irrelevant chunks.
    #    - Balanced → Ideal; gives LLM enough evidence without polluting context.
    #
    # These metrics help tune retriever settings (like embedding model, similarity metric, or top_k)
    # and validate that your RAG pipeline is retrieving *useful* context for the LLM.
    # ================================================================

    gold = gold or []
    preds = (preds or [])[:k]

    # If there are no gold and no predictions, treat as perfect
    if not gold and not preds:
        return 1.0, 1.0, 0
    if not preds:
        return 0.0, 0.0, 0

    matched = set()
    matches = 0
    for p in preds:
        for gi, g in enumerate(gold):
            if gi in matched:
                continue
            if match_score(g, p):
                matched.add(gi)
                matches += 1
                break

    precision = matches / max(1, len(preds))
    recall = matches / max(1, len(gold))
    F1 =  2 * (precision * recall)/(precision + recall)
    return precision, recall, F1,matches

if isinstance(results, dict) and "results" in results and isinstance(results["results"], dict):
    per_example = results["results"]
else:
    raise RuntimeError("Unexpected results structure. Expected dict with 'results' key.")

example_by_id = {ex.id: ex for ex in client.list_examples(dataset_id=dataset.id)}
K = RETRIEVER_K
rows: List[Dict[str, Any]] = []

total_matches = total_preds = total_gold = 0

for ex_id, entry in per_example.items():
    inp = entry.get("input", {}) or {}
    out = entry.get("output", {}) or {}

    gold = inp.get("gold_relevant_docs", []) or []
    retrieved = out.get("retrieved_contexts", []) or []

    p, r, f1,matches = precision_recall_at_k(gold, retrieved, K)
    total_matches += matches
    total_preds += max(1, min(K, len(retrieved)))
    total_gold += len(gold)

    question = inp.get("input") or example_by_id.get(ex_id, {}).inputs.get("input", "")
    rows.append({
        "example_id": ex_id,
        "question": question,
        f"precision@{K}": round(p, 3),
        f"recall@{K}": round(r, 3),
        f"f1@{K}": round(f1, 3),
        "gold_count": len(gold),
        "retrieved_count": len(retrieved),
    })

micro_p = (total_matches / total_preds) if total_preds else 0.0
micro_r = (total_matches / total_gold) if total_gold else 0.0

#F1@k = 2 * (P * R) / (P + R)
micro_F1 = 2 * (micro_p * micro_r)/(micro_p + micro_r)

print("\n=== Retrieval Metrics (micro-averaged) ===")
print(f"Precision@{K}: {micro_p:.3f}")
print(f"Recall@{K}:    {micro_r:.3f}")
print(f"F1Score@{K}:    {micro_F1:.3f}")

if rows:
    out_csv = f"retrieval_eval_{results.get('project_name','project')}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[INFO] Saved metrics to {out_csv}")