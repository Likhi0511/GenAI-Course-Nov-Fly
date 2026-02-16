"""
search_pinecone.py
---------------------------------
Interactive semantic search over a Pinecone index, with an OpenAI-powered
summary that synthesises the retrieved chunks into a direct answer.

WHAT THIS SCRIPT DOES
----------------------
1. Connects to your Pinecone index
2. Calls OpenAI text-embedding-3-small to embed the user's query
3. Runs a cosine similarity search via Pinecone's query() API
4. Passes the top-K chunks to OpenAI GPT to generate a consolidated answer
5. Loops interactively until the user types 'quit'

PIPELINE POSITION
-----------------
  [1] Docling extraction
  [2] Meta-enrichment (enrich_pipeline_openai.py)
  [3] Embedding generation (openai_embeddings.py → text-embedding-3-small, 1536 dims)
  [4] Pinecone ingestion (load_embeddings_to_pinecone.py)
  [5] Semantic search + RAG answer  ← you are here

ONE API, TWO MODELS
-------------------
  text-embedding-3-small  (embedding model)
    → Converts the query into a 1536-dim vector
    → MUST match the model used when loading embeddings into Pinecone
    → Different model = vectors in different geometric spaces = wrong results

  gpt-4o-mini  (language model)
    → Reads the retrieved chunk TEXT (not vectors) and writes a synthesised answer
    → Does zero retrieval — Pinecone already found the relevant passages
    → This is the RAG pattern: retrieve → augment prompt → generate answer

HOW PINECONE SEARCH DIFFERS FROM PGVECTOR SEARCH
-------------------------------------------------
  pgvector:  you write raw SQL with the <=> cosine distance operator
  Pinecone:  you call index.query(vector=..., top_k=..., include_metadata=True)
             Pinecone handles ANN index selection, distance computation, and ranking

  Both return results ordered by cosine similarity (highest first).
  Pinecone returns a 'score' field (0→1, higher = more similar).
  pgvector returns '1 - distance' which is the same thing.

METADATA FILTERS (OPTIONAL)
----------------------------
Pinecone supports server-side metadata filtering via the 'filter' parameter.
Filters are applied BEFORE the ANN search, narrowing the candidate set.

  Example:
    search(..., filter={"source": {"$eq": "annual_report_2024.pdf"}})
    search(..., filter={"page": {"$gte": 10, "$lte": 20}})

  Supported operators: $eq, $ne, $gt, $gte, $lt, $lte, $in, $nin

  Use --filter '{"source": "my_doc.pdf"}' on the CLI. The metadata fields
  available for filtering are those stored at ingestion time (source, page,
  breadcrumbs, key_phrases, char_count).

USAGE
-----
  export PINECONE_API_KEY=pc-...
  export OPENAI_API_KEY=sk-...

  python search_pinecone.py --index-name financial-docs
  python search_pinecone.py --index-name financial-docs --namespace q4-reports
  python search_pinecone.py --index-name financial-docs --top-k 8 --chat-model gpt-4o
  python search_pinecone.py --index-name financial-docs --no-summary

DEPENDENCIES
------------
  pip install pinecone-client openai
"""

import os
import sys
import time
import json
import argparse

from pinecone import Pinecone
from openai import OpenAI


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_EMBED_MODEL = 'text-embedding-3-small'   # must match ingestion model
DEFAULT_CHAT_MODEL  = 'gpt-4o-mini'
DEFAULT_TOP_K       = 5


# ===========================================================================
# API Clients
# ===========================================================================

def init_clients(pinecone_key: str = None, openai_key: str = None) -> tuple:
    """
    Initialise both the Pinecone client and the OpenAI client.

    Both are required:
      - Pinecone: to run the vector similarity search
      - OpenAI:   to embed the query AND to generate the summary

    API key resolution for each:
      1. CLI argument (--pinecone-api-key / --openai-api-key)
      2. Environment variable (PINECONE_API_KEY / OPENAI_API_KEY)

    Returns:
        (Pinecone client, OpenAI client) tuple.
        sys.exit(1) if either key is missing.
    """
    pc_key  = pinecone_key or os.getenv('PINECONE_API_KEY')
    oai_key = openai_key   or os.getenv('OPENAI_API_KEY')

    missing = []
    if not pc_key:  missing.append("PINECONE_API_KEY  (get from https://app.pinecone.io/)")
    if not oai_key: missing.append("OPENAI_API_KEY    (get from https://platform.openai.com/)")

    if missing:
        print("ERROR: Missing API keys:")
        for m in missing: print(f"  {m}")
        sys.exit(1)

    pc  = Pinecone(api_key=pc_key)
    oai = OpenAI(api_key=oai_key)
    print("Pinecone and OpenAI clients initialised.")
    return pc, oai


# ===========================================================================
# Index Connection
# ===========================================================================

def connect_index(pc: Pinecone, index_name: str, namespace: str = None):
    """
    Connect to an existing Pinecone index and print its stats.

    NAMESPACE VALIDATION
    --------------------
    If a namespace is specified, we check that it exists in the index stats.
    A missing namespace means either the data was never loaded there, or the
    namespace name has a typo. We warn rather than hard-fail because Pinecone
    returns empty results (not an error) for queries against a non-existent
    namespace — the user can still proceed and see zero results.

    Returns:
        (index, stats) tuple, or sys.exit(1) if index doesn't exist.
    """
    try:
        index = pc.Index(index_name)
        stats = index.describe_index_stats()
    except Exception as e:
        print(f"ERROR: Could not connect to index '{index_name}' — {e}")
        print("Check that the index exists at https://app.pinecone.io/")
        sys.exit(1)

    total = stats['total_vector_count']
    dims  = stats['dimension']
    print(f"Index '{index_name}' | {total} vectors | {dims} dimensions")

    namespaces = stats.get('namespaces', {})
    if namespaces:
        for ns, ns_data in namespaces.items():
            label = ns if ns else '(default)'
            print(f"  namespace {label}: {ns_data.get('vector_count', 0)} vectors")
    else:
        print("  namespace: default only")

    # Namespace existence check (soft warning)
    if namespace and namespace not in namespaces:
        print(f"\nWARNING: Namespace '{namespace}' not found in index.")
        print(f"  Available: {list(namespaces.keys()) or ['(default)']}")
        confirm = input("Continue anyway? (y/N): ").strip().lower()
        if confirm not in ('y', 'yes'):
            sys.exit(1)

    return index, stats


# ===========================================================================
# Embedding  (OpenAI text-embedding-3-small)
# ===========================================================================

def embed_query(oai: OpenAI, text: str, model: str = DEFAULT_EMBED_MODEL) -> list:
    """
    Embed the user's query using OpenAI's embedding API.

    CONSISTENCY RULE
    ----------------
    The vectors stored in Pinecone were created with text-embedding-3-small
    at ingestion time (openai_embeddings.py → load_embeddings_to_pinecone.py).
    The query vector MUST come from the same model — otherwise you're comparing
    vectors from different geometric spaces and cosine scores are meaningless.

    Pinecone stores the index dimension (1536) but NOT which model produced it.
    There is no runtime check — it's your responsibility to keep them aligned.

    MODEL QUICK REFERENCE:
      text-embedding-3-small  1536 dims  ~$0.00002/1K tokens  ← default
      text-embedding-3-large  3072 dims  ~$0.00013/1K tokens
      text-embedding-ada-002  1536 dims  ~$0.00010/1K tokens  (legacy — different space)

    Returns:
        Plain Python list of floats (Pinecone's query() accepts lists directly).
    """
    response = oai.embeddings.create(input=text, model=model)
    return response.data[0].embedding


# ===========================================================================
# Vector Search
# ===========================================================================

def search(index, query_vector: list, top_k: int,
           namespace: str = None, filter_dict: dict = None) -> list:
    """
    Query Pinecone for the top-K most similar vectors.

    HOW PINECONE SEARCH WORKS
    -------------------------
    Pinecone maintains an ANN (Approximate Nearest Neighbour) index — similar
    to pgvector's HNSW, but managed and auto-scaled by Pinecone.

    index.query() parameters:
      vector           : query embedding (list of floats)
      top_k            : how many results to return
      namespace        : partition to search (empty string = default namespace)
      filter           : server-side metadata filter applied BEFORE ANN search
      include_metadata : must be True to get the text and metadata back

    METADATA FILTERS
    ----------------
    Filters narrow the candidate pool before ANN runs. This is useful when
    you know which document, date range, or section to restrict to.

    Filter syntax (Pinecone):
      {"source": {"$eq": "report.pdf"}}         — exact match
      {"page":   {"$gte": 5, "$lte": 20}}       — range
      {"key_phrases": {"$in": ["AI", "LLM"]}}   — list membership

    Available metadata fields (set at ingestion in load_embeddings_to_pinecone.py):
      source, page, breadcrumbs, key_phrases, char_count, pii_redacted

    RETURN FORMAT
    -------------
    Pinecone returns a dict with a 'matches' list. Each match has:
      id        : vector ID
      score     : cosine similarity (0→1, higher = more similar)
      metadata  : dict of stored metadata fields (text, source, page, etc.)

    Args:
        index        : connected Pinecone Index object
        query_vector : list of floats from embed_query()
        top_k        : max results to return
        namespace    : namespace to search (None = default)
        filter_dict  : optional metadata filter (None = no filter)

    Returns:
        List of match dicts, ordered by score descending.
    """
    start = time.time()

    response = index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=namespace or "",
        filter=filter_dict,
        include_metadata=True      # required to get text + metadata back
    )

    matches = response.get('matches', [])
    elapsed = time.time() - start
    print(f"Search: {len(matches)} results in {elapsed:.3f}s")
    return matches


# ===========================================================================
# RAG Summary  (OpenAI gpt-4o-mini)
# ===========================================================================

def summarise(oai: OpenAI, model: str, query: str,
              matches: list, enabled: bool) -> str | None:
    """
    Send retrieved chunks to OpenAI GPT for a synthesised answer.

    RAG PATTERN
    -----------
    Pinecone already retrieved the top-K relevant passages (the R in RAG).
    This function augments the prompt with those passages as context (A),
    then GPT generates a grounded answer (G).

    GPT sees ONLY the text stored in each match's metadata — never the vectors.
    Its job is language generation, not retrieval.

    PROMPT DESIGN
    -------------
    System: financial research assistant persona; strict citation requirement
    User:   query + chunk texts with headers showing score/source/page,
            then asks for three structured outputs:
              1. DIRECT ANSWER   — cited answer synthesised from chunks
              2. KEY INSIGHTS    — 3–5 numbered data-backed takeaways
              3. CHUNK BREAKDOWN — one sentence per chunk

    SETTINGS
    --------
    temperature=0.2  : near-deterministic; factual synthesis, not creativity
    max_tokens=1500  : enough for thorough answers across 5–8 chunks

    Args:
        oai     : OpenAI client
        model   : chat model ID
        query   : user's original search string
        matches : Pinecone match dicts from search()
        enabled : if False, return None immediately (--no-summary flag)

    Returns:
        GPT answer string, or None if disabled or no matches.
    """
    if not enabled or not matches:
        return None

    # Build context block from Pinecone match metadata
    chunks_block = ""
    for i, match in enumerate(matches, 1):
        meta       = match.get('metadata', {})
        score      = match.get('score', 0)
        text       = meta.get('text', '(no text stored)')
        source     = meta.get('source', meta.get('breadcrumbs', 'unknown'))
        page       = meta.get('page', 'N/A')
        phrases    = meta.get('key_phrases', 'N/A')
        chunks_block += (
            f"\n--- CHUNK #{i} | score={score:.1%} | "
            f"source={source} | page={page} | key_phrases={phrases} ---\n"
            f"{text}\n"
        )

    prompt = f"""A user searched a financial research document for: "{query}"

The top {len(matches)} most relevant passages are below:
{chunks_block}

Using ONLY these passages, provide:

1. DIRECT ANSWER — answer "{query}" concisely and specifically. Cite which chunks support each claim (e.g. "According to Chunk #1...").

2. KEY INSIGHTS — 3–5 specific, numbered takeaways from the passages relevant to the query. Include data points and percentages where available.

3. CHUNK BREAKDOWN — one sentence per chunk explaining what it contributes to answering the query.

If the passages lack enough information to answer fully, say so explicitly."""

    print(f"Generating summary with {model}...")
    start = time.time()
    response = oai.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise financial research assistant. "
                    "Synthesise document passages into clear, factual answers. "
                    "Always cite chunk numbers. Never invent information not in the passages."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=1500
    )
    elapsed = time.time() - start
    tokens  = response.usage.total_tokens
    print(f"Summary ready in {elapsed:.1f}s | {tokens} tokens used")
    return response.choices[0].message.content


# ===========================================================================
# Display
# ===========================================================================

def display(query: str, matches: list, summary: str | None):
    """
    Print retrieved chunks followed by the GPT-generated answer.

    Chunks are always shown — the summary is additive on top.
    Text is truncated at 500 chars for terminal readability; full text
    was already passed to GPT for the summary.

    PINECONE SCORE vs PGVECTOR SIMILARITY
    --------------------------------------
    Pinecone's 'score' field and pgvector's '1 - (embedding <=> query)'
    are both cosine similarity values in the range 0→1. They mean the same
    thing: 1.0 = identical, 0.0 = completely unrelated.
    """
    if not matches:
        print("No results found.")
        return

    print(f"\n{'─' * 70}")
    print(f"TOP {len(matches)} RESULTS FOR: \"{query}\"")
    print(f"{'─' * 70}")

    for i, match in enumerate(matches, 1):
        meta  = match.get('metadata', {})
        score = match.get('score', 0)
        vid   = match.get('id', 'unknown')

        print(f"\n[Result #{i}]  score={score:.4f} ({score*100:.1f}%)")
        print(f"  ID:          {vid}")

        if 'source'      in meta: print(f"  Source:      {meta['source']}")
        if 'breadcrumbs' in meta: print(f"  Section:     {meta['breadcrumbs']}")
        if 'page'        in meta: print(f"  Page:        {meta['page']}")
        if 'key_phrases' in meta: print(f"  Key phrases: {meta['key_phrases'][:80]}")
        if 'char_count'  in meta: print(f"  Length:      {meta['char_count']} chars")

        text = meta.get('text', '')
        if text:
            preview = text[:500] + ' [...]' if len(text) > 500 else text
            print(f"\n  {preview}")

    if summary:
        print(f"\n{'=' * 70}")
        print("GPT SUMMARY")
        print(f"{'=' * 70}\n")
        print(summary)

    print()


# ===========================================================================
# Interactive Loop
# ===========================================================================

def interactive_loop(index, oai: OpenAI, embed_model: str, chat_model: str,
                     top_k: int, namespace: str, filter_dict: dict,
                     summary_enabled: bool):
    """
    Run the search-and-summarise loop until the user exits.

    Each iteration:
      query text
        → embed_query()   : text → 1536-dim vector (OpenAI embedding API)
        → search()        : vector → top-K Pinecone matches
        → summarise()     : matches → GPT synthesised answer
        → display()       : print chunks + answer

    Approximate cost per query:
      Embedding:  ~$0.00002  (short query, < 50 tokens)
      Summary:    ~$0.001    (5 chunks + answer, ~2000 tokens)
      Total:      ~$0.001 per search

    Commands:
      'help'  — show sample queries for the Morgan Stanley AI research dataset
      'quit'  — exit cleanly
      Ctrl+C  — exit cleanly
    """
    sample_queries = [
        "What is Agentic AI and why does it matter in 2025?",
        "Which stocks have the highest AI materiality?",
        "How do High Pricing Power Adopters perform vs Low Pricing Power?",
        "What is the difference between Enabler, Adopter, and Disrupted?",
        "How does US AI adoption compare to Europe and APAC?",
        "Which sectors saw the biggest increase in AI materiality?",
        "How did AI-upgraded stocks perform against the MSCI World?",
        "What is the AI conceptual roadmap from GPT-3.5 to GPT-X?",
    ]

    print(f"\n{'─' * 70}")
    print("INTERACTIVE SEARCH  (type 'help' for sample queries, 'quit' to exit)")
    print(f"Embed: {embed_model}  |  Chat: {chat_model}  |  Summary: {'on' if summary_enabled else 'off'}")
    print(f"Top-K: {top_k}"
          + (f"  |  Namespace: {namespace}" if namespace else "")
          + (f"  |  Filter: {filter_dict}" if filter_dict else ""))
    print(f"{'─' * 70}\n")

    while True:
        try:
            query = input("Search: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not query:
            continue

        if query.lower() in ('quit', 'exit', 'q'):
            print("Goodbye.")
            break

        if query.lower() == 'help':
            print("\nSample queries:")
            for i, q in enumerate(sample_queries, 1):
                print(f"  {i}. {q}")
            print()
            continue

        try:
            query_vector = embed_query(oai, query, embed_model)
            matches      = search(index, query_vector, top_k, namespace, filter_dict)
            summary      = summarise(oai, chat_model, query, matches, summary_enabled)
            display(query, matches, summary)
        except Exception as e:
            print(f"ERROR: {e}\n")


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(args):
    """
    Startup sequence: init clients → connect index → verify dims → start loop.

    DIMENSION CONSISTENCY CHECK
    ---------------------------
    text-embedding-3-small always produces 1536-dim vectors.
    If the Pinecone index was built with a different model (e.g. 384-dim
    Sentence Transformers), every query will return wrong results silently
    — Pinecone won't error, it just computes distances in the wrong space.
    We compare model output dims against the index dims and warn loudly.

    FILTER PARSING
    --------------
    --filter accepts a JSON string, e.g.:
      --filter '{"source": "report.pdf"}'
      --filter '{"page": {"$gte": 5}}'
    We parse it here before entering the loop so any syntax error surfaces
    immediately rather than on the first query.
    """
    # 1. Clients
    pc, oai = init_clients(args.pinecone_api_key, args.openai_api_key)

    # 2. Connect to index
    index, stats = connect_index(pc, args.index_name, args.namespace)

    # 3. Dimension check — text-embedding-3-small = 1536 dims
    index_dims  = stats['dimension']
    model_dims  = 1536   # text-embedding-3-small fixed output
    if index_dims != model_dims:
        print(f"\nWARNING: Index has {index_dims}-dim vectors but "
              f"{args.embed_model} produces {model_dims}-dim vectors.")
        print("Results will be semantically meaningless. "
              "Use the embedding model that was used at ingestion time.")
        confirm = input("Continue anyway? (y/N): ").strip().lower()
        if confirm not in ('y', 'yes'):
            sys.exit(1)

    # 4. Parse metadata filter (if provided)
    filter_dict = None
    if args.filter:
        try:
            filter_dict = json.loads(args.filter)
            print(f"Metadata filter active: {filter_dict}")
        except json.JSONDecodeError as e:
            print(f"ERROR: --filter is not valid JSON — {e}")
            print("Example: --filter '{{\"source\": \"report.pdf\"}}'")
            sys.exit(1)

    # 5. Run interactive loop
    interactive_loop(
        index, oai,
        args.embed_model, args.chat_model,
        args.top_k, args.namespace, filter_dict,
        not args.no_summary
    )


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Semantic search over Pinecone with OpenAI embedding + GPT summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EMBEDDING MODEL MUST MATCH INGESTION
  Default is text-embedding-3-small (1536 dims) — matches load_embeddings_to_pinecone.py.

METADATA FILTER EXAMPLES
  --filter '{"source": "annual_report.pdf"}'
  --filter '{"page": {"$gte": 5, "$lte": 20}}'

Examples:
  export PINECONE_API_KEY=pc-...
  export OPENAI_API_KEY=sk-...

  python search_pinecone.py --index-name financial-docs
  python search_pinecone.py --index-name financial-docs --namespace q4-reports
  python search_pinecone.py --index-name financial-docs --top-k 8
  python search_pinecone.py --index-name financial-docs --chat-model gpt-4o
  python search_pinecone.py --index-name financial-docs --no-summary
  python search_pinecone.py --index-name financial-docs --filter '{"source": "report.pdf"}'
        """
    )

    parser.add_argument('--index-name', required=True,  help='Pinecone index name (required)')
    parser.add_argument('--namespace',  default=None,   help='Namespace to search in (optional)')
    parser.add_argument(
        '--embed-model', default=DEFAULT_EMBED_MODEL,
        help=f"OpenAI embedding model — MUST match ingestion (default: {DEFAULT_EMBED_MODEL})"
    )
    parser.add_argument(
        '--chat-model', default=DEFAULT_CHAT_MODEL,
        help=f"OpenAI chat model for summaries (default: {DEFAULT_CHAT_MODEL})"
    )
    parser.add_argument('--top-k',   type=int, default=DEFAULT_TOP_K,
                        help=f"Results per query (default: {DEFAULT_TOP_K})")
    parser.add_argument('--filter',  default=None,
                        help="Metadata filter as JSON string (optional)")
    parser.add_argument('--no-summary', action='store_true',
                        help="Skip GPT summary — show raw chunks only")
    parser.add_argument('--pinecone-api-key', default=None,
                        help="Pinecone API key (default: PINECONE_API_KEY env var)")
    parser.add_argument('--openai-api-key',   default=None,
                        help="OpenAI API key (default: OPENAI_API_KEY env var)")

    run_pipeline(parser.parse_args())