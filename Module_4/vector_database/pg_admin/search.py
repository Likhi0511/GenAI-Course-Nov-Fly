"""
sample_queries_ms_ai_research.py
---------------------------------
Ready-to-run query suite for the Morgan Stanley "Uncovering Alpha in AI's Rate of Change"
research report loaded into pgvector.

WHAT THIS FILE IS
-----------------
A standalone script that runs a curated set of queries against the database
and prints results + GPT summaries. Useful for:
  - Verifying your pipeline end-to-end after loading data
  - Demonstrating the RAG system to students or stakeholders
  - Exploring all the angles of the document systematically

DATASET OVERVIEW (what's in the 20 chunks)
-------------------------------------------
The document covers:
  - AI stock classification framework (Enabler, Adopter, Disrupted, etc.)
  - Materiality scoring (Core to Thesis → Insignificant)
  - Performance data: AI-upgraded stocks vs MSCI World
  - Regional comparison: US vs Europe vs APAC
  - High vs Low Pricing Power Adopter performance
  - AI capability roadmap (GPT-3.5 → GPT-4 → GPT-X)
  - Sector-level materiality changes (Banks, Utilities, Consumer Staples)
  - Agentic AI thesis for 2025
  - Market cap reclassification data ($14tr total)

QUERY CATEGORIES
----------------
Each query is designed to retrieve a different subset of chunks, testing
both semantic recall (does the right chunk come back?) and RAG generation
(does GPT synthesise it correctly?).

USAGE
-----
  export OPENAI_API_KEY=sk-...
  python sample_queries_ms_ai_research.py
  python sample_queries_ms_ai_research.py --password Root@123 --top-k 3
  python sample_queries_ms_ai_research.py --query-category performance
  python sample_queries_ms_ai_research.py --run-all --top-k 5
"""

import os
import sys
import time
import argparse

import psycopg2
from openai import OpenAI


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST        = 'localhost'
DEFAULT_PORT        = 5432
DEFAULT_DB          = 'vector_demo'
DEFAULT_USER        = 'postgres'
DEFAULT_PASS        = 'postgres'
DEFAULT_SCHEMA      = 'public'
DEFAULT_TABLE       = 'document_chunks'
DEFAULT_EMBED_MODEL = 'text-embedding-3-small'
DEFAULT_CHAT_MODEL  = 'gpt-4o-mini'
DEFAULT_TOP_K       = 3     # smaller default for batch runs to save cost


# ---------------------------------------------------------------------------
# Query Bank
# ---------------------------------------------------------------------------
# Each query is a dict with:
#   category   : thematic group (used for --query-category filtering)
#   query      : the natural language search string
#   what_it_tests : what chunk(s) it should retrieve and why
#
# CATEGORIES:
#   framework     — the classification system itself (Enabler/Adopter/Disrupted)
#   performance   — stock returns, outperformance vs MSCI World
#   market_cap    — reclassification by dollar value
#   regional      — US vs Europe vs APAC comparisons
#   sectors       — sector-specific materiality changes
#   agentic       — 2025 Agentic AI thesis
#   capabilities  — AI model roadmap (GPT-3.5 → GPT-X)
#   valuation     — EV/Sales and P/E ratios by AI category
#   pricing_power — High vs Low Pricing Power Adopter split
#   methodology   — how the survey works, analyst questions

QUERY_BANK = [

    # -----------------------------------------------------------------------
    # FRAMEWORK — understanding the classification system
    # -----------------------------------------------------------------------
    {
        "category": "framework",
        "query": "What are the seven AI exposure categories Morgan Stanley uses to classify stocks?",
        "what_it_tests": "Should retrieve Exhibit 2 chunk (Disrupted → Enabler/Adopter spectrum diagram)."
    },
    {
        "category": "framework",
        "query": "How is AI materiality scored for the investment thesis?",
        "what_it_tests": "Should retrieve Exhibit 3 chunk (Insignificant → Core to Thesis, 5 categories)."
    },
    {
        "category": "framework",
        "query": "What three questions do analysts answer in the AI survey?",
        "what_it_tests": "Should retrieve the Executive Summary chunk listing exposure, materiality, pricing power questions."
    },
    {
        "category": "framework",
        "query": "What does it mean for a company to move from Adopter to Enabler/Adopter?",
        "what_it_tests": "Should retrieve the reclassification summary chunk (44 stocks moved, Utilities/Energy driven)."
    },

    # -----------------------------------------------------------------------
    # PERFORMANCE — outperformance vs MSCI World
    # -----------------------------------------------------------------------
    {
        "category": "performance",
        "query": "How much did AI-upgraded stocks outperform the MSCI World in 2024?",
        "what_it_tests": "Should retrieve Rate of Change performance chunk (25% outperformance in 2024, 2H driven)."
    },
    {
        "category": "performance",
        "query": "What is the upside to price targets for overweight stocks with rising AI materiality?",
        "what_it_tests": "Should retrieve the introduction chunk (29% upside to price targets mentioned)."
    },
    {
        "category": "performance",
        "query": "How do Enabler/Adopter stocks compare to pure Adopter or Enabler in market returns?",
        "what_it_tests": "Should retrieve Exhibit 11 chunk (market cap weighted performance by AI exposure)."
    },
    {
        "category": "performance",
        "query": "What happened to Disrupted stocks in 2024 compared to the broader market?",
        "what_it_tests": "Should retrieve Exhibit 10 and Exhibit 11 chunks (Disrupted underperformed, core-to-thesis dropped to ~60)."
    },

    # -----------------------------------------------------------------------
    # MARKET CAP — scale of reclassification
    # -----------------------------------------------------------------------
    {
        "category": "market_cap",
        "query": "How much total market cap was reclassified across AI exposure categories?",
        "what_it_tests": "Should retrieve Executive Summary / What's New chunk ($14tr market cap changed)."
    },
    {
        "category": "market_cap",
        "query": "How many stocks changed both AI exposure and materiality and what is their combined value?",
        "what_it_tests": "Should retrieve What's New chunk (115 stocks, $2.2trn changed both)."
    },
    {
        "category": "market_cap",
        "query": "What is the market cap transition from Adopter to Enabler/Adopter category?",
        "what_it_tests": "Should retrieve the transition matrix chunk (Exhibit 15, $1,475bn moved Adopter → Enabler/Adopter)."
    },

    # -----------------------------------------------------------------------
    # REGIONAL — US vs Europe vs APAC
    # -----------------------------------------------------------------------
    {
        "category": "regional",
        "query": "How does the US compare to Europe in AI materiality as a percentage of market cap?",
        "what_it_tests": "Should retrieve US Leadership chunk (US >70% market cap with moderate+ AI, double Europe's level)."
    },
    {
        "category": "regional",
        "query": "Which region has the highest proportion of Enabler/Adopter stocks by market cap?",
        "what_it_tests": "Should retrieve US Leadership chunk (US has double weighting of Europe in Enabler/Adopters by market cap)."
    },
    {
        "category": "regional",
        "query": "Is there a catch-up argument for Europe and Asia relative to the US in AI adoption?",
        "what_it_tests": "Should retrieve the Rest of World catch-up section (Moderate Adopters comparable, margins upside)."
    },
    {
        "category": "regional",
        "query": "What proportion of Core to Thesis stocks does the US have compared to Europe?",
        "what_it_tests": "Should retrieve US Leadership chunk (US has ~15x higher Core to Thesis weighting than Europe/Japan)."
    },

    # -----------------------------------------------------------------------
    # SECTORS — which industries moved most
    # -----------------------------------------------------------------------
    {
        "category": "sectors",
        "query": "Which sector had the highest net increase in AI materiality?",
        "what_it_tests": "Should retrieve the sector materiality chunk (Financials had highest increase, 17% now more material)."
    },
    {
        "category": "sectors",
        "query": "What happened to Consumer Staples in AI materiality rankings?",
        "what_it_tests": "Should retrieve What's New chunk (Consumer Staples net 3% lower importance — weakest sector)."
    },
    {
        "category": "sectors",
        "query": "Why did Utilities and Energy stocks get reclassified to Enabler/Adopter?",
        "what_it_tests": "Should retrieve the Latest Rate of Change chunk (AI infrastructure buildout, energy demand beneficiaries)."
    },
    {
        "category": "sectors",
        "query": "Which sectors show the most materiality upgrades across Survey 1, 2, and 3?",
        "what_it_tests": "Should retrieve Exhibit 16 chunk (Banks highest in Survey 1→2, then Utilities and Telecoms)."
    },

    # -----------------------------------------------------------------------
    # AGENTIC AI — 2025 thesis
    # -----------------------------------------------------------------------
    {
        "category": "agentic",
        "query": "What is Agentic AI and what shift does it represent from the chatbot phase?",
        "what_it_tests": "Should retrieve the introduction chunk (reactive chatbot → proactive task-fulfillment phase)."
    },
    {
        "category": "agentic",
        "query": "Which specific software stocks are favoured in the Agentic AI theme?",
        "what_it_tests": "Should retrieve Exhibit 6 chunk (CRM, MSFT, NOW, WDAY, SAP etc. listed with prices)."
    },
    {
        "category": "agentic",
        "query": "Why is 2025 expected to be the year of Agentic AI rather than infrastructure?",
        "what_it_tests": "Should retrieve intro chunk (Semiconductor leadership giving way to Software Layer)."
    },

    # -----------------------------------------------------------------------
    # AI CAPABILITIES — model roadmap
    # -----------------------------------------------------------------------
    {
        "category": "capabilities",
        "query": "What is Morgan Stanley's AI capability roadmap from simple tasks to complex tasks?",
        "what_it_tests": "Should retrieve Exhibit 18 chunk (10-second → 5-hour tasks, GPT-3.5 → GPT-4 → GPT-X)."
    },
    {
        "category": "capabilities",
        "query": "What does inference-time reasoning mean and how does it differ from memory regurgitation?",
        "what_it_tests": "Should retrieve Why AI Rate of Change Will Continue chunk (o3 series, compute-intensive reasoning)."
    },
    {
        "category": "capabilities",
        "query": "What was OpenAI's major breakthrough announced in December?",
        "what_it_tests": "Should retrieve the final small chunk (o3 Series supersedes o1 models)."
    },

    # -----------------------------------------------------------------------
    # VALUATION — EV/Sales and P/E
    # -----------------------------------------------------------------------
    {
        "category": "valuation",
        "query": "Which AI exposure category has the highest EV/Sales ratio?",
        "what_it_tests": "Should retrieve Exhibit 10 bar chart chunk (Adopter category highest at >3.0x EV/Sales)."
    },
    {
        "category": "valuation",
        "query": "How do P/E ratios compare across Enabler, Adopter, and Disrupted categories?",
        "what_it_tests": "Should retrieve the EV/Sales and P/E chart chunk (P/E similar across categories 14x–17x)."
    },

    # -----------------------------------------------------------------------
    # PRICING POWER — the high vs low split
    # -----------------------------------------------------------------------
    {
        "category": "pricing_power",
        "query": "How much have High Pricing Power Adopters outperformed Low Pricing Power Adopters since ChatGPT?",
        "what_it_tests": "Should retrieve What's New chunk (30% outperformance since ChatGPT release, 139 stocks)."
    },
    {
        "category": "pricing_power",
        "query": "How is pricing power defined in the context of AI adoption for companies?",
        "what_it_tests": "Should retrieve the Executive Summary survey questions chunk (ability to retain cost savings vs passing to customers)."
    },
    {
        "category": "pricing_power",
        "query": "How many stocks were recently added to the high pricing power and high AI materiality category?",
        "what_it_tests": "Should retrieve What's New chunk (8 companies added in latest survey)."
    },

    # -----------------------------------------------------------------------
    # METHODOLOGY — meta questions about the survey itself
    # -----------------------------------------------------------------------
    {
        "category": "methodology",
        "query": "How many global stocks does Morgan Stanley cover in this AI mapping exercise?",
        "what_it_tests": "Should retrieve intro chunk (>3,700 global stocks, 585 changed this round)."
    },
    {
        "category": "methodology",
        "query": "What is the ratio of upward to downward materiality changes in this survey?",
        "what_it_tests": "Should retrieve Rate of Change chunk (3:1 ratio upward vs downward; previously was 1.1:1)."
    },
    {
        "category": "methodology",
        "query": "How many surveys have been published and what changed between each one?",
        "what_it_tests": "Should retrieve intro and Executive Summary chunks (Survey 1 Jan 2024, Survey 2 Jun 2024, Survey 3 current)."
    },
]


# ===========================================================================
# Helpers (identical to search_pgvector_with_summary.py — kept local to keep
# this file self-contained so it can run standalone)
# ===========================================================================

def init_client(api_key):
    key = api_key or os.getenv('OPENAI_API_KEY')
    if not key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)
    return OpenAI(api_key=key)


def connect(host, port, database, user, password):
    conn = psycopg2.connect(
        host=host, port=port, database=database, user=user, password=password
    )
    conn.autocommit = True
    return conn, conn.cursor()


def embed(client, text, model):
    return client.embeddings.create(input=text, model=model).data[0].embedding


def search(cursor, vec, schema, table, top_k):
    vec_str = '[' + ','.join(map(str, vec)) + ']'
    cursor.execute(f"""
        SELECT id, content, metadata,
               1 - (embedding <=> %s::vector) AS similarity
        FROM {schema}.{table}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (vec_str, vec_str, top_k))
    return cursor.fetchall()


def summarise(client, model, query, results):
    if not results:
        return "No results found."
    chunks = ""
    for i, (_, content, meta, sim) in enumerate(results, 1):
        section = (meta or {}).get('breadcrumbs', 'unknown')
        chunks += f"\n--- CHUNK #{i} | similarity={sim:.1%} | section={section} ---\n{content}\n"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content":
                "You are a precise financial research assistant. "
                "Synthesise passages into factual answers. Cite chunk numbers."},
            {"role": "user", "content":
                f'Query: "{query}"\n\nPassages:{chunks}\n\n'
                f'Provide: (1) Direct answer with chunk citations, '
                f'(2) 3-5 key data insights, (3) one line per chunk on its contribution.'}
        ],
        temperature=0.2,
        max_tokens=1000
    )
    return response.choices[0].message.content


def run_query(cursor, client, embed_model, chat_model, schema, table,
              top_k, query_dict, index, total):
    """Run a single query from the bank and print results."""
    q       = query_dict['query']
    cat     = query_dict['category']
    expects = query_dict['what_it_tests']

    print(f"\n{'=' * 70}")
    print(f"Query {index}/{total}  [{cat.upper()}]")
    print(f"{'=' * 70}")
    print(f"Q: {q}")
    print(f"   Expected: {expects}")
    print()

    start = time.time()
    vec     = embed(client, q, embed_model)
    results = search(cursor, vec, schema, table, top_k)
    summary = summarise(client, chat_model, q, results)
    elapsed = time.time() - start

    # Show top result snippet only (keep output scannable in batch mode)
    if results:
        best = results[0]
        meta = best[2] or {}
        print(f"Top result: similarity={best[3]:.3f} | "
              f"section={meta.get('breadcrumbs', 'N/A')}")
        preview = best[1][:200] + '...' if len(best[1]) > 200 else best[1]
        print(f"  {preview}\n")

    print(f"GPT ANSWER:")
    print(summary)
    print(f"\n[{elapsed:.1f}s total]")


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run sample queries against the Morgan Stanley AI research database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Categories:
  framework, performance, market_cap, regional, sectors,
  agentic, capabilities, valuation, pricing_power, methodology

Examples:
  # Run all queries
  python sample_queries_ms_ai_research.py --run-all

  # Run only Agentic AI queries
  python sample_queries_ms_ai_research.py --query-category agentic

  # Run performance queries with more chunks and better model
  python sample_queries_ms_ai_research.py --query-category performance --top-k 5 --chat-model gpt-4o

  # List all queries without running them
  python sample_queries_ms_ai_research.py --list-only
        """
    )

    parser.add_argument('--host',     default=DEFAULT_HOST)
    parser.add_argument('--port',     default=DEFAULT_PORT, type=int)
    parser.add_argument('--database', default=DEFAULT_DB)
    parser.add_argument('--user',     default=DEFAULT_USER)
    parser.add_argument('--password', default=DEFAULT_PASS)
    parser.add_argument('--schema',   default=DEFAULT_SCHEMA)
    parser.add_argument('--table',    default=DEFAULT_TABLE)
    parser.add_argument('--embed-model',    default=DEFAULT_EMBED_MODEL)
    parser.add_argument('--chat-model',     default=DEFAULT_CHAT_MODEL)
    parser.add_argument('--openai-api-key', default=None)
    parser.add_argument('--top-k',    type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        '--query-category', default=None,
        help="Run only queries of this category (see list above)"
    )
    parser.add_argument(
        '--run-all', action='store_true',
        help="Run every query in the bank (costs ~$0.05 total)"
    )
    parser.add_argument(
        '--list-only', action='store_true',
        help="Print all queries without running them"
    )
    parser.add_argument(
        '--query-index', type=int, default=None,
        help="Run a single query by its 1-based index in the bank"
    )

    args = parser.parse_args()

    # --- List mode ---
    if args.list_only:
        print(f"\n{len(QUERY_BANK)} queries in the bank:\n")
        current_cat = None
        for i, q in enumerate(QUERY_BANK, 1):
            if q['category'] != current_cat:
                current_cat = q['category']
                print(f"\n  [{current_cat.upper()}]")
            print(f"  {i:2}. {q['query']}")
            print(f"      → {q['what_it_tests']}")
        print()
        return

    # --- Determine which queries to run ---
    if args.query_index:
        queries_to_run = [QUERY_BANK[args.query_index - 1]]
    elif args.query_category:
        queries_to_run = [q for q in QUERY_BANK if q['category'] == args.query_category]
        if not queries_to_run:
            print(f"No queries found for category '{args.query_category}'")
            print(f"Available: {sorted(set(q['category'] for q in QUERY_BANK))}")
            sys.exit(1)
    elif args.run_all:
        queries_to_run = QUERY_BANK
    else:
        # Default: show the query bank and ask
        print(f"\n{len(QUERY_BANK)} queries available. Use one of:")
        print("  --run-all                        run everything")
        print("  --query-category <name>          run a category")
        print("  --query-index <n>                run one query")
        print("  --list-only                      list without running")
        print("\nCategories:")
        for cat in sorted(set(q['category'] for q in QUERY_BANK)):
            count = sum(1 for q in QUERY_BANK if q['category'] == cat)
            print(f"  {cat:<18} {count} queries")
        return

    # --- Run queries ---
    client = init_client(args.openai_api_key)
    conn, cursor = connect(args.host, args.port, args.database, args.user, args.password)

    print(f"\nRunning {len(queries_to_run)} queries | top-K={args.top_k} | "
          f"embed={args.embed_model} | chat={args.chat_model}")

    try:
        for i, q in enumerate(queries_to_run, 1):
            run_query(
                cursor, client,
                args.embed_model, args.chat_model,
                args.schema, args.table,
                args.top_k, q, i, len(queries_to_run)
            )
            if i < len(queries_to_run):
                time.sleep(0.5)   # small pause to respect OpenAI rate limits

        print(f"\n{'=' * 70}")
        print(f"All {len(queries_to_run)} queries complete.")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()