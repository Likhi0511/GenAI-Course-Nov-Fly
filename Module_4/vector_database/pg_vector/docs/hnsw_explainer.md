# HNSW — The Graph-Based Vector Index
### How pgvector Searches Millions of Vectors Using Hierarchical Navigable Small Worlds

---

## Reading Guide

This document builds HNSW from the ground up — starting with why brute-force search fails, then explaining how HNSW is structured, how it gets built, and finally how a query actually travels through it. Each section depends on the one before it, so the order matters.

```
Part 1 — The Problem     : Why brute-force search fails at scale
Part 2 — The Structure   : What the multi-layer graph looks like
Part 3 — Building        : How vectors get inserted and connected (m, ef_construction)
Part 4 — Searching       : How a query travels through the graph (ef_search)
Part 5 — Measuring       : What recall means and why < 1.0 is acceptable
Part 6 — Configuration   : Operator classes, end-to-end example, summary
```

---

## Part 1 — The Problem: Why Brute-Force Search Fails

After loading your embeddings into pgvector, every RAG query boils down to one operation:

> *"Given this query vector, find the K chunks whose vectors are closest to it."*

This is called **K-Nearest Neighbour (KNN) search**. The naive approach — compare the query against every single vector in the table — is called **exact search** or **brute-force search**. It is perfectly accurate. It is also painfully slow at scale. Understanding exactly *why* it is slow motivates everything that HNSW does to fix it.

### How the Operation Count Is Calculated

Each brute-force query compares the query vector against **every row**, and each comparison costs one multiply-add per dimension. Cosine similarity is computed as:

```
similarity = Σ (query[i] × chunk[i]) for i in range(dimensions)
```

So for every row you perform `dimensions` multiplications and `dimensions` additions:

```
Row 1: [0.12, -0.34, 0.88, ..., 0.41] ← 384 multiply-adds
Row 2: [0.21, 0.11, 0.55, ..., 0.09] ← 384 multiply-adds
...
Row 1000: [...]                        ← 384 multiply-adds

Total = 1,000 × 384 = 384,000 multiply-add operations
```

| Rows | Dimensions | Dominant cost (rows × dims) | What the table shows |
|---|---|---|---|
| 1,000 | 384 | 384,000 operations | dot products only |
| 100,000 | 384 | 38,400,000 operations | dot products only |
| 10,000,000 | 1536 | 15,360,000,000 operations | dot products only |

> **Note:** These numbers are actually understated. Each query also computes two magnitude values (for cosine normalisation), `rows` division operations, and `rows` comparisons to track the top-K result set. The real operation count is roughly 2× the table — the table shows only the dominant term.

### Three Compounding Factors That Make It Slow

The raw operation count is only part of the problem. Three factors compound on each other to make brute-force truly unworkable at scale.

**1. Memory bandwidth — the real bottleneck**

All vectors must be loaded from RAM into CPU cache *before* any arithmetic happens. The CPU cannot compute similarity on data it hasn't read yet:

```
1,000,000 rows × 1536 dimensions × 4 bytes per float = 6 GB of data
that must move through memory for every single query

Memory bandwidth ≈ 50 GB/s on a typical server
→ 6 GB / 50 GB/s = 0.12 seconds just reading the data
  (before a single multiply-add is done)
```

This means even if all arithmetic were instantaneous, a million-vector query would still take 120ms — just from data movement.

**2. Concurrent queries**

A production RAG system handles many users simultaneously. If 100 users query at once and each query needs 15 billion operations, the database is attempting 1.5 trillion operations per second — no hardware handles that without queuing.

**3. Latency budget**

A typical RAG query has a 200ms end-to-end budget (embed + retrieve + LLM generation). Brute-force at scale consumes the entire budget on retrieval alone before the LLM has started.

### The Real-World Viability Threshold

Combining operation count, memory bandwidth, and latency, the practical limits are:

```
< 10,000 rows     → brute-force is fine, no index needed
10,000–100,000    → borderline, depends on query volume
> 100,000 rows    → index required
```

At a million documents, a brute-force search takes seconds per query. A RAG system needs results in milliseconds. The gap is too large to close with faster hardware alone. The solution is to avoid scanning all vectors entirely — which is exactly what an **Approximate Nearest Neighbour (ANN) index** does.

---

## Part 2 — The Structure: How HNSW Organises Vectors

ANN indexes trade a small amount of accuracy for a massive speedup by only searching a *carefully chosen subset* of vectors. HNSW does this using a navigable graph — and to understand how it searches, you first need to understand what it builds.

### The Social Network Intuition

Think about how information spreads in a social network. If you want to reach someone you don't know, you don't message every person on the platform. You message a friend, who knows someone, who knows someone else — and within a few hops you reach the target. This is the "six degrees of separation" idea.

HNSW builds the same kind of navigable network — not of people, but of vectors. Each vector is a node. Each node is connected by edges to its nearest neighbours. To find the vector closest to a query, you start somewhere in the network and hop to closer and closer nodes until you converge on the answer.

The full name — **Hierarchical Navigable Small World** — describes this structure precisely: it is a graph (*navigable small world*) organised in layers (*hierarchical*).

### The Multi-Layer Graph

The key word in the name is *hierarchical*. HNSW doesn't build one flat graph — it builds **multiple layers**, each covering vectors at different levels of density. Picture it like a map at different zoom levels:

```
Layer 2 (highway network — very few nodes, long-range connections):
  v1 ————————————————— v500 ————————————————— v9000

Layer 1 (main roads — more nodes, shorter connections):
  v1 ——— v50 ——— v200 ——— v500 ——— v700 ——— v9000

Layer 0 (local streets — ALL nodes, shortest connections):
  v1 — v3 — v8 — v12 — ... — v500 — v501 — ... — v9000
```

The top layers act like a highway — they cover large distances quickly with few nodes. Layer 0 is the precision layer — it holds every single vector and is where the final answer is found. A query starts at the top (fast, coarse navigation) and descends to layer 0 (slow, precise search).

Two questions immediately arise: *which vectors end up in the upper layers?* and *how many edges does each vector get?* Part 3 answers both — they are both decided at insert time.

---

## Part 3 — Building the Index: Insertion, Layer Assignment, and Connections

When a new vector is inserted into HNSW, three things happen in sequence:
1. A random number decides which layers the vector lives in
2. At each of those layers, the vector finds its nearest neighbours using its actual content
3. Edges are created to those neighbours

Understanding each step explains why the index behaves the way it does at query time.

### Step 1 — Layer Assignment: One Random Number

When vector `v` arrives to be inserted, the code runs exactly this:

```python
import math, random

r = random.random()                     # Step 1: random float between 0.0 and 1.0
mL = 1.0 / math.log(m)                 # Step 2: normalisation factor derived from m
layer_max = int(-math.log(r) * mL)     # Step 3: the highest layer this vector will live in
```

That single integer `layer_max` determines which layers the vector is inserted into:

```
layer_max = 0 → vector lives in layer 0 only
layer_max = 1 → vector lives in layer 0 AND layer 1
layer_max = 2 → vector lives in layer 0, layer 1, AND layer 2
```

**Every vector always lands in layer 0. No exceptions.** Only some get promoted higher — purely by chance.

### What `r` Is — and What It Is Not

`r = random.random()` is a plain random float. It knows **nothing** about the vector's content. It does not look at the vector's 384 numbers. It does not care what the vector means. It does not prefer "important" or "central" vectors.

`r` is purely a **probabilistic gate** — its only job is to answer: *does this vector get promoted to a higher layer, yes or no?*

The vector's actual content plays **zero role** in deciding which layer it goes to. Content is only used *after* the layer is decided — when finding which neighbours to connect to:

```
New vector v = [0.12, -0.34, 0.88, ..., 0.41]  (384 numbers)

Step 1: r = random() → layer_max = 1   ← content NOT used here
                                           purely random gate

Step 2: insert into layer 1
        → compare v's 384 numbers against existing layer 1 vectors
        → find the m nearest by cosine similarity
        → create edges                 ← content IS used here

Step 3: insert into layer 0
        → compare v's 384 numbers against existing layer 0 vectors
        → find the m nearest by cosine similarity
        → create edges                 ← content IS used here
```

### Why `-ln(r)` Produces the Right Distribution

The formula produces an exponential distribution — most vectors land only in layer 0, very few reach higher layers. Here is the math made visible:

```
r value   -ln(r)   layer_max (m=16, mL=0.36)
─────────  ──────   ───────────────────────────
0.99       0.01     0  ← int(0.004) = 0
0.90       0.11     0  ← int(0.040) = 0
0.50       0.69     0  ← int(0.250) = 0
0.10       2.30     0  ← int(0.830) = 0
0.05       3.00     1  ← int(1.080) = 1  ✓ promoted to layer 1
0.01       4.61     1  ← int(1.660) = 1  ✓ promoted to layer 1
0.002      6.22     2  ← int(2.237) = 2  ✓ promoted to layer 2
0.00005    9.90     3  ← int(3.564) = 3  ✓ promoted to layer 3
```

The `-ln` function stretches small values of `r` into large numbers and compresses large values into small ones. Combined with `int()` truncation, the result is an exponential probability drop-off across layers:

```
For m=16, across 10,000 vectors:
  Layer 0 : all 10,000  (100%)   ← every single vector
  Layer 1 : ~630        (~6.3%)  ← only r < 0.063 produce layer_max ≥ 1
  Layer 2 : ~40         (~0.4%)  ← only r < 0.004 produce layer_max ≥ 2
  Layer 3 : ~2          (~0.02%) ← extremely rare
```

This sparse pyramid is intentional. Upper layers need to be sparse so that each hop covers a large distance. If every vector reached layer 2, the "highway" would just be another dense local graph with no navigational advantage.

### Walking Through 10 Insertions

To make the formula concrete, here is what actually happens as 10 vectors arrive one by one:

```
m = 16, mL = 0.36

Vector  r value   -ln(r)  × mL    int   layer_max  Lives in
──────  ───────   ──────  ──────   ───   ─────────  ────────────────────
v1      0.82      0.20    0.07      0    0          L0
v2      0.67      0.40    0.14      0    0          L0
v3      0.91      0.09    0.03      0    0          L0
v4      0.04      3.22    1.16      1    1          L0, L1
v5      0.55      0.60    0.22      0    0          L0
v6      0.78      0.25    0.09      0    0          L0
v7      0.002     6.21    2.24      2    2          L0, L1, L2
v8      0.44      0.82    0.29      0    0          L0
v9      0.33      1.11    0.40      0    0          L0
v10     0.06      2.81    1.01      1    1          L0, L1

Result after 10 insertions:
  Layer 2: v7            (1 vector)
  Layer 1: v4, v7, v10  (3 vectors)
  Layer 0: v1–v10        (all 10)
```

v7 happened to draw `r = 0.002` — a rare small value — so it was promoted all the way to layer 2. v7 is now the **entry point** for all searches: every future query starts at v7 in layer 2. v7 has no special meaning in terms of content. It just got lucky with the random draw. This entry point role becomes important in Part 4.

### Why Random Assignment Works Better Than Semantic Selection

The random selection feels counterintuitive — surely "important" or "central" vectors should be in the upper layers? Random actually works *better* for a geometric reason.

The upper layers exist purely as **navigation shortcuts** — they let search skip large distances quickly. For shortcuts to work well, upper-layer nodes need to be **evenly spread** across the entire vector space so that any neighbourhood can be reached from any direction:

```
Good upper layer (random — evenly spread):
  ·   ·   ·   ·
    ·   ·   ·
  ·   ·   ·   ·
→ Can navigate to any corner of the space in few hops

Bad upper layer (semantic — most common topics dominate):
  · · · · · · ·  ← all clustered in the dense middle
  · · · · · · ·
→ Edges of the space are poorly connected
```

Random selection naturally gives uniform spatial coverage. Any hand-picked semantic selection would over-represent the most common topics and leave rare regions poorly connected. The randomness is a feature, not a compromise.

### Step 2 — Connections: The `m` Parameter

Once a vector's layers are decided, it needs to be *connected* to its neighbours at each layer. This is where `m` comes in.

`m` controls **how many edges each vector gets at each layer it lives in**. It has nothing to do with the random number `r` — it is a fixed configuration parameter set when the index is created:

```sql
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

The trade-off is straightforward:

```
m = 4  → 4 edges per node  → sparse graph, fewer hops possible → lower recall, very low memory
m = 16 → 16 edges per node → well-connected graph              ← sweet spot (default)
m = 64 → 64 edges per node → very dense graph                  → excellent recall, 4× more memory
```

The default `m=16` comes from the original HNSW research paper — the authors benchmarked across many datasets and found it sits at the sweet spot of speed, recall, and memory for most real workloads.

After inserting v_new with m=16, it connects to its 16 nearest neighbours at each layer. Crucially, connections are **bidirectional** — v_new gets 16 edges out, and each of those 16 neighbours gains an edge back to v_new:

```
Layer 0 after inserting v_new:

  v_003 ←──┐
  v_007 ←──┤
  v_012 ←──┼── v_new  (16 edges total, each to a nearby vector)
  v_019 ←──┤
  v_891 ←──┘  ...
  v_003 also gets an edge pointing back to v_new
```

> **Layer 0 special case:** pgvector doubles the connection count at the base layer to `2m` (so 32 edges for m=16). Layer 0 holds every vector and is where the final precision search happens — the extra connections ensure it stays densely navigable even as the dataset grows.

**Rule of thumb for choosing m:**

| Dataset size | Recommended m |
|---|---|
| < 100K rows | 8 – 16 |
| 100K – 1M rows | 16 – 32 |
| > 1M rows | 32 – 64 |

For a typical document RAG pipeline (tens of thousands of chunks), `m=16` is correct.

### Step 3 — Connection Quality: The `ef_construction` Parameter

Once you know a vector will have `m=16` edges at a given layer, the next question is: *which* 16 neighbours does it connect to? Ideally, the true 16 nearest vectors — but finding them requires a search, and `ef_construction` controls how thorough that search is.

`ef_construction` sets **how many candidates are evaluated before the final `m` neighbours are chosen**. A higher value means a more thorough search — the `m` edges created will be higher quality, producing a better graph that gives higher recall at query time:

```
ef_construction = 32  → considers 32 candidates → picks best 16
                        fast to build, but edges may not be the true nearest
                        lower quality graph → lower recall at query time

ef_construction = 64  → considers 64 candidates → picks best 16  (default)
                        good balance of build speed and edge quality

ef_construction = 200 → considers 200 candidates → picks best 16
                        slow to build, but edges are almost certainly the true nearest
                        highest quality graph → best recall at query time
```

You only pay the build cost once. A higher `ef_construction` is worth it for production indexes.

**Hard rule:** `ef_construction` must always be ≥ `m`. Never set it lower — you'd be asking the algorithm to pick 16 neighbours from fewer than 16 candidates, which is impossible.

### Putting Insertion Together

With layer assignment, edge count, and edge quality all defined, here is the complete sequence when a new vector arrives. Every concept from this part comes together:

```
New vector v  (random draw produced layer_max = 1)
Current top layer of the index = 2
                │
                ▼
TRAVERSE layer 2  — v does NOT get inserted here
  → greedy hop toward v's position in vector space
  → purpose: find a good starting neighbourhood for insertion below
                │
                ▼
ARRIVE at layer 1  (= layer_max — insertion starts here)
  → search ef_construction=64 candidates using v's actual content
  → pick the m=16 nearest as neighbours
  → create bidirectional edges to those 16
                │
                ▼
DESCEND to layer 0
  → search ef_construction=64 candidates
  → pick the 2m=32 nearest (base layer gets double edges)
  → create bidirectional edges to those 32
                │
                ▼
Done — v is permanently wired into the graph at layers 0 and 1
```

The index is now built — every vector is placed, every connection is wired. The question that remains: when a query arrives, how does it actually travel through this structure to find the nearest vectors?

---

## Part 4 — Searching: How a Query Travels Through the Graph

A query does not scan all vectors — that would be brute-force again. Instead it exploits the same layered structure that was built during insertion. The search has two distinct phases that mirror the two-role design of the graph: fast coarse navigation in the upper layers, then precise local search in layer 0.

### The Entry Point

Every query begins at the **same fixed entry point** — the node sitting at the top of the highest layer. From the 10-insertion example in Part 3, that is `v7` in layer 2 — the vector that happened to draw `r = 0.002`.

The entry point is stored in the index metadata. It only changes if a new insertion produces a higher `layer_max` than the current top. Two things follow from this:

- All queries start at the same place — the search is deterministic in starting position
- The entry point has no special semantic meaning — it reached the top layer purely by chance, which as we saw in Part 3, is actually desirable for navigational coverage

### Phase 1 — Greedy Descent Through Upper Layers (Fast Navigation)

In every layer **above layer 0**, the algorithm uses a simple greedy rule: look at all neighbours of the current node, move to whichever is closest to the query, stop when no neighbour is closer than the current position.

```
current_node = entry_node  (e.g. v7 at layer 2)

repeat:
    examine all m=16 neighbours of current_node
    find the neighbour closest to the query vector
    if that neighbour is closer → move to it
    if no neighbour is closer  → stop (local minimum)

descend one layer, repeat from the stopping node
```

The goal of Phase 1 is **not** to find the answer — it is to arrive at a good neighbourhood in layer 0 as quickly as possible. Because upper layers are sparse (only ~40 nodes at layer 2 for 10,000 vectors), each hop covers enormous distances. A few hops get us close with very little work:

```
Query: [0.12, -0.34, 0.88, ...]

Layer 2 (entry: v7)
  v7 neighbours: v1, v500, v9000
  v1    distance: 0.82  ← farther
  v500  distance: 0.31  ← closer → move to v500
  v9000 distance: 0.74  ← farther
  No improvement from v500 → stop

Layer 1 (enter at v500)
  v500 neighbours: v50, v200, v700, ...
  v700  distance: 0.18  ← closest → move to v700
  No improvement from v700 → stop

→ v700 is handed off to Phase 2 as the layer 0 entry point
```

Two layers, roughly 32 distance comparisons total. Phase 1 is done.

### Phase 2 — Beam Search in Layer 0 (Precise Search)

Layer 0 is where all vectors live and where precision is needed. The greedy single-node approach used in Phase 1 would get stuck at local minima here — it could miss the true nearest neighbour because a slightly farther node leads to much better results if explored further.

Instead, Phase 2 uses **beam search**: rather than tracking a single current node, it tracks a list of the best `ef_search` candidates simultaneously and expands them all:

```
ef_search = 40  (default — configured with: SET hnsw.ef_search = 40)

Enter layer 0 at v700
Initialise candidate list : [v700]
Initialise result set      : [v700]

while candidate list is not empty:
    take the closest unvisited candidate → call it C
    examine all 2m=32 neighbours of C in layer 0
    for each neighbour N:
        if N is closer than the furthest node in result set:
            add N to candidate list
            add N to result set
            if result set size > ef_search: drop the furthest
    mark C as visited

When no candidate can improve the result set → stop
Return the top K from the result set
```

The beam expands outward from v700, pulling in closer and closer nodes, pruning anything that falls outside the top `ef_search` at each step. It converges naturally — once the frontier of candidates cannot beat the worst node already in the result set, the search terminates.

```
ef_search = 40 means:
  → tracking 40 best candidates simultaneously
  → exploring each candidate's 32 neighbours
  → continuously pruning anything outside the top 40

Final result set holds the 40 best nodes found
Return the top K from those 40  (e.g. LIMIT 5 → return the 5 closest)
```

### Why Phase 1 is Greedy but Phase 2 is Beam Search

The two phases use different strategies for the same underlying reason: the structure of each layer demands it.

| Phase | Layer | Strategy | Why |
|---|---|---|---|
| Phase 1 | Upper layers (≥1) | Greedy, single-node | Very few nodes — any path gets close quickly, precision not needed |
| Phase 2 | Layer 0 | Beam search, `ef_search` candidates | All vectors present — greedy gets stuck, must explore multiple paths |

The handoff between them — the entry point into layer 0 — is what makes the overall search efficient. Phase 1 delivers a starting point that is already in the right neighbourhood; Phase 2 does the careful local work from there rather than from a random position.

### The `ef_search` Parameter: Tuning the Trade-off

`ef_search` is the only search parameter that can be changed without rebuilding the index — it is a session-level setting:

```sql
SET hnsw.ef_search = 40;    -- default
SET hnsw.ef_search = 10;    -- faster, lower recall
SET hnsw.ef_search = 200;   -- slower, higher recall
```

What it controls is the size of the beam in Phase 2 — how many candidates are tracked simultaneously in layer 0:

```
ef_search = 10
  → beam tracks 10 candidates → small neighbourhood explored
  → fast, but may miss true nearest neighbours → lower recall

ef_search = 40  (default)
  → beam tracks 40 candidates → good balance of coverage and speed

ef_search = 200
  → beam tracks 200 candidates → very thorough local search
  → near-brute-force quality in the neighbourhood → high recall, slower
```

One hard rule: **`ef_search` must always be ≥ K** (the number of results you are requesting). If you run `LIMIT 5` but `ef_search = 3`, the beam only ever tracked 3 candidates — it cannot produce 5 meaningful results.

Because `ef_search` is per-session, you can tune it per query type without touching the index:

```sql
-- High-stakes query: maximise recall
SET hnsw.ef_search = 100;
SELECT content FROM document_chunks
ORDER BY embedding <=> $query LIMIT 5;

-- Real-time query: minimise latency
SET hnsw.ef_search = 20;
SELECT content FROM document_chunks
ORDER BY embedding <=> $query LIMIT 5;
```

### Full Query Trace: Both Phases Together

```
Query vector q = [0.12, -0.34, 0.88, ...]
K = 5  (LIMIT 5),  ef_search = 40

───────────────────────────────────────────────────
PHASE 1  ·  Navigate upper layers  ·  Fast
───────────────────────────────────────────────────

Layer 2:  start at v7 (entry point)
          check v7's 16 neighbours → closest is v500
          move to v500
          check v500's 16 neighbours → no improvement
          stop at v500

Layer 1:  enter at v500
          check v500's 16 neighbours → closest is v700
          move to v700
          check v700's 16 neighbours → no improvement
          stop at v700

          → v700 handed off to Phase 2

───────────────────────────────────────────────────
PHASE 2  ·  Beam search in layer 0  ·  Precise
───────────────────────────────────────────────────

Enter at v700, ef_search = 40
Expand frontier, track top-40 candidates
Explore neighbours of neighbours, prune continuously
Converge when no candidate can improve the result set

Result set (top 40 found in the neighbourhood):
  v512  distance 0.06  ← closest
  v389  distance 0.09
  v107  distance 0.12
  v042  distance 0.15
  v601  distance 0.17  ← 5th closest
  v891  distance 0.18
  ...  (35 more explored but outside final top 5)

───────────────────────────────────────────────────
Return top 5:  v512, v389, v107, v042, v601
───────────────────────────────────────────────────
```

### Why This Is Fast: The Complexity Picture

```
Phase 1 (upper layers):
  O(log N) hops × m=16 comparisons per hop → very cheap

Phase 2 (layer 0):
  ef_search candidates × 2m=32 neighbours each
  → cost is bounded by ef_search, not by N

Total per query:
  O(log N × m  +  ef_search × m)

Compare to brute-force:
  O(N × dimensions)
```

For 1,000,000 vectors with m=16, ef_search=40, 1536 dimensions:

```
HNSW:        (20 × 16) + (40 × 32) × 1536 ≈ 2,000,000 operations
Brute-force: 1,000,000 × 1536             ≈ 1,500,000,000 operations
```

That is a **750× reduction in work** per query — which is why a brute-force query taking seconds becomes a sub-10ms query with HNSW.

The logarithmic behaviour of Phase 1 comes from the "small world" property introduced in Part 2: because upper-layer membership is random and exponentially sparse, any node can be reached from any other in O(log N) hops. This is the formal guarantee that makes HNSW scale to millions of vectors without degrading.

---

## Part 5 — Measuring: What "Recall" Actually Means

HNSW is fast precisely because it skips most vectors. The cost of that skip is that it might occasionally miss one of the true nearest neighbours — returning the 6th-closest result instead of the 5th. Recall is the metric that quantifies how often this happens.

### The Definition

> **Recall** = the fraction of the true nearest neighbours that the approximate index actually returns.

"True nearest neighbours" means what a perfect brute-force search would have returned. Recall is measured by comparing HNSW's output against that ground truth:

```
           results returned that were in the true top-K
Recall@K = ───────────────────────────────────────────
                               K
```

### A Concrete Example

Say you query for the top-5 most similar chunks. Brute-force would return:

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
Approximate top-5:
  chunk_042  ✓  (rank 1 — correct)
  chunk_107  ✓  (rank 2 — correct)
  chunk_389  ✓  (rank 3 — correct)
  chunk_012  ✓  (rank 4 — correct)
  chunk_891  ✗  (not in ground truth — missed chunk_601)

Recall@5 = 4 correct out of 5 = 0.80  (80%)
```

### The @K Notation

| Notation | Meaning |
|---|---|
| Recall@1 | Did the index return the single closest vector? |
| Recall@5 | Of the 5 results returned, how many were in the true top-5? |
| Recall@10 | Of the 10 results returned, how many were in the true top-10? |

Higher K is usually easier to achieve — more slots means fewer misses matter. Recall@10 is almost always higher than Recall@1 for the same index settings.

### Typical Values in Practice

| Index | Typical Recall@10 |
|---|---|
| Brute-force (exact) | 1.00 — always perfect |
| HNSW (default settings) | 0.95 – 0.99 |
| HNSW (low `ef_search`) | 0.85 – 0.92 |

### Why Recall < 1.0 Is Acceptable for RAG

In the example above, HNSW missed `chunk_601` (similarity 0.83) and returned `chunk_891` (similarity ~0.82) instead — the two are nearly identical in relevance. An LLM generating an answer from these 5 chunks will produce the same response either way.

**The scenario where low recall actually hurts** is when the only chunk containing the answer falls outside what `ef_search` can reach in Phase 2. If the answer lives in `chunk_601` (rank 5) and `ef_search` is too low to find it, you will miss it entirely. This connects directly back to Part 4: increasing `ef_search` expands the beam in Phase 2, which raises recall at the cost of more comparisons. The two knobs — speed and accuracy — are one and the same knob.

### The Speed–Recall Trade-off

```
High recall
  ↑
  │  ● Brute-force (always 1.0, always slow)
  │
  │  ● HNSW ef_search=200
  │
  │  ● HNSW ef_search=40 (default)
  │
  │  ● HNSW ef_search=10
  │
  └──────────────────────────────→ High speed
```

For most RAG pipelines, **Recall@10 ≥ 0.90** with query latency under 50ms is the practical target. Default settings (`m=16, ef_construction=64, ef_search=40`) typically deliver Recall@10 ≈ 0.97 at well under 10ms for datasets up to a few million rows.

---

## Part 6 — Configuration and Putting It All Together

### The `vector_cosine_ops` Operator Class

When creating the index, you specify which distance function HNSW uses for all comparisons — both at build time (connecting neighbours) and at query time (traversing the graph):

```sql
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

| Operator class | Distance metric | Use when |
|---|---|---|
| `vector_cosine_ops` | Cosine distance (1 − cosine similarity) | Embeddings (normalised or unnormalised) |
| `vector_l2_ops` | Euclidean distance (straight-line) | Raw feature vectors |
| `vector_ip_ops` | Inner product (negative dot product) | Normalised embeddings only |

For embedding-based RAG, `vector_cosine_ops` is the right choice. The query operator must match the index operator class or the index will not be used:

```sql
embedding <=> query_vector  -- cosine distance     → use with vector_cosine_ops
embedding <-> query_vector  -- euclidean distance  → use with vector_l2_ops
embedding <#> query_vector  -- negative dot product → use with vector_ip_ops
```

If your embeddings are L2-normalised (`normalize=True`), cosine similarity equals dot product — so `vector_cosine_ops` and `vector_ip_ops` give identical results. `vector_cosine_ops` is the safer default because it works correctly even when vectors are not normalised.

### HNSW vs Other Indexes: When to Use It

```
Build time  : Slower (more time + memory than IVFFlat)
Memory      : Higher (full graph must fit in RAM for best performance)
Query speed : Faster than IVFFlat
Recall      : Higher than IVFFlat at the same speed setting
Inserts     : Handled natively — no reindex needed
Best for    : Production RAG, quality-critical retrieval, growing datasets
```

The main reason to choose HNSW over alternatives is that it handles **new inserts natively** — each new vector is wired into the existing graph at insert time without rebuilding anything. IVFFlat requires periodic reindexing as new data arrives, making it awkward for datasets that grow continuously, which is most production RAG pipelines.

### End-to-End RAG Query Example

Everything from Parts 1–6 comes together in a single query:

```
User: "What was the revenue growth in Q3?"

Step 1 — Embed the query
  query_vector = model.encode("What was the revenue growth in Q3?")
  → [0.12, -0.34, 0.88, ..., 0.41]

Step 2 — Search pgvector
  SELECT content, 1 - (embedding <=> query_vector::vector) AS similarity
  FROM public.document_chunks
  ORDER BY embedding <=> query_vector::vector
  LIMIT 5;

  What HNSW does internally:

  Phase 1: Enter graph at v7 (top-layer entry point, set at index build time)
           Greedy hop through layer 2 → layer 1
           Arrive at v700 as layer 0 entry point
           (~32 comparisons total)

  Phase 2: Beam search in layer 0 from v700
           Track top ef_search=40 candidates
           Expand frontier, prune continuously
           Converge on the nearest neighbourhood
           (~1,280 comparisons total)

  Total work: ~1,300 comparisons vs 1.5 billion for brute-force

Step 3 — Retrieved chunks (with similarity scores)
  0.94  "Q3 revenue grew 12% year-on-year, driven by Asia-Pacific..."
  0.91  "Asia-Pacific segment contributed $2.3B in Q3, up from..."
  0.88  "Revenue targets for Q3 were set at $8.1B globally..."
  0.72  "Quarterly earnings call transcript, Q3 2024..."
  0.69  "FY2024 guidance revised upward following Q3 results..."

Step 4 — LLM generates answer from retrieved context
  "Revenue grew 12% year-on-year in Q3, driven by strong Asia-Pacific
   performance which contributed $2.3B..."
```

---

## Summary

### Parameter Quick Reference

| Parameter | Set at | Controls | Rule of thumb |
|---|---|---|---|
| `m` | Index creation | Edges per node per layer | 16 for most RAG pipelines; raise for >1M rows |
| `ef_construction` | Index creation | Candidates considered when wiring edges | Always ≥ m; 64 default, 200 for production |
| `ef_search` | Query time | Candidates tracked in layer 0 beam search | Always ≥ K; raise for high-stakes queries |

### Concept Reference

| Concept | One-line explanation |
|---|---|
| **KNN search** | Find the K vectors closest in meaning to a query vector |
| **Brute-force** | Compare query against every vector — exact but O(N × dims), too slow at scale |
| **ANN search** | Find *close enough* results fast by trading a little accuracy for a lot of speed |
| **HNSW** | Multi-layer navigable graph — descend from coarse to precise to find nearest neighbours |
| **Layer 0** | Every vector, always — the dense precision layer where Phase 2 runs |
| **Layer 1+** | Random sparse subset — highway layers where Phase 1 navigates |
| **`r`** | Random float at insert time; decides layer promotion — knows nothing about vector content |
| **`layer_max`** | Highest layer a vector lives in — computed as `int(-ln(r) × mL)` |
| **Entry point** | The node at the top of the highest layer — fixed starting point for all queries |
| **Phase 1** | Greedy single-node descent through upper layers — fast coarse navigation to a good neighbourhood |
| **Phase 2** | Beam search with `ef_search` candidates in layer 0 — thorough local search for the final answer |
| **Recall@K** | Fraction of true top-K nearest neighbours the index actually returned |
| **`vector_cosine_ops`** | Use cosine distance — correct choice for L2-normalised embeddings |