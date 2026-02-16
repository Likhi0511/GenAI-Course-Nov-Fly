# HNSW — The Graph-Based Vector Index
### How pgvector Searches Millions of Vectors Using Hierarchical Navigable Small Worlds

---

## The Problem: Searching a Million Vectors

After loading your embeddings into pgvector, every RAG query boils down to one operation:

> *"Given this query vector, find the K chunks whose vectors are closest to it."*

This is called **K-Nearest Neighbour (KNN) search**.

The naive approach — compare the query against every single vector in the table — is called an **exact search** or **brute-force search**. It is perfectly accurate. It is also painfully slow at scale.

### How the Operation Count Is Calculated

Each brute-force query compares the query vector against **every row**, and each comparison costs one multiply-add per dimension. This is because cosine similarity is computed as:

```
similarity = Σ (query[i] × chunk[i])   for i in range(dimensions)
```

So for every row you perform `dimensions` multiplications and `dimensions` additions:

```
Row 1:    [0.12, -0.34, 0.88, ..., 0.41]  ← 384 multiply-adds
Row 2:    [0.21,  0.11, 0.55, ..., 0.09]  ← 384 multiply-adds
...
Row 1000: [...]                            ← 384 multiply-adds

Total = 1,000 × 384 = 384,000 multiply-add operations
```

| Rows | Dimensions | Dominant cost (rows × dims) | What the table shows |
|---|---|---|---|
| 1,000 | 384 | 384,000 operations | dot products only |
| 100,000 | 384 | 38,400,000 operations | dot products only |
| 10,000,000 | 1536 | 15,360,000,000 operations | dot products only |

> **Note:** These numbers are actually understated. Each query also computes two magnitude values (for cosine normalisation), `rows` division operations, and `rows` comparisons to track the top-K result set. The real operation count is roughly 2× the table — the table shows only the dominant term.

### Why It Gets Slow: Three Compounding Factors

**1. Memory bandwidth — the real bottleneck**

All vectors must be loaded from RAM into CPU cache before any arithmetic happens:

```
1,000,000 rows × 1536 dimensions × 4 bytes per float
= 6 GB of data that must move through memory for every single query

Memory bandwidth ≈ 50 GB/s on a typical server
→ 6 GB / 50 GB/s = 0.12 seconds just reading the data
   (before a single multiply-add is done)
```

**2. Concurrent queries**

A production RAG system handles many users simultaneously. If 100 users query at once and each query needs 15 billion operations, the database is attempting 1.5 trillion operations per second — no hardware handles that without queuing.

**3. Latency budget**

A typical RAG query has a 200ms end-to-end budget (embed + retrieve + LLM generation). Brute-force at scale consumes the entire budget on retrieval alone before the LLM has started.

### The Real-World Viability Threshold

```
< 10,000 rows     → brute-force is fine, no index needed
10,000–100,000    → borderline, depends on query volume
> 100,000 rows    → index required
```

At a million documents, a brute-force search takes seconds per query. A RAG system needs results in milliseconds. The solution is an **Approximate Nearest Neighbour (ANN) index**.

---

## HNSW — The Social Network Approach

### The Intuition

Think about how information spreads in a social network. If you want to reach someone you don't know, you don't message every person on the platform. You message a friend, who knows someone, who knows someone else — and within a few hops you reach the target. This is the "six degrees of separation" idea.

HNSW builds a similar navigable network — not of people, but of vectors. To find the nearest vector to your query, you start somewhere in the network, hop to closer and closer nodes, and converge on the answer in very few steps.

The full name — **Hierarchical Navigable Small World** — describes exactly this structure.

---

## The Multi-Layer Graph

HNSW builds a **multi-layer graph**. Picture it like a map at different zoom levels:

```
Layer 2 (highway network — very few nodes, long-range connections):
  v1 ————————————————— v500 ————————————————— v9000

Layer 1 (main roads — more nodes, shorter connections):
  v1 ——— v50 ——— v200 ——— v500 ——— v700 ——— v9000

Layer 0 (local streets — ALL nodes, shortest connections):
  v1 — v3 — v8 — v12 — ... — v500 — v501 — ... — v9000
```

The top layers act like a highway — they cover large distances quickly. Layer 0 handles precision. Search starts fast at the top and ends precise at the bottom.

---

## How Vectors Get Assigned to Layers

This is the most important thing to understand about HNSW and the most commonly misunderstood.

### The Rule: One Random Number, Decided at Insert Time

When vector `v` arrives to be inserted, the code runs exactly this:

```python
import math, random

r = random.random()          # Step 1: generate one random float between 0.0 and 1.0
mL = 1.0 / math.log(m)      # Step 2: compute the normalisation factor from m
layer_max = int(-math.log(r) * mL)   # Step 3: this integer is the highest layer v will live in
```

That single integer `layer_max` determines everything:

```
layer_max = 0  →  vector lives in layer 0 only
layer_max = 1  →  vector lives in layer 0 AND layer 1
layer_max = 2  →  vector lives in layer 0, layer 1, AND layer 2
```

**Every vector always lands in layer 0. No exceptions.**  
Only some get promoted higher — purely by chance.

---

### What `r` Is — and What It Is Not

`r = random.random()` is just a plain random float. It knows **nothing** about the vector. It does not look at the vector's 384 numbers. It does not care what the vector means. It does not prefer "important" or "central" vectors.

`r` is purely a **probabilistic gate** — its only job is to answer: *does this vector get promoted to a higher layer, yes or no?*

The vector's actual content (its 384 or 1536 numbers) plays **zero role** in deciding which layer it goes to. Content is used only **after** the layer is decided — when finding which neighbours to connect to at each layer.

```
New vector v  =  [0.12, -0.34, 0.88, ..., 0.41]  (384 numbers)

Step 1: r = random()  →  layer_max = 1       ← content NOT used here
                                                 purely random gate

Step 2: insert into layer 1
        → compare v's 384 numbers against existing layer 1 vectors
        → find the m nearest by cosine similarity
        → create edges                        ← content IS used here

Step 3: insert into layer 0
        → compare v's 384 numbers against existing layer 0 vectors
        → find the m nearest by cosine similarity
        → create edges                        ← content IS used here
```

---

### Why Does `-ln(r)` Produce the Right Distribution?

`r = random.random()` gives a uniform float between 0 and 1. Here is how `-ln(r)` transforms it:

```
r value     -ln(r)     layer_max (m=16, mL=0.36)
─────────   ──────     ─────────────────────────
0.99        0.01       0    ← int(0.01 × 0.36) = int(0.004) = 0
0.90        0.11       0    ← int(0.11 × 0.36) = int(0.040) = 0
0.72        0.33       0    ← int(0.33 × 0.36) = int(0.118) = 0
0.50        0.69       0    ← int(0.69 × 0.36) = int(0.250) = 0
0.30        1.20       0    ← int(1.20 × 0.36) = int(0.433) = 0
0.10        2.30       0    ← int(2.30 × 0.36) = int(0.830) = 0
0.05        3.00       1    ← int(3.00 × 0.36) = int(1.080) = 1  ✓ promoted
0.01        4.61       1    ← int(4.61 × 0.36) = int(1.660) = 1  ✓ promoted
0.002       6.22       2    ← int(6.22 × 0.36) = int(2.237) = 2  ✓ promoted
0.0003      8.11       2    ← int(8.11 × 0.36) = int(2.920) = 2  ✓ promoted
0.00005     9.90       3    ← int(9.90 × 0.36) = int(3.564) = 3  ✓ promoted
```

The `-ln` function stretches small values of `r` into large numbers and compresses large values into small numbers. Combined with `int()` truncation, the result is an **exponential probability distribution**:

```
For m=16, across 10,000 vectors:

Layer 0 : all 10,000  (100%)     ← every single vector
Layer 1 : ~630        (~6.3%)    ← only r < 0.063 produce layer_max ≥ 1
Layer 2 : ~40         (~0.4%)    ← only r < 0.004 produce layer_max ≥ 2
Layer 3 : ~2          (~0.02%)   ← extremely rare
```

Most values of `r` are large (close to 1.0), which means `-ln(r)` is small, which means `layer_max = 0` is the most common outcome by far. Only when `r` happens to be very small (a rare event) does the vector get promoted upward.

---

### Walking Through 10 Insertions

```
m = 16,  mL = 0.36

Vector    r value    -ln(r)    × mL    int    layer_max    Lives in
──────    ───────    ──────    ────    ───    ─────────    ────────────────────
v1        0.82       0.20      0.07    0      0            L0
v2        0.67       0.40      0.14    0      0            L0
v3        0.91       0.09      0.03    0      0            L0
v4        0.04       3.22      1.16    1      1            L0, L1
v5        0.55       0.60      0.22    0      0            L0
v6        0.78       0.25      0.09    0      0            L0
v7        0.002      6.21      2.24    2      2            L0, L1, L2
v8        0.44       0.82      0.29    0      0            L0
v9        0.33       1.11      0.40    0      0            L0
v10       0.06       2.81      1.01    1      1            L0, L1

Result after 10 insertions:
  Layer 2:  v7                              (1 vector)
  Layer 1:  v4, v7, v10                     (3 vectors)
  Layer 0:  v1,v2,v3,v4,v5,v6,v7,v8,v9,v10 (all 10)
```

v7 happened to draw `r = 0.002` — a rare small value — so it was promoted all the way to layer 2. This is now the **entry point** for all searches: every query starts at v7 in layer 2. v7 has no special meaning in terms of content. It just got lucky.

---

### Why Random Assignment Works Better Than Semantic Selection

The random selection feels counterintuitive — surely the "most central" or "most important" vectors should be in the upper layers?

Random actually works *better* for a geometric reason. The upper layers exist purely as **navigation shortcuts** — they let search cover large distances quickly. For shortcuts to work well, upper-layer vectors need to be **evenly spread** across the entire vector space.

```
Good upper layer (random — evenly spread):
  ·         ·              ·
        ·         ·
  ·              ·     ·
       ·    ·
  → Can navigate to any corner of the space in few hops

Bad upper layer (semantic — most common topics dominate):
         · · ·
        · · · ·     ← all clustered in the dense middle
         · · ·
  → Edges of the space are poorly reachable
```

Random selection naturally gives uniform spatial coverage. Any hand-picked semantic selection would over-represent the most common topics and leave rare regions poorly connected.

---

## The `m` Parameter: Why 16?

```sql
CREATE INDEX ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

`m` controls **how many edges each vector gets at each layer it lives in**.

It has nothing to do with the random number `r`. It is a fixed configuration parameter you choose before building the index.

### Where 16 Comes From

It is an empirically tested default from the original HNSW research paper. The authors benchmarked across many datasets and found `m=16` sits at the sweet spot of speed, recall, and memory for most real workloads.

```
m = 4   →  4 edges per node  →  sparse graph
           few hops possible  →  lower recall
           very low memory

m = 16  →  16 edges per node  →  well-connected graph
           ← sweet spot — good recall, manageable memory

m = 64  →  64 edges per node  →  very dense graph
           excellent recall
           4× more memory than m=16, much slower to build
```

### What m Looks Like in the Graph

After inserting v_new with m=16, it connects to its 16 nearest neighbours at each layer:

```
Layer 0 after inserting v_new:

         v_003
        /
       v_007
      /
v_new — v_012
      \
       v_019    ← 16 edges total, each to a nearby vector
       v_024       connections are BIDIRECTIONAL
       ...         v_003 also gets an edge back to v_new
       v_891
```

### Rule of Thumb for Choosing m

| Dataset size | Recommended m |
|---|---|
| < 100K rows | 8 – 16 |
| 100K – 1M rows | 16 – 32 |
| > 1M rows | 32 – 64 |

For your document RAG pipeline (typically tens of thousands of chunks), `m=16` is correct.

> **Layer 0 special case:** pgvector doubles the connection count at the base layer to `2m` (so 32 edges for m=16). Layer 0 holds every vector and is where precision search happens — the extra connections ensure it stays densely navigable.

---

## The `ef_construction` Parameter

When inserting a new vector, the algorithm needs to find its best `m` neighbours at each layer. `ef_construction` controls how many candidates it considers before picking the final `m`.

```
ef_construction = 32  →  considers 32 candidates → picks best 16
                          fast build, but the 16 chosen may not be the true nearest
                          lower quality graph → lower recall at query time

ef_construction = 64  →  considers 64 candidates → picks best 16  (default)
                          good balance

ef_construction = 200 →  considers 200 candidates → picks best 16
                          slow build, but almost certainly finds the true 16 nearest
                          highest quality graph → best recall at query time
```

You only pay the build cost once. A higher `ef_construction` is worth it for production indexes.

**Rule of thumb:** `ef_construction ≥ m` always. Never set it lower — you'd be asking the algorithm to find 16 neighbours from fewer than 16 candidates, which is impossible.

---

## What Happens During a Full Insertion

Putting it all together — here is the complete sequence when a new vector arrives:

```
New vector v  (rolled layer_max = 1 from the random formula)

Current top layer of the index = 2
         │
         ▼
TRAVERSE layer 2  (v is NOT inserted here — just navigating to find a good entry point)
  → greedy hop toward v's location in vector space
         │
         ▼
ARRIVE at layer 1  (= layer_max — start inserting here)
  → search for m=16 nearest neighbours using v's actual 384 numbers
  → create bidirectional edges to those 16 neighbours
         │
         ▼
DESCEND to layer 0
  → search for 2m=32 nearest neighbours (base layer gets double edges)
  → create bidirectional edges to those 32 neighbours
         │
         ▼
Done — v is permanently wired into the graph at layers 0 and 1
```

---

## The Query-Time Parameter: `ef_search`

```sql
SET hnsw.ef_search = 40;  -- default: 40
```

At query time, the greedy traversal tracks a list of candidate neighbours. `ef_search` is the size of that candidate list:

```
ef_search=10  → tracks 10 candidates → very fast, lower recall
ef_search=40  → tracks 40 candidates → balanced (default)
ef_search=200 → tracks 200 candidates → slower, very high recall
```

Unlike `m` and `ef_construction`, you can tune `ef_search` per query without rebuilding the index. Useful for high-stakes queries where you want maximum recall, and fast queries where speed matters more.

---

## Why "Small World" and Why Logarithmic Time

In graph theory, a "small world" network is one where any node is reachable from any other in a surprisingly small number of hops — even in a huge graph. HNSW is designed to have this property at every layer.

Because upper-layer membership is random and exponentially sparse, the expected number of hops to reach any point from any starting point is:

```
O(log N)   — logarithmic in the number of vectors

For N = 1,000,000 vectors:
  log(1,000,000) ≈ 20 hops through the upper layers to reach any neighbourhood
  then a local search in layer 0

Compare to a flat graph (no layers):
  O(√N) = O(1,000) hops — 50× more
```

This logarithmic behaviour is what makes HNSW fast even at millions of vectors.

---

## HNSW Summary

```
Build time  : Slower (more time + memory than IVFFlat)
Memory      : Higher (full graph must fit in RAM for best performance)
Query speed : Faster than IVFFlat
Recall      : Higher than IVFFlat at the same speed setting
Inserts     : Handled natively — no reindex needed
Best for    : Production RAG, quality-critical retrieval,
              any pipeline where rows keep growing
```

---

## What "Recall" Actually Means

### The One-Line Definition

> **Recall** = the fraction of the true nearest neighbours that the approximate index actually returns.

### Where the Word Comes From

"Recall" is borrowed from information retrieval, where it means:

```
          relevant results returned
Recall = ──────────────────────────
           total relevant results
```

In vector search, "relevant" means "would appear in the exact brute-force top-K result."

### A Concrete Example

Say you run a query and want the top-5 most similar chunks. The exact brute-force result would be:

```
Exact top-5 (ground truth):
  Rank 1: chunk_042  similarity=0.94
  Rank 2: chunk_107  similarity=0.91
  Rank 3: chunk_389  similarity=0.88
  Rank 4: chunk_012  similarity=0.85
  Rank 5: chunk_601  similarity=0.83
```

Your HNSW index returns:

```
Approximate top-5 (what the index found):
  chunk_042  ✓  (was rank 1 — correct)
  chunk_107  ✓  (was rank 2 — correct)
  chunk_389  ✓  (was rank 3 — correct)
  chunk_012  ✓  (was rank 4 — correct)
  chunk_891  ✗  (NOT in ground truth — missed chunk_601, returned chunk_891 instead)
```

```
Recall@5 = 4 correct out of 5 ground truth = 0.80 (80%)
```

### The "@K" Notation

| Notation | Meaning |
|---|---|
| Recall@1 | Did the index return the single closest vector? |
| Recall@5 | Of the 5 results returned, how many were in the true top-5? |
| Recall@10 | Of the 10 results returned, how many were in the true top-10? |

Higher K is usually easier — more slots means fewer misses matter. Recall@10 is almost always higher than Recall@1 for the same index.

### Typical Values in Practice

| Index | Typical Recall@10 |
|---|---|
| Brute-force (exact) | 1.00 — always perfect |
| HNSW (default settings) | 0.95 – 0.99 |
| HNSW (low `ef_search`) | 0.85 – 0.92 |

### Why Recall < 1.0 Is Acceptable for RAG

If your index has Recall@5 = 0.80, it might return ranks 1–4 correctly but swap rank 5 for the 6th-best chunk (similarity 0.82 — almost identical). The LLM generating an answer from these 5 chunks will produce the same answer either way.

**The scenario where low recall actually hurts:**  
If the only chunk containing the answer is ranked 8th, and `ef_search` only searches deeply enough to find the top-5, you will miss it. This is the failure mode that motivates tuning `ef_search` upward for high-stakes retrieval.

### The Speed–Recall Trade-off Visualised

```
           High recall
               ↑
               │                      ● Brute-force (always 1.0, always slow)
               │
               │         ● HNSW high ef_search
               │
               │   ● HNSW default
               │
               │  ● HNSW low ef_search
               │
               └─────────────────────────────→ High speed
```

For most RAG pipelines, **Recall@10 ≥ 0.90** with query latency under 50ms is the practical target.

---

## The `vector_cosine_ops` Operator Class

```sql
USING hnsw (embedding vector_cosine_ops)
```

This tells pgvector which distance function to use when building and querying the index.

| Operator class | Distance metric | Use when |
|---|---|---|
| `vector_cosine_ops` | Cosine distance (1 − cosine similarity) | Embeddings (normalised or unnormalised) |
| `vector_l2_ops` | Euclidean distance (straight-line) | Raw feature vectors |
| `vector_ip_ops` | Inner product (negative dot product) | Normalised embeddings only |

Your embedding scripts all use `normalize=True` — vectors have unit length. For unit vectors, cosine similarity equals dot product, so `vector_cosine_ops` and `vector_ip_ops` give identical results. `vector_cosine_ops` is the safest default regardless.

```sql
embedding <=>  query_vector   -- cosine distance     (use with vector_cosine_ops)
embedding <->  query_vector   -- euclidean distance   (use with vector_l2_ops)
embedding <#>  query_vector   -- negative dot product (use with vector_ip_ops)
```

---

## A Complete Example: End-to-End RAG Query

```
User: "What was the revenue growth in Q3?"

Step 1: Embed the query
  query_vector = model.encode("What was the revenue growth in Q3?")
  → [0.12, -0.34, 0.88, ..., 0.41]

Step 2: Vector search in pgvector
  SELECT content, 1 - (embedding <=> query_vector::vector) AS similarity
  FROM public.document_chunks
  ORDER BY embedding <=> query_vector::vector
  LIMIT 5;

  HNSW internally:
    → Enter graph at top layer entry point (e.g. v7 — the lucky high roller)
    → Greedily hop toward query vector through upper layers
    → Descend to layer 0, do thorough local search
    → Return 5 nearest vectors found

Step 3: Retrieved chunks:
  0.94  "Q3 revenue grew 12% year-on-year, driven by Asia-Pacific..."
  0.91  "Asia-Pacific segment contributed $2.3B in Q3, up from..."
  0.88  "Revenue targets for Q3 were set at $8.1B globally..."
  0.72  "Quarterly earnings call transcript, Q3 2024..."
  0.69  "FY2024 guidance revised upward following Q3 results..."

Step 4: LLM answers using retrieved chunks as context
  "Revenue grew 12% year-on-year in Q3, driven by strong
   Asia-Pacific performance which contributed $2.3B..."
```

---

## Summary

| Concept | One-line explanation |
|---|---|
| **KNN search** | Find the K vectors closest in meaning to a query vector |
| **ANN search** | Find *close enough* results fast by trading a little accuracy for a lot of speed |
| **HNSW** | Multi-layer navigable graph — hop through it top-down to find nearest neighbours |
| **Layer 0** | Every vector, always — the dense precision layer |
| **Layer 1+** | Random subset — sparse navigation layers for fast long-range travel |
| **`r`** | A random float; its only job is deciding layer promotion — knows nothing about the vector's content |
| **`layer_max`** | The highest layer a vector lives in — computed as `int(-ln(r) × mL)` |
| **`m`** | Fixed config parameter: how many edges each vector gets per layer (default 16) |
| **`ef_construction`** | How many candidates considered when finding the m best neighbours at build time |
| **`ef_search`** | How many candidates tracked during query traversal — tunable without rebuilding |
| **Recall@K** | Fraction of the true top-K nearest neighbours the index actually returned |
| **`vector_cosine_ops`** | Use cosine distance — right choice for L2-normalised embeddings |
