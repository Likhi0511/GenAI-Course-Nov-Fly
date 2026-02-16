# IVFFlat — The Cluster-Based Vector Index
### How pgvector Searches Millions of Vectors Using k-Means Clustering

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

Modern CPUs can do ~10 billion floating-point operations per second, so the raw multiply-add count alone does not tell the whole story. Three things compound to make brute-force unacceptable at scale:

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

## IVFFlat — The Postal District Approach

### The Intuition

Imagine you're trying to find the nearest pizza restaurant to your house. The brute-force approach: check every restaurant in the country. Obviously wasteful — you don't need to check restaurants in another city.

A smarter approach: divide the country into **postal districts**. First find which district you're in, then only search within that district and maybe the ones bordering it.

IVFFlat works exactly like this — but for vectors.

### How It Works: Step by Step

**Phase 1: Build time (when you CREATE INDEX)**

```
All your chunk vectors:
  [v1, v2, v3, v4, ... v10000]
         ↓
Run k-means clustering (find natural groupings)
         ↓
Assign every vector to its nearest cluster centre
         ↓
Result: 100 clusters (or however many "lists" you specified)

  Cluster 1 (financial reports): [v12, v45, v891, ...]
  Cluster 2 (product specs):     [v3,  v17, v203, ...]
  Cluster 3 (customer emails):   [v8,  v99, v441, ...]
  ...
```

The cluster centres are called **centroids** — the "average location" of each cluster.

---

### But Wait — How Does k-Means Actually Find Those Clusters?

k-means has **no labels, no categories, no human guidance**. It finds groupings purely from the **geometry of the vectors** — which ones happen to sit close together in the high-dimensional space.

Here is exactly what it does, step by step.

---

**Step 1 — Place random starting centroids**

k-means begins by randomly dropping `k` points anywhere in the vector space. `k` is the `lists` value you specified.

```
Your vectors scattered in space (shown in 2D for simplicity):

    ·  ·  ·         ·  ·
       ·      ·  ·        ·
  ·       ·       ·    ·
       ·    ·  ·     ·
                ·  ·    ·
                     ·    ·
```

```
Step 1: Drop 3 centroids ★ at random positions — pure guesses:

    ·  ·  ·    ★    ·  ·
       ·      ·  ·        ·
  ·       ·       ·    ·
       ·    ·  ·     ·
         ★      ·  ·    ·
                     ·  ★ ·
```

---

**Step 2 — Assign every vector to its nearest centroid**

Every vector measures its distance to all 3 centroids and joins whichever is geometrically closest.

```
    A  A  A    ★A   A  A
       A      A  A        A
  B       B       B    B
       B    B  B     B
         ★B     C  C    C
                     C  ★C C
```

The clusters look messy at this point — they're based on random starting positions, not real structure.

---

**Step 3 — Move each centroid to the true average of its group**

Calculate the **mean position** of all vectors currently assigned to each centroid. Move the centroid to that average. This is the literal meaning of "k-**means**".

```
After moving centroids to the average position of their assigned vectors:

    A  A  A         A  A
       A      A  A        A
  B       B    ★A    B    B      ← ★A moved toward the dense A cluster
       B    B  ★B  B             ← ★B moved toward the centre of B cluster
                  C  C    C
                       ★C  C     ← ★C moved toward the C cluster
```

---

**Step 4 — Reassign and repeat until nothing changes**

With centroids in new positions, some vectors are now closer to a different centroid. Reassign them, recompute means, move centroids again. Repeat until no vector switches cluster — the algorithm has **converged**.

```
Iteration 2 — some vectors switch cluster as centroids settle:

    A  A  A         A  A
       A      A  ★A       A
  B       B           B    B
       B    B  ★B  B
                  C  C    C
                  C   ★C  C

Iteration 3 — nothing moves → DONE ✓
```

---

**The result: meaningful clusters nobody programmed**

k-means converged on groupings that reflect the actual geometry of your data. Vectors with similar meanings ended up close together because the **embedding model** placed them close together upstream. k-means just found the natural neighbourhoods that already existed.

The labels "financial reports" and "product specs" are our human interpretation *after the fact*. k-means only ever saw numbers.

```
Centroid A ≈ average of the "revenue / quarterly / earnings" neighbourhood
Centroid B ≈ average of the "product / specification / features" neighbourhood
Centroid C ≈ average of the "customer / correspondence / email" neighbourhood
```

---

### Why Does k-Means Work on Embeddings But Not Raw Text?

It works because the embedding model did the hard work first. By the time vectors reach k-means:

- Texts about similar topics already sit **close together** in vector space
- Texts about different topics already sit **far apart**
- k-means just needs to draw boundary lines between existing neighbourhoods

If you ran k-means on random numbers, it would find arbitrary clusters with no semantic meaning. It works on embeddings because embeddings already carry **geometric structure that mirrors meaning**.

---

### One Limitation Worth Knowing

k-means requires you to declare `k` (the number of clusters) in advance. It doesn't figure out the "natural" number on its own. If your data has 7 natural topic groupings but you set `lists=100`, you get 100 clusters that over-split those groups. If you set `lists=3`, you under-split and each cluster becomes too broad to search efficiently.

This is exactly why the `lists ≈ sqrt(total_rows)` rule of thumb exists — it's an empirical guideline that produces clusters that are neither too coarse nor too fine, regardless of how many real topics your data contains.

---

**Phase 2: Query time (when you run a SELECT)**

```
Query vector q = [0.12, -0.34, 0.88, ...]
         ↓
Compare q against all 100 centroids (cheap — only 100 comparisons)
         ↓
Find the nearest centroids (controlled by probes parameter)
         ↓
Search only the vectors inside those clusters
         ↓
Return the top K results
```

Instead of searching 10,000 vectors, you search perhaps 200 — the contents of 2 nearby clusters.

---

## The Key Parameter: `lists`

```sql
CREATE INDEX ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

`lists` = the number of clusters to divide your data into.

**Rule of thumb:** `lists ≈ sqrt(total_rows)`

| Rows | Recommended lists |
|---|---|
| 1,000 | ~32 |
| 10,000 | ~100 |
| 100,000 | ~316 |
| 1,000,000 | ~1,000 |

**Too few lists:** Each cluster is huge → you still search lots of vectors → slow  
**Too many lists:** Clusters are tiny → high chance the answer is in an unsearched cluster → poor recall

---

## The Query-Time Parameter: `probes`

At query time you control how many clusters to search:

```sql
SET ivfflat.probes = 1;   -- search 1 cluster  (fast, less accurate)
SET ivfflat.probes = 10;  -- search 10 clusters (slower, more accurate)
```

Default is 1. For production RAG, `probes = sqrt(lists)` is a good starting point.

```
probes=1     → searches 1% of data   → very fast, ~80% recall
probes=10    → searches 10% of data  → moderate,  ~95% recall
probes=lists → searches 100% of data → same as brute-force
```

---

## The Critical Ordering Rule: Data First, Index Second

```sql
-- WRONG — k-means runs on an empty table → random useless centroids:
CREATE TABLE document_chunks (...);
CREATE INDEX ... USING ivfflat ...;
INSERT INTO document_chunks ...;

-- CORRECT — k-means runs on real data → centroids reflect actual structure:
INSERT INTO document_chunks ...;
CREATE INDEX ... USING ivfflat ...;
```

An index built before data is loaded will have random centroids that are useless for search. Your pipeline always creates the index after `insert_chunks()` — this ordering is intentional.

---

## IVFFlat Summary

```
Build time  : Fast (minutes for millions of rows)
Memory      : Low (stores centroids + cluster assignments)
Query speed : Good
Recall      : ~95% with reasonable probes setting
Best for    : Large datasets, resource-constrained environments,
              datasets that are loaded in bulk and rarely change
```

---

## The Problem with Incremental Inserts

IVFFlat's centroids are **frozen at index build time**. When you insert new vectors after the index is built:

- New vectors get assigned to the nearest existing centroid
- But those centroids were computed on the old data — they may not represent the new data well
- Over time, clusters become unbalanced: some bloated, some nearly empty
- Search recall **silently degrades** — no errors, just worse results

```
Day 1 : Build index on 10,000 chunks → 100 well-balanced clusters
Day 30: 50,000 new chunks inserted incrementally
        → Centroids still reflect Day 1 data
        → New "Q4 earnings" chunks crammed into nearest old cluster
        → Recall quietly drops from 95% → maybe 75%
        → You'd never know without running eval queries
```

### So how do you decide `lists` when rows keep growing?

**Option 1 — Use HNSW instead (recommended)**

HNSW handles incremental inserts natively. Each new vector is wired into the graph at insert time — no reindex ever needed. For any pipeline where documents keep arriving, HNSW is the right choice.

**Option 2 — Set `lists` for your target size, then reindex periodically**

Pick `lists` based on your **expected steady-state size**, not today's count. Then schedule a reindex when data has grown 3–5×.

```sql
-- You have 10,000 chunks today but expect 100,000 eventually
CREATE INDEX ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 316);   -- sqrt(100,000) — your target size, not current size

-- When rows have grown 3-5x, rebuild the index in place:
REINDEX INDEX CONCURRENTLY document_chunks_embedding_idx;
-- CONCURRENTLY keeps the table readable during the rebuild
```

A practical reindex schedule:

| Current rows | Rebuild when you reach |
|---|---|
| 10,000 | ~50,000 rows |
| 100,000 | ~500,000 rows |
| 1,000,000 | ~3,000,000 rows |

**Option 3 — Hot / Cold split for large pipelines**

```
New chunks arriving daily
        ↓
  "Hot" table  → no index (brute-force, small = fast enough)
        ↓
  Nightly job  → move to "Cold" table + rebuild IVFFlat index on full dataset

Query time: search both tables, merge and re-rank results
```

```sql
SELECT content, embedding <=> $1 AS dist FROM hot_chunks
UNION ALL
SELECT content, embedding <=> $1 AS dist FROM cold_chunks
ORDER BY dist
LIMIT 5;
```

### Decision summary

| Scenario | Recommendation |
|---|---|
| Rows grow continuously | **Use HNSW** — handles inserts natively |
| Bulk load once, rarely change | **IVFFlat** with `lists = sqrt(final_expected_rows)` |
| Large scale + daily inserts | **HNSW** or hot/cold split with IVFFlat on cold table |
| Don't know future size | **HNSW** — always the safer default |

---

## Summary

| Concept | One-line explanation |
|---|---|
| **KNN search** | Find the K vectors closest in meaning to a query vector |
| **Exact search** | Compare query against every vector — accurate but slow at scale |
| **ANN search** | Compare query against a smart data structure — fast, ~95-98% accurate |
| **k-means** | Iterative algorithm: randomly place centroids, assign vectors, recompute means, repeat until stable |
| **Centroid** | The average position of all vectors in a cluster — the cluster's "centre of gravity" |
| **Convergence** | When no vector changes cluster on a full pass — k-means is done |
| **IVFFlat** | Cluster vectors first (k-means), then at query time search only the relevant clusters |
| **`lists`** | Number of clusters to create (~√rows is a good default) |
| **`probes`** | How many clusters to search at query time (more = better recall) |
| **Recall** | % of true nearest neighbours correctly found by the approximate search |
| **`vector_cosine_ops`** | Use cosine distance — right choice for L2-normalised embeddings |
