# Understanding Embeddings
### From Words to Numbers — A Guide for Everyone

---

## The Problem: Computers Don't Understand Language

Before we talk about embeddings, let's understand the problem they solve.

Computers are fundamentally number machines. They can compare numbers, sort numbers, calculate distances between numbers. What they **cannot** do — natively — is understand that the word *"happy"* is closer in meaning to *"joyful"* than it is to *"car"*.

If you encode words naively — say, A=1, B=2, C=3 — then:
- "cat" → [3, 1, 20]
- "dog" → [4, 15, 7]
- "automobile" → [1, 21, 20, 15, 13, 15, 2, 9, 12, 5]

These numbers tell a computer nothing about meaning. According to this scheme, "cat" and "automobile" might look similar just because they share the letter 'A'. This is useless.

**The core question embeddings answer is:**

> *How do we represent meaning as numbers so that things with similar meanings get similar numbers?*

---

## The Intuition: A Map of Meaning

Imagine you're creating a map — not of geography, but of **concepts**.

On this map:
- "king" and "queen" are placed close together
- "happy", "joyful", "elated" form a tight cluster
- "Paris" and "France" are nearby, just like "Tokyo" and "Japan"
- "bank" (financial) sits in a completely different neighborhood from "bank" (river bank)

An **embedding** is exactly this: a set of coordinates on a map of meaning.

Instead of a 2D map (latitude, longitude), this map has **hundreds of dimensions** — typically 384, 768, 1024, or 1536. Each dimension captures some aspect of meaning that linguists might not even be able to name, but that the model has learned from reading billions of sentences.

Each word or piece of text gets a **vector** — a list of numbers representing its coordinates on this map.

```
"happy"   → [0.21, -0.54, 0.88, 0.03, -0.17, ..., 0.62]  ← 384 numbers
"joyful"  → [0.19, -0.51, 0.90, 0.01, -0.19, ..., 0.65]  ← very close!
"car"     → [0.73,  0.12, -0.34, 0.88, 0.41, ..., -0.22]  ← far away
```

The closer two vectors are on this map, the more similar their meaning.

---

## A Concrete Analogy: Describing Movies

Suppose you wanted to describe movies with numbers so that similar movies end up close together.

You might invent three dimensions:

| Dimension | Low (0) | High (1) |
|---|---|---|
| Action level | Slow, dialogue-heavy | High-speed, explosive |
| Seriousness | Light comedy | Dark/serious |
| Time period | Contemporary | Historical/futuristic |

Now you can place movies on this 3D map:

| Movie | Action | Serious | Historical | Coordinates |
|---|---|---|---|---|
| The Dark Knight | 0.8 | 0.9 | 0.1 | [0.8, 0.9, 0.1] |
| Batman v Superman | 0.8 | 0.85 | 0.1 | [0.8, 0.85, 0.1] |
| Paddington 2 | 0.2 | 0.1 | 0.3 | [0.2, 0.1, 0.3] |
| Gladiator | 0.75 | 0.8 | 0.95 | [0.75, 0.8, 0.95] |

The Dark Knight and Batman v Superman are close together. Paddington 2 is far from both. Gladiator is similar in tone to The Dark Knight but far away on the historical axis.

**This is exactly what embedding models do** — except instead of 3 hand-crafted dimensions that humans designed, they learn **hundreds of dimensions automatically** from data, capturing nuances of meaning that no human explicitly programmed.

---

## How Are Embeddings Learned?

Embeddings are not hand-crafted. They are **learned from text**.

The key insight comes from a principle called the **Distributional Hypothesis**:

> *"You shall know a word by the company it keeps."*
> — J.R. Firth, 1957

Words that appear in similar contexts tend to have similar meanings.

- "The dog ran across the yard"
- "The cat ran across the yard"
- "The puppy ran across the yard"

A model that reads millions of sentences like these learns that "dog", "cat", and "puppy" appear in similar surrounding contexts → they should have similar coordinates on the meaning map.

Modern embedding models (like the ones you used in your pipeline) are trained on enormous amounts of text. The training process nudges vectors closer together when the corresponding words appear in similar contexts, and pushes them apart when they don't.

---

## The Math: Measuring Similarity

Once you have embeddings, how do you measure how similar two things are?

The standard answer is **cosine similarity**.

Forget the formula for a moment. Geometrically, it measures the **angle** between two vectors:

```
         ↑
  "joyful" \  ← small angle → similar meaning
              \
               → "happy"


  "car" → ← large angle → different meaning
  
  "happy" ↑
```

- **Angle ≈ 0°** → cosine similarity ≈ 1.0 → nearly identical meaning
- **Angle = 90°** → cosine similarity ≈ 0.0 → unrelated
- **Angle = 180°** → cosine similarity ≈ -1.0 → opposite meaning

In code, this looks like:

```python
import numpy as np

def cosine_similarity(vec_a, vec_b):
    # Dot product divided by the product of magnitudes
    return np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))

similarity = cosine_similarity(embedding_happy, embedding_joyful)
# → 0.94  (very similar)

similarity = cosine_similarity(embedding_happy, embedding_car)
# → 0.12  (very different)
```

> **Note on normalised embeddings:** In your pipeline scripts, all three embedding generators use `normalize=True`. When vectors are L2-normalised (each vector has length = 1), cosine similarity is identical to the dot product. This is why your vector databases can run faster queries — dot product is cheaper to compute than full cosine similarity.

---

## The Famous Arithmetic of Meaning

Here is the result that made the field famous when it was discovered around 2013:

```
embedding("king") - embedding("man") + embedding("woman") ≈ embedding("queen")
```

You can do **arithmetic on meaning**.

- Take the concept "king"
- Subtract the concept "man"  
- Add the concept "woman"
- The result lands closest to "queen" on the meaning map

More examples:

```
embedding("Paris") - embedding("France") + embedding("Germany") ≈ embedding("Berlin")
embedding("walked") - embedding("walk") + embedding("run") ≈ embedding("ran")
embedding("doctor") - embedding("man") + embedding("woman") ≈ embedding("nurse")
```

This works because the embedding space has learned to encode **relationships** as consistent directions:

- The "capital city of" relationship always points in roughly the same direction
- The "past tense of" relationship always points in roughly the same direction
- The "feminine version of" relationship always points in roughly the same direction

The embedding space is not random — it has **geometric structure** that mirrors the structure of language and the world.

---

## From Words to Chunks: Document Embeddings

In your pipeline, you are not embedding individual words. You are embedding entire **chunks of text** — paragraphs extracted from PDFs.

The same principle applies, just at a larger scale. A chunk about "quarterly revenue growth in Asia-Pacific markets" will end up in a region of the meaning map surrounded by other chunks about financial performance, geographic markets, and business metrics.

This is how your RAG (Retrieval-Augmented Generation) system works at query time:

```
User query: "What was the revenue growth in Q3?"
     ↓
Embed the query → get a vector
     ↓
Find the chunks whose vectors are closest to the query vector
     ↓
Return those chunks as context to the LLM
     ↓
LLM generates an answer grounded in the retrieved text
```

The embedding step turns a vague semantic question into a precise geometric search: *"find me the points on the meaning map that are nearest to this query point."*

---

## Comparing the Three Models You Used

In your pipeline you have three embedding providers. They all do the same job but differ in trade-offs:

### `all-MiniLM-L6-v2` — Sentence Transformers

```
Dimensions : 384
Cost       : Free (runs locally on your machine)
Speed      : Fast
Quality    : Good for most RAG use cases
Download   : ~80 MB one-time
```

**When to use:** Development, experimentation, budget-constrained production, or when data cannot leave your environment. No API calls, no cost, works offline after the initial download.

**How it works locally:**
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')
embedding = model.encode("quarterly revenue grew 12% year-on-year")
# → numpy array of 384 floats, computed on your CPU/GPU
```

---

### `text-embedding-3-small` — OpenAI

```
Dimensions : 1536
Cost       : $0.020 per 1 million tokens
Speed      : Fast (API call)
Quality    : Excellent
Download   : Nothing — model lives on OpenAI's servers
```

**When to use:** Production systems where retrieval quality matters and cost is secondary. The 1536 dimensions give the model more "room" to represent nuanced meaning — better at distinguishing subtle differences between similar documents.

**Key difference from Sentence Transformers:**
- Your text leaves your environment (sent to OpenAI's API)
- No GPU or local compute required
- Costs money at scale (but small — 50,000 pages ≈ $1)

---

### `amazon.titan-embed-text-v2` — AWS Bedrock

```
Dimensions : 256 / 512 / 1024  (you choose)
Cost       : $0.0001 per 1K tokens (~6x cheaper than OpenAI)
Speed      : Slower (one API call per chunk — no batching)
Quality    : Good, especially for enterprise/multilingual
Download   : Nothing — model lives on AWS
```

**When to use:** AWS-native deployments where everything already lives in AWS (S3, RDS, OpenSearch). Stays within your existing AWS security perimeter — IAM roles, VPC, CloudTrail logging. Best choice for regulated industries (healthcare, finance) where data governance requires everything to stay within AWS.

**Key limitation:** Titan processes one text at a time. OpenAI can embed 2048 texts in a single call. For 10,000 chunks, this makes Titan noticeably slower.

---

### Side-by-Side Comparison

| | Sentence Transformers | OpenAI | Bedrock Titan |
|---|---|---|---|
| **Dimensions** | 384 | 1536 | 256 / 512 / 1024 |
| **Cost** | Free | $0.020 / 1M tokens | $0.0001 / 1K tokens |
| **Data leaves your machine?** | No | Yes (→ OpenAI) | Yes (→ AWS) |
| **Batching** | Yes | Yes (2048/call) | No (1/call) |
| **Best for** | Dev / privacy / budget | Quality-first production | AWS-native / regulated |
| **Languages** | English-focused | Multilingual | 100+ languages |

---

## Dimensions: Does More Always Mean Better?

You might wonder: if 384 dimensions is good, is 3072 always better?

Not necessarily.

More dimensions mean:
- The model can encode more nuanced differences in meaning ✓
- Each vector takes more memory to store ✓ (costs more in a vector DB)
- Similarity search is slower (more numbers to compare) ✗
- Marginally higher cost per embedding ✗

For most RAG applications, **384–1024 dimensions is sufficient**. The retrieval quality difference between 384 and 1536 is real but often smaller than the difference between good and bad chunking strategy.

The biggest quality lever in your pipeline is not which embedding model you choose — it is **how you chunk the text** upstream.

---

## Why L2 Normalisation Matters

All three of your embedding scripts use normalisation (`normalize=True` or `normalize_embeddings=True`).

Without normalisation, two vectors can look dissimilar just because one is longer (higher magnitude) than the other — even if they point in the same direction.

```
Vector A = [0.2, 0.4]      magnitude = 0.45
Vector B = [2.0, 4.0]      magnitude = 4.47

Direction: identical (both point at 63.4°)
Dot product: 2.0  ← misleadingly large due to B's magnitude
```

After L2 normalisation, every vector is scaled to have magnitude = 1. Now:
- Direction is the only thing that matters
- Dot product = cosine similarity (cheaper to compute)
- All vectors live on the surface of a unit sphere

This is why your code passes `normalize=True` — it is a free quality improvement that also speeds up the vector database.

---

## What the Output JSON Actually Contains

After running any of your three embedding scripts, each chunk in the output file looks like this:

```json
{
  "content": "Revenue grew 12% year-on-year driven by Asia-Pacific expansion...",
  "metadata": {
    "entities": { "MONEY": ["12%"], "GPE": ["Asia-Pacific"] },
    "key_phrases": ["revenue growth", "Asia-Pacific expansion", ...],
    "monetary_values": ["$5.5M"]
  },
  "embedding": [
    0.0521, -0.1832, 0.4401, 0.0073, -0.2190, 0.3812, ...
    ... 384 (or 1024, or 1536) numbers total ...
  ],
  "embedding_metadata": {
    "model": "all-MiniLM-L6-v2",
    "dimensions": 384,
    "normalized": true,
    "generated_at": "2025-01-15T10:23:45"
  }
}
```

The `embedding` array is the coordinate of this chunk on the meaning map. Every other field — the original text, the entities, the key phrases — travels alongside it so that when the vector database retrieves this chunk, your application gets everything it needs to construct an answer, not just a list of numbers.

---

## The Full Pipeline in Context

Your three embedding scripts are step 3 of a four-step pipeline:

```
PDF / Document
     ↓
[1] Docling Extraction
     → Structured chunks (text, tables, images) with boundary markers
     ↓
[2] Meta-Enrichment (Bedrock / OpenAI)
     → Adds: PII redaction, named entities, key phrases, monetary values
     ↓
[3] Embedding Generation  ← you are here
     → Adds: dense vector representation of each chunk's meaning
     ↓
[4] Vector Database Ingestion (pgvector / Pinecone / OpenSearch)
     → Enables: semantic search, RAG retrieval, similarity clustering
```

The embedding step is the bridge between the **symbolic world** (text, entities, metadata) and the **geometric world** (vectors, distances, nearest-neighbour search).

Without embeddings, you can only search for exact keyword matches.  
With embeddings, you can search for **meaning**.

---

## Common Misconceptions

**"The embedding is the meaning."**  
Not quite. The embedding is a *representation* of meaning in the context of the model that produced it. Embeddings from different models are not compatible — you cannot mix Sentence Transformer vectors with OpenAI vectors in the same index.

**"Higher dimensions always win."**  
Diminishing returns set in quickly. The jump from 384 → 768 often matters; the jump from 1536 → 3072 rarely does for standard document retrieval.

**"One embedding per document."**  
Usually wrong for RAG. A 50-page report should be split into many chunks, each embedded separately. Embedding the whole document produces a single vector that averages everything out — it will be mediocre at retrieving any specific fact.

**"Embeddings understand the content."**  
They capture statistical patterns learned from training data. A model trained mostly on English will produce poor embeddings for Hindi. A model trained on general web text may struggle with highly specialised medical or legal terminology. Model choice matters when your domain is specialised.

---

## Summary

| Concept | One-line explanation |
|---|---|
| **Embedding** | A list of numbers representing the meaning of a piece of text |
| **Vector** | The technical name for that list of numbers |
| **Dimensions** | How many numbers are in the list (384, 1024, 1536, etc.) |
| **Cosine similarity** | A measure of how similar two meanings are (0 = unrelated, 1 = identical) |
| **Normalisation** | Scaling all vectors to the same length so direction is all that matters |
| **Semantic search** | Finding chunks by meaning rather than by keyword matching |
| **RAG** | Using retrieved chunks as context so an LLM can answer questions about your documents |
| **Vector database** | A database optimised for storing and searching embeddings |

---

*The three scripts in your pipeline — `sentence_transformers_embeddings.py`, `openai_embeddings.py`, and `bedrock_titan_embeddings.py` — all do the same thing: take a chunk's `content` field and replace it with a coordinate on the map of meaning. Everything else in the pipeline exists to make sure those coordinates are as accurate and useful as possible.*
