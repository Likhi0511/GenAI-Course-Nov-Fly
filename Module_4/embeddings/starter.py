"""
Sentence Transformer Demo
=========================
Demonstrates: encode(), cosine_similarity, semantic search, and clustering
Install: pip install sentence-transformers
"""

from sentence_transformers import SentenceTransformer, util
import numpy as np

# ─────────────────────────────────────────
# 1. Load Model
# ─────────────────────────────────────────
print("=" * 60)
print("Loading model: all-MiniLM-L6-v2")
print("=" * 60)

model = SentenceTransformer("distiluse-base-multilingual-cased-v2")


# ─────────────────────────────────────────
# 2. Encode Sentences → Embeddings
# ─────────────────────────────────────────
print("\nSECTION 1: Encoding Sentences")
print("-" * 40)

sentences = [
    "The cat sat on the mat.",
    "A feline rested on the rug.",
    "Dogs love to play fetch.",
    "Machine learning is a subset of AI.",
    "Deep learning uses neural networks.",
    "Python is great for data science.",
]

embeddings = model.encode(sentences, show_progress_bar=False)

print(f"Number of sentences : {len(sentences)}")
print(f"Embedding dimension : {embeddings.shape[1]}")
print(f"Embeddings shape    : {embeddings.shape}\n")

for i, (sentence, emb) in enumerate(zip(sentences, embeddings)):
    print(f"  [{i}] \"{sentence}\"")
    print(f"       Vector (first 5 dims): {emb.round(4)}\n")


# ─────────────────────────────────────────
# 3. Pairwise Cosine Similarity
# ─────────────────────────────────────────
print("=" * 60)
print("📌 SECTION 2: Pairwise Cosine Similarity")
print("-" * 40)

pairs = [
    (0, 1),  # cat/mat vs feline/rug  → HIGH similarity
    (0, 2),  # cat vs dogs            → LOW similarity
    (3, 4),  # ML vs deep learning    → HIGH similarity
    (3, 5),  # ML vs Python           → MEDIUM similarity
    (2, 5),  # dogs vs Python         → LOW similarity
]

print(f"{'Sentence A':<45} {'Sentence B':<45} {'Score':>6}")
print("-" * 100)

for a, b in pairs:
    score = util.cos_sim(embeddings[a], embeddings[b]).item()
    label = "✅ HIGH" if score > 0.7 else ("🟡 MED" if score > 0.4 else "❌ LOW")
    print(f"  {sentences[a]:<43} {sentences[b]:<43} {score:.4f}  {label}")

#
# # ─────────────────────────────────────────
# # 4. Semantic Search (Query → Top-K)
# # ─────────────────────────────────────────
# print("\n" + "=" * 60)
# print("📌 SECTION 3: Semantic Search (Query → Corpus)")
# print("-" * 40)
#
# corpus = [
#     "How to train a neural network?",
#     "What is transfer learning in NLP?",
#     "Best practices for SQL query optimization.",
#     "Introduction to Kubernetes and container orchestration.",
#     "Transformer models revolutionized NLP tasks.",
#     "How to optimize database indexes for performance?",
#     "Understanding attention mechanism in deep learning.",
#     "Docker vs Kubernetes: which to choose?",
# ]
#
# query = "How do attention mechanisms work in transformers?"
# top_k = 3
#
# print(f"Query   : \"{query}\"")
# print(f"Top-K   : {top_k}\n")
#
# corpus_embeddings = model.encode(corpus, convert_to_tensor=True)
# query_embedding   = model.encode(query,  convert_to_tensor=True)
#
# hits = util.semantic_search(query_embedding, corpus_embeddings, top_k=top_k)[0]
#
# print(f"{'Rank':<6} {'Score':<8} Result")
# print("-" * 70)
# for rank, hit in enumerate(hits, start=1):
#     print(f"  #{rank}    {hit['score']:.4f}   {corpus[hit['corpus_id']]}")
#
#
# # ─────────────────────────────────────────
# # 5. Full Similarity Matrix
# # ─────────────────────────────────────────
# print("\n" + "=" * 60)
# print("📌 SECTION 4: Full Cosine Similarity Matrix")
# print("-" * 40)
#
# short_sentences = [
#     "I love programming.",
#     "Coding is my passion.",
#     "I enjoy cooking.",
#     "Baking is a great hobby.",
# ]
#
# short_embeddings = model.encode(short_sentences, convert_to_tensor=True)
# sim_matrix = util.cos_sim(short_embeddings, short_embeddings).numpy()
#
# # Pretty-print matrix
# col_width = 22
# header = " " * col_width + "".join(f"  S{i:<2}" for i in range(len(short_sentences)))
# print(header)
# print("-" * (col_width + 6 * len(short_sentences)))
#
# for i, row in enumerate(sim_matrix):
#     row_label = f"  S{i} {short_sentences[i][:17]:<17}"
#     scores    = "".join(f"  {v:.2f}" for v in row)
#     print(row_label + scores)
#
# print()
# for i, s in enumerate(short_sentences):
#     print(f"  S{i} = \"{s}\"")
#
#
# # ─────────────────────────────────────────
# # 6. Batch Encoding with Normalization
# # ─────────────────────────────────────────
# print("\n" + "=" * 60)
# print("📌 SECTION 5: Batch Encoding + L2 Normalization")
# print("-" * 40)
#
# batch_sentences = [f"This is sentence number {i}." for i in range(1, 6)]
#
# batch_embeddings = model.encode(
#     batch_sentences,
#     batch_size=32,
#     normalize_embeddings=True,   # L2-normalize → dot product == cosine sim
#     show_progress_bar=False,
# )
#
# print(f"Batch size   : {len(batch_sentences)}")
# print(f"Emb shape    : {batch_embeddings.shape}")
# print(f"L2 norms     : {np.linalg.norm(batch_embeddings, axis=1).round(4)}")
# print()
#
# # Dot product == cosine similarity when normalized
# dot_scores = np.dot(batch_embeddings[0], batch_embeddings[1:].T)
# print("Dot-product similarity of S1 vs S2–S5:")
# for i, score in enumerate(dot_scores, start=2):
#     print(f"  S1 ↔ S{i}: {score:.4f}")
#
#
# print("\n" + "=" * 60)
# print("✅ Demo complete!")
# print("=" * 60)