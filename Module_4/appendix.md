Here is the refined pipeline description in Markdown format.

---

# Document Processing & Enrichment Pipeline

## 1. Extraction Layer

* **Input:** A single PDF file or a directory containing multiple PDFs.
* **Process:** The system decomposes the PDF into structural components, including text, tables, and images, while maintaining boundary markers.
* **Default Output:** If no path is provided, it creates an `extracted_docs_bounded/` root directory. For each document, a dedicated subfolder is generated containing:
* **Images/**: All visual assets extracted from the file.
* **Pages/**: Individual Markdown (`.md`) files for every page.
* **metadata.json**: A manifest mapping the structural relationship between assets and text.



## 2. Semantic Chunking Layer

* **Input:** The folder containing the `pages/` directory (Markdown files) from the extraction step.
* **Process:** Groups atomic content into logically coherent blocks. It uses type-aware logic to ensure headers remain attached to their following paragraphs and manages large tables as standalone semantic units.
* **Default Output:** Generates `semantic_chunks.json`. This is saved within the document's specific subfolder inside `extracted_docs_bounded/` unless an alternative path is specified.

## 3. Intelligence Enrichment Layer

* **Input:** The `semantic_chunks.json` file created in the previous layer.
* **Process:** Acts as a data refinery using AI (OpenAI/AWS) and local regex patterns. It identifies key entities (People, Orgs, Money), extracts thematic key phrases, and performs context-aware PII redaction (hiding sensitive personal data while preserving business-critical dates and locations).
* **Final Output:** **`semantic_chunks_enriched.json`** — a high-fidelity, metadata-rich file ready for ingestion into a RAG (Retrieval-Augmented Generation) pipeline or Vector Database.

---

### Pipeline Summary Table

| Step | Action | Primary Input | Primary Output |
| --- | --- | --- | --- |
| **1** | **Extraction** | Raw `.pdf` | `pages/*.md` + `metadata.json` |
| **2** | **Chunking** | `pages/` (Markdown) | `semantic_chunks.json` |
| **3** | **Enrichment** | `semantic_chunks.json` | `semantic_chunks_enriched.json` |

---

**Would you like me to help you create a README.md file that includes these descriptions along with the CLI commands to run each script?**