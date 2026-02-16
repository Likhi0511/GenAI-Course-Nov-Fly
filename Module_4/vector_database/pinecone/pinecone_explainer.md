# Pinecone: Architecture and How It Works

## What Is Pinecone?

Pinecone is a **managed vector database** — a database purpose-built for storing
and searching high-dimensional vectors (embeddings) by semantic similarity.

A traditional database answers questions like *"find all rows where price > 100"*.  
Pinecone answers questions like *"find the 5 vectors most similar in meaning to this query"*.

You never write SQL. You call `index.upsert()` to store vectors and `index.query()`
to search them. Pinecone handles all infrastructure, indexing, scaling, and replication.

---

## Where Pinecone Sits in the RAG Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RAG PIPELINE                                │
│                                                                     │
│  PDF / Document                                                     │
│       │                                                             │
│       ▼  [1] Docling PDF Extractor                                  │
│  Text Chunks                                                        │
│       │                                                             │
│       ▼  [2] Enrichment Pipeline (OpenAI)                           │
│  Chunks + Metadata                                                  │
│  (key_phrases, entities, PII-redacted)                              │
│       │                                                             │
│       ▼  [3] OpenAI text-embedding-3-small                          │
│  Chunks + 1536-dim Vectors                                          │
│       │                                                             │
│       ▼  [4] load_embeddings_to_pinecone.py                         │
│  ┌────────────────────────────────┐                                 │
│  │        PINECONE INDEX          │  ← stored on Pinecone cloud     │
│  │  id + values[1536] + metadata  │                                 │
│  └────────────────────────────────┘                                 │
│       │                                                             │
│       ▼  [5] search_pinecone.py                                     │
│  User Query                                                         │
│       │  embed (text-embedding-3-small)                             │
│       │  query() → top-K matches                                    │
│       │  GPT summarise                                              │
│       ▼                                                             │
│  Answer grounded in document chunks                                 │
└─────────────────────────────────────────────────────────────────────┘
```

The embedding model is the **thread connecting every step**. The model used at load
time (`openai_embeddings.py`) must be identical to the model used at search time
(`search_pinecone.py`). Both must produce vectors in the same geometric space for
cosine distance to mean anything.

---

## How a Vector Represents Meaning

Before explaining Pinecone's internals, it is worth understanding what it stores.

An embedding model (like `text-embedding-3-small`) converts any text into a list of
1536 floating point numbers. This list is a **coordinate in a 1536-dimensional space**.

The key property: **semantically similar text lands close together**.

```
"Agentic AI in 2025"          →  [0.12, -0.34, 0.87, ...]
"Autonomous software agents"  →  [0.13, -0.31, 0.85, ...]  ← nearby
"Stock price of Apple"        →  [-0.45, 0.22, -0.10, ...] ← far away
```

No exact word overlap is needed. The model has learned that "Agentic" and "autonomous
agents" share the same semantic neighbourhood. This is what makes semantic search
fundamentally different from keyword search.

---

## Pinecone Architecture

### 1. Indexes

An **index** is the top-level container. It has a fixed:
- **Dimension** — length of vectors it accepts (e.g. 1536 for `text-embedding-3-small`)
- **Metric** — how similarity is measured (`cosine`, `euclidean`, or `dotproduct`)

```python
pc.create_index(
    name="financial-docs",
    dimension=1536,
    metric="cosine",
    spec=ServerlessSpec(cloud="aws", region="us-east-1")
)
```

Once created, the dimension and metric are **fixed**. You cannot change them without
deleting and recreating the index.

---

### 2. Vector Records

Each record stored in Pinecone has exactly three fields:

```
┌──────────────────────────────────────────────────────────┐
│                    VECTOR RECORD                         │
│                                                          │
│  id:       "chunk_abc123"          ← unique string key   │
│                                                          │
│  values:   [0.12, -0.34, 0.87,     ← the embedding      │
│             ..., 0.61]               (1536 floats)       │
│                                                          │
│  metadata: {                       ← flat key-value      │
│    "text":        "Agentic AI...", │  pairs only         │
│    "source":      "report.pdf",    │  (no nested dicts)  │
│    "page":        3,               │                     │
│    "breadcrumbs": "Intro > 2025",  │                     │
│    "key_phrases": "Agentic, LLM"   │                     │
│  }                                                       │
└──────────────────────────────────────────────────────────┘
```

**Important metadata constraints:**
- Values must be flat scalars: strings, integers, booleans, or lists of scalars
- No nested dictionaries
- 40KB limit per vector's total metadata
- Lists of strings are supported for `$in` filtering

This is why `key_phrases` is stored as a comma-joined string rather than a Python list
in `load_embeddings_to_pinecone.py` — to stay safe across all filter operations.

---

### 3. Namespaces

A namespace is a **logical partition** inside one index. Vectors in different namespaces
are completely isolated — a query in `"q4-reports"` never touches `"q1-reports"`.

```
index: financial-docs
  ├── namespace: ""              (default)  200 vectors
  ├── namespace: "q1-reports"              500 vectors
  ├── namespace: "q2-reports"              420 vectors
  └── namespace: "q4-reports"              380 vectors
```

```python
# Upsert into a namespace
index.upsert(vectors=batch, namespace="q4-reports")

# Query a specific namespace
index.query(vector=query_vec, top_k=5, namespace="q4-reports")
```

Use namespaces to organise documents without creating separate indexes. Each Pinecone
project has a quota on the number of indexes (1 on the free tier), so namespaces are
how you host multiple document collections for free.

---

### 4. Serverless vs Pod-Based

Pinecone offers two index types:

```
┌──────────────────┬────────────────────────────────────────────────┐
│                  │ SERVERLESS          │ POD-BASED                │
├──────────────────┼─────────────────────┼──────────────────────────┤
│ Infrastructure   │ Fully managed       │ Dedicated pods           │
│ Scaling          │ Automatic           │ Manual (add pods)        │
│ Cost model       │ Pay per query       │ Pay per pod/hour         │
│ Free tier        │ Yes (1 index, 2GB)  │ No                       │
│ Latency          │ Variable            │ Consistent               │
│ Best for         │ Most use cases      │ Strict SLA workloads     │
└──────────────────┴─────────────────────┴──────────────────────────┘
```

For learning and prototyping, always use **Serverless**. It costs nothing for small
datasets and requires zero configuration beyond choosing `cloud` and `region`.

---

## How Similarity Search Works Internally

### Step 1 — Cosine Similarity

Pinecone measures how similar two vectors are by computing the **cosine of the angle**
between them.

```
                     A · B
similarity(A, B) = ─────────
                   |A| × |B|

Result range:
  1.0  →  vectors point in same direction  →  identical meaning
  0.0  →  vectors are perpendicular         →  unrelated
 -1.0  →  vectors point opposite directions →  opposing meaning
```

For text embeddings, scores rarely go below 0 — but values above 0.8 indicate strong
semantic similarity, while values below 0.5 are usually noise.

### Step 2 — The Brute Force Problem

If your index has 1 million vectors, computing cosine similarity against all of them
for every query would be 1 million multiplications — far too slow for interactive use.

```
1M vectors × 1536 floats × cosine math = ~100ms per query at best
At 100 queries/second = fully saturated
```

### Step 3 — ANN Index (HNSW)

Pinecone solves this with **Approximate Nearest Neighbour** search using an HNSW graph
(Hierarchical Navigable Small World) — the same algorithm covered in the HNSW explainer.

The key idea: build a multi-layer graph where upper layers are sparse long-range
connections and the bottom layer has all vectors densely connected.

```
Layer 2 (sparse — 1% of vectors)
  ●─────────────────────────●
  │ long-range connections  │
  │ for fast navigation     │
  ●─────────────────────────●

Layer 1 (medium — 10% of vectors)
  ●───●       ●───●
  │   │       │   │
  ●───●───────●───●

Layer 0 (dense — 100% of vectors)
  ●─●─●─●─●─●─●─●─●─●─●─●
  every vector is here
  local connections only
```

**Search traversal:**
1. Enter at the top layer at the designated entry point
2. Greedily hop towards the query vector (always move to the nearest neighbour)
3. Drop down to the next layer and repeat
4. At Layer 0, scan the local neighbourhood for the true top-K

This finds the nearest vectors in `O(log N)` hops instead of `O(N)` comparisons.
The trade-off is "approximate" — it may miss the absolute closest vector occasionally,
but recall@5 of 0.95+ is typical and the speed gain is enormous.

---

## Distributed Systems Architecture

This is the layer most explanations skip. Pinecone is not a single machine running HNSW
— it is a distributed system spread across many nodes, with a clear separation between
the **control plane** (managing the cluster) and the **data plane** (storing and searching
vectors).

### High-Level Node Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PINECONE CLUSTER                                     │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      CONTROL PLANE                                  │   │
│  │                                                                     │   │
│  │   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐         │   │
│  │   │  Master Node │    │  Master Node │    │  Master Node │         │   │
│  │   │  (Primary)   │◄──►│  (Standby 1) │◄──►│  (Standby 2) │         │   │
│  │   └──────┬───────┘    └──────────────┘    └──────────────┘         │   │
│  │          │  leader election via Raft consensus                      │   │
│  │          │                                                          │   │
│  │          │  responsibilities:                                       │   │
│  │          │    - index metadata (dimensions, metric, namespaces)     │   │
│  │          │    - shard assignment map (which shard owns which IDs)   │   │
│  │          │    - cluster membership (tracks which nodes are alive)   │   │
│  │          │    - replication topology                                │   │
│  └──────────┼─────────────────────────────────────────────────────────┘   │
│             │                                                               │
│             │ routing decisions                                             │
│             ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       DATA PLANE                                     │  │
│  │                                                                      │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐         │  │
│  │  │   SHARD 0      │  │   SHARD 1      │  │   SHARD 2      │         │  │
│  │  │                │  │                │  │                │         │  │
│  │  │ Primary Node   │  │ Primary Node   │  │ Primary Node   │         │  │
│  │  │ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │         │  │
│  │  │ │ HNSW graph │ │  │ │ HNSW graph │ │  │ │ HNSW graph │ │         │  │
│  │  │ │ (subset of │ │  │ │ (subset of │ │  │ │ (subset of │ │         │  │
│  │  │ │  vectors)  │ │  │ │  vectors)  │ │  │ │  vectors)  │ │         │  │
│  │  │ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │         │  │
│  │  │                │  │                │  │                │         │  │
│  │  │ Replica Node   │  │ Replica Node   │  │ Replica Node   │         │  │
│  │  │ (hot standby)  │  │ (hot standby)  │  │ (hot standby)  │         │  │
│  │  └────────────────┘  └────────────────┘  └────────────────┘         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       QUERY ROUTER                                   │  │
│  │    fan-out query → all shards → merge results → return top-K        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### Control Plane — Master Nodes

The master nodes form a **Raft consensus cluster** (typically 3 nodes for odd quorum).

**What Raft consensus means:**
- One master is elected **Primary** (leader)
- All metadata writes go through the Primary
- Primary replicates every write to Standby nodes before acknowledging
- If Primary dies, Standbys hold an election and a new Primary is chosen in seconds
- Requires majority (2 of 3) to agree before any write is confirmed

```
Write to master:
  Client → Primary Master
               │
               ├── replicate → Standby 1  ✓
               ├── replicate → Standby 2  ✓
               │
               └── majority confirmed → acknowledge to client

Primary dies:
  Standby 1 detects heartbeat timeout
  Standby 1 + Standby 2 vote → Standby 1 becomes new Primary
  Cluster continues within seconds
```

**What the master stores:**
- Index configuration (dimension, metric, creation time)
- **Shard assignment map** — the routing table that says "vector IDs 0–33% live on
  Shard 0, 34–66% on Shard 1, 67–100% on Shard 2"
- Namespace definitions
- Node health and cluster membership
- Replication factor settings

The master nodes **never store vector data** — they only store the map of where
vector data lives.

---

### Data Plane — Shards, Primaries, and Replicas

#### Sharding

A **shard** is a horizontal partition of the vector data. Instead of one node holding
all vectors (which limits you to one machine's RAM), the vectors are split across
multiple shards.

```
Total: 900 vectors, 3 shards

Shard 0: vectors 1–300    (owns IDs in bucket 0)
Shard 1: vectors 301–600  (owns IDs in bucket 1)
Shard 2: vectors 601–900  (owns IDs in bucket 2)
```

**How sharding assignment works:**
When you upsert a vector, the master's routing table determines which shard owns
that vector ID (typically via consistent hashing of the ID string). The write is
sent directly to that shard's Primary Node.

#### Primary Node (per shard)

Each shard has one **Primary Node** that:
- Accepts all **write** operations (upserts, deletes) for its shard
- Maintains the **HNSW graph** for its subset of vectors in memory
- Replicates every write to its Replica Node(s) before acknowledging
- Serves read/query requests

#### Replica Node (per shard)

Each shard also has one or more **Replica Nodes** that:
- Maintain an **identical copy** of the Primary's HNSW graph
- Can serve **read/query** requests (load sharing)
- Promoted to Primary instantly if the Primary Node fails
- Are "hot standbys" — always up-to-date, no rebuild needed on failover

```
Shard 0 write path:
  Upsert request
       │
       ▼
  Primary Node (Shard 0)
       │  write to HNSW graph
       │  replicate to replica
       ▼
  Replica Node (Shard 0)  ← exact copy, ready to take over
       │
  Acknowledge to client
```

---

### Query Router — Fan-Out and Merge

When you call `index.query(vector=q, top_k=5)`, the request hits the **Query Router**
which does not hold any vector data — it is a stateless coordinator:

```
Step 1 — Fan-out
  Query Router receives query vector q, top_k=5
       │
       ├── send query to Shard 0 Primary  → "give me your top-5"
       ├── send query to Shard 1 Primary  → "give me your top-5"
       └── send query to Shard 2 Primary  → "give me your top-5"
              (all three queries run IN PARALLEL)

Step 2 — Local HNSW search (per shard, simultaneously)
  Shard 0: traverses its HNSW graph → returns its top-5 candidates
  Shard 1: traverses its HNSW graph → returns its top-5 candidates
  Shard 2: traverses its HNSW graph → returns its top-5 candidates

Step 3 — Merge
  Query Router receives 3 × 5 = 15 candidates with scores
  Sorts all 15 by cosine similarity score (descending)
  Returns the global top-5 to the client
```

This is why sharding works: each shard does a fast local HNSW search on its subset,
and the router merges the results. The caller sees one unified ranked list.

**Why fan-out to all shards?**
Because the globally most similar vector could be on any shard. The router cannot
know in advance which shard holds the nearest neighbour — it must ask all of them
and pick the best from each response.

---

### Write Path — Full Journey of an Upsert

```
Your code:
  index.upsert(vectors=[{"id": "chunk_42", "values": [...], "metadata": {...}}])
       │
       ▼
  Pinecone API Gateway (HTTPS)
       │  authenticates API key
       │
       ▼
  Master Node (Primary)
       │  consults shard assignment map
       │  "chunk_42" → hash → Shard 1
       │
       ▼
  Shard 1 — Primary Node
       │  inserts vector into HNSW graph in memory
       │  assigns layer via random float r → layer_max formula
       │  connects to m=16 nearest neighbours at each layer
       │  replicates to Replica Node
       │
       ▼
  Shard 1 — Replica Node  (exact copy written synchronously)
       │
       ▼
  Acknowledge: upsert accepted
```

The HNSW insertion itself (the random layer assignment, neighbour connection, edge
creation) happens on the **Primary Node of the responsible shard**. This is why
insert order matters for HNSW graph quality — but not for query correctness.

---

### Read Path — Full Journey of a Query

```
Your code:
  index.query(vector=[...], top_k=5, include_metadata=True)
       │
       ▼
  Pinecone API Gateway (HTTPS)
       │  authenticates, routes to Query Router
       │
       ▼
  Query Router
       │  fan-out: dispatch to all 3 shard Primaries in parallel
       │
       ├─────────────────────────────────────────────┐
       ▼                    ▼                         ▼
  Shard 0 Primary      Shard 1 Primary           Shard 2 Primary
  HNSW traversal       HNSW traversal            HNSW traversal
  → local top-5        → local top-5             → local top-5
       │                    │                         │
       └──────────┬──────────┘─────────────────────────┘
                  ▼
          Query Router merges 15 candidates
          Sorts by cosine score
          Returns global top-5 with metadata
                  │
                  ▼
          Your code receives matches list
```

---

### Failure Scenarios and Recovery

#### Primary Node Failure

```
Normal state:
  Shard 0: Primary (alive) ←── writes
                 │
                 └── Replica (alive) ←── reads

Primary dies:
  Shard 0: Primary (DEAD)
                 │
                 └── Replica (alive) ← promoted to Primary instantly
                                        (already has full HNSW graph)

Recovery time: seconds (no data rebuild needed — replica was hot)
```

#### Master Node Failure

```
Normal state:
  Primary Master (alive) ─── Standby 1 ─── Standby 2

Primary Master dies:
  Standby 1 + Standby 2 detect heartbeat timeout
  Raft election: Standby 1 wins majority
  Standby 1 becomes new Primary Master

Recovery time: seconds (Raft election is fast)
Data loss: zero (all metadata was replicated before acknowledgement)
```

#### Shard Failure During Query

```
Query Router fans out to Shard 0, Shard 1, Shard 2
Shard 1 Primary fails mid-query
       │
       ├── Shard 1 Replica takes over
       └── Query Router retries the Shard 1 sub-query
           (timeout + retry is handled internally)

Result: client gets top-5 results, slightly higher latency
        no error returned (transparent failover)
```

---

### Serverless Architecture — How It Differs

In **Serverless mode** (what you use in this pipeline), the physical node topology
is hidden from you entirely. Pinecone manages sharding, replication, and scaling
automatically based on your usage pattern.

```
Pod-Based (you manage):
  You choose: 1 pod → 4 pods → 8 pods (manual scaling decisions)
  You set: replication factor (how many replicas per shard)
  You pay: per pod per hour, always on

Serverless (Pinecone manages):
  Zero vectors → minimal cost
  Burst to 1M queries → auto-scales
  You pay: per query unit and per stored vector
  Nodes, shards, replicas → invisible to you

Under the hood, Serverless still uses the same architecture —
shards, primaries, replicas, query router — but Pinecone's
control plane makes all the scaling decisions automatically.
```

The code you write is **identical** for both. The `Pinecone()` client, `upsert()`,
and `query()` calls are the same. Serverless vs Pod-based is purely a
cost/control trade-off at the infrastructure layer.

---

### How Namespaces Map to the Distributed Architecture

A namespace is **not** a separate shard or a separate set of nodes. It is a
logical tag applied to each vector record within the existing shards.

```
Shard 0 memory (HNSW graph + metadata):
  chunk_1  namespace=""         values=[...]
  chunk_2  namespace="q4-2024"  values=[...]
  chunk_3  namespace="q4-2024"  values=[...]
  chunk_4  namespace="q1-2024"  values=[...]
```

When you query with `namespace="q4-2024"`:
1. Query Router fans out to all shards as usual
2. Each shard's HNSW search is restricted to vectors tagged `namespace="q4-2024"`
3. Results from other namespaces are excluded before scoring

This means namespaces have **zero infrastructure overhead** — no extra nodes,
no extra replication. They are purely a filter applied at search time within each shard.

---

## Metadata Filtering — Pre-filter vs Post-filter

Pinecone's metadata filtering happens **before** the ANN search, not after.

```
WITHOUT FILTER:
  All 1300 vectors
       ↓ ANN search (fast, full index)
  Top-5 results

WITH FILTER {"source": "annual_report_2024.pdf"}:
  All 1300 vectors
       ↓ metadata filter (220 vectors remain)
  Filtered 220 vectors
       ↓ ANN search (fast, smaller candidate set)
  Top-5 results from that document only
```

This is called **pre-filtering** and it is more efficient than retrieving top-K results
and then discarding non-matching ones. However, if the filter is very selective (e.g.
matches only 3 vectors) and `top_k=5`, you may get fewer than 5 results back.

### Supported Filter Operators

```python
# Exact match
{"source": {"$eq": "report.pdf"}}
{"pii_redacted": {"$eq": True}}

# Range
{"page": {"$gte": 5, "$lte": 20}}
{"char_count": {"$gt": 500}}

# List membership
{"key_phrases": {"$in": ["Agentic AI", "LLM"]}}

# Negation
{"source": {"$ne": "disclaimer.pdf"}}
{"page": {"$nin": [1, 2]}}

# Compound (implicit AND)
{"source": "report.pdf", "page": {"$gte": 10}}
```

Available metadata fields (stored at ingestion in `load_embeddings_to_pinecone.py`):

| Field | Type | Example |
|---|---|---|
| `text` | string | chunk content (truncated to 10KB) |
| `source` | string | `"annual_report_2024.pdf"` |
| `page` | int | `7` |
| `breadcrumbs` | string | `"Executive Summary > Key Findings"` |
| `key_phrases` | string | `"Agentic AI, pricing power, MSCI World"` |
| `char_count` | int | `1489` |
| `pii_redacted` | bool | `True` |

---

## Upsert — Why There Is No "Insert"

Pinecone only has **upsert**, not insert. If a vector with the same ID already exists,
it is **overwritten** with the new values and metadata.

```python
# First run: creates 20 new vectors
index.upsert(vectors=batch)

# Second run on same file: overwrites the same 20 vectors
# No duplicate-key errors, no manual deduplication needed
index.upsert(vectors=batch)
```

This makes ingestion scripts fully **idempotent** — safe to re-run at any time.
If you fix a bug in your enrichment pipeline and re-process the same documents,
just re-run the loader and the updated chunks replace the old ones automatically.

---

## Pinecone vs pgvector

Both store vectors and search by cosine distance. The choice is operational:

```
┌──────────────────┬──────────────────────────────┬────────────────────────────────┐
│                  │ PINECONE                      │ PGVECTOR                       │
├──────────────────┼──────────────────────────────┼────────────────────────────────┤
│ Type             │ Managed cloud service         │ PostgreSQL extension            │
│ Setup            │ API key + one function call   │ Docker / RDS / local install   │
│ Query language   │ Python SDK (index.query())    │ SQL with <=> operator          │
│ SQL joins        │ No                            │ Yes — join with any Postgres   │
│                  │                               │ table                          │
│ Cost             │ Free tier (1 index, 2GB)      │ Free forever (self-hosted)     │
│                  │ then pay-per-query            │                                │
│ Scale            │ Serverless auto-scale         │ Manual HNSW/IVFFlat tuning     │
│ Filtering        │ Metadata pre-filter           │ SQL WHERE clause               │
│ Replication      │ Built-in                      │ Your responsibility            │
│ Best for         │ Production RAG, no infra team │ Analytics, existing Postgres   │
│                  │ Rapid prototyping             │ stack, complex joins           │
└──────────────────┴──────────────────────────────┴────────────────────────────────┘
```

In your pipeline, both do **exactly the same job**. The embedding model, chunk format,
and RAG pattern are identical. The only difference is where you point the search:

```python
# pgvector search
cursor.execute("SELECT ... FROM chunks ORDER BY embedding <=> %s::vector LIMIT 5", ...)

# Pinecone search
index.query(vector=query_vec, top_k=5, include_metadata=True)
```

---

## The Search Flow End-to-End

```
User types: "What is Agentic AI?"
                │
                ▼
        embed_query()
        OpenAI text-embedding-3-small
        "What is Agentic AI?" → [0.12, -0.34, ..., 0.87]  (1536 floats)
                │
                ▼
        index.query(vector=[...], top_k=5)
                │
        Pinecone internals:
          1. Apply metadata filter (if any)
          2. Enter HNSW graph at Layer 2
          3. Greedily hop toward query vector
          4. Descend to Layer 1, continue
          5. Descend to Layer 0, scan local neighbourhood
          6. Return top-5 by cosine similarity
                │
                ▼
        matches = [
          {id: "chunk_7", score: 0.91, metadata: {text: "Agentic AI gives agency..."}},
          {id: "chunk_2", score: 0.87, metadata: {text: "2025 will be the year of..."}},
          {id: "chunk_4", score: 0.83, metadata: {text: "move from chatbot phase..."}},
          ...
        ]
                │
                ▼
        summarise()
        GPT reads the 5 chunk texts (not vectors)
        Synthesises a direct answer with chunk citations
                │
                ▼
        "According to Chunk #1, Agentic AI refers to..."
```

GPT never touches the vectors. It only reads the text stored in `metadata.text`.
Its role is pure language generation — Pinecone does all the retrieval.

---

## Key Numbers to Remember

| Concept | Value |
|---|---|
| Embedding dimensions (text-embedding-3-small) | 1536 |
| Metadata limit per vector | 40KB |
| Recommended batch size for upsert | 100–200 vectors |
| Free tier | 1 serverless index, ~2GB storage |
| Cosine similarity range | 0.0 (unrelated) → 1.0 (identical) |
| Typical good similarity score | > 0.75 |
| HNSW search complexity | O(log N) vs O(N) brute force |

---

## Common Mistakes

**1. Using a different embedding model at search time**
The most common and most silent mistake. If you loaded with `text-embedding-3-small`
(1536 dims) but search with `all-MiniLM-L6-v2` (384 dims), the query call will fail
with a dimension mismatch error. If you search with `ada-002` (also 1536 dims but a
different model), it will not error — it will just silently return meaningless results
because the vectors live in different geometric spaces.

**2. Storing nested metadata**
Pinecone metadata must be flat key-value pairs. Passing a nested dict like
`{"entities": {"PERSON": ["Alice"], "ORG": ["Acme"]}}` will either error or be
silently dropped. Flatten or serialise to a string first.

**3. Expecting exact counts after upsert**
`describe_index_stats()` updates **asynchronously**. The vector count may lag by a
few seconds after a large upsert. Wait 2–3 seconds before checking stats — or simply
trust the SDK's upsert response, which confirms what was accepted.

**4. Very selective filters with small top_k**
If your filter matches only 3 vectors and `top_k=5`, you get 3 results back — not an
error. Always set `top_k` higher than the minimum acceptable number of results when
using selective filters.

**5. Forgetting `include_metadata=True`**
Pinecone's `query()` does **not** return metadata by default — it only returns IDs and
scores. Without `include_metadata=True`, the `metadata` field is empty and you have
no chunk text to pass to GPT.

---

## Quick Reference — Code Patterns

```python
from pinecone import Pinecone, ServerlessSpec

pc = Pinecone(api_key="pc-...")

# Create index
pc.create_index(
    name="my-docs",
    dimension=1536,
    metric="cosine",
    spec=ServerlessSpec(cloud="aws", region="us-east-1")
)

# Connect
index = pc.Index("my-docs")

# Upsert
index.upsert(vectors=[
    {"id": "chunk_1", "values": [...], "metadata": {"text": "...", "source": "doc.pdf"}}
], namespace="my-namespace")

# Query
results = index.query(
    vector=[...],          # query embedding
    top_k=5,
    namespace="my-namespace",
    filter={"source": {"$eq": "doc.pdf"}},
    include_metadata=True  # required to get text back
)

for match in results["matches"]:
    print(match["score"], match["metadata"]["text"])

# Stats
stats = index.describe_index_stats()
print(stats["total_vector_count"], stats["dimension"])
```
