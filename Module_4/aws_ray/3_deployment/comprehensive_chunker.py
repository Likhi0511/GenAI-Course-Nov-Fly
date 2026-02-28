"""
===============================================================================
Comprehensive Boundary-Aware Semantic Chunker
===============================================================================

Author: Prudhvi | Thoughtworks
Domain: Enterprise Document Intelligence / RAG Ingestion

-------------------------------------------------------------------------------
SINGLE RESPONSIBILITY
-------------------------------------------------------------------------------

This module does exactly TWO things:

  1. PARSE   — Read boundary-marked .md files written by Stage 1 and extract
               atomic chunks (one per document element).

  2. GROUP   — Group atomic chunks into semantic chunks of ~target_size chars,
               respecting section boundaries and hard size limits.

That is all.

Everything else already happened in Stage 1 (docling_pdf_extractor.py):
  ✓ S3 uploads          — tables, images, page .md files all uploaded by Stage 1.
                          s3_uri is already in the boundary attr of each chunk.
  ✓ AI descriptions     — tables, images, formulas, and long code blocks all
                          described by Stage 1. ai_description is already in
                          the boundary attr of each chunk.

This module has NO boto3, NO openai, NO base64, NO image bytes.
Dependencies: re, html, logging, pathlib — pure text processing.

-------------------------------------------------------------------------------
HOW STAGE 1 ATTRS FLOW THROUGH
-------------------------------------------------------------------------------

Stage 1 writes a table boundary like:

  <!-- BOUNDARY_START type="table" id="p3_table_1" page="3" rows="8"
       breadcrumbs="Results &gt; Efficacy"
       s3_uri="s3://bucket/doc/tables/p3_table_1.md"
       ai_description="1. PURPOSE &#x2014; ..." -->
  | raw markdown table |
  <!-- BOUNDARY_END type="table" id="p3_table_1" -->

This module:
  1. Parses it → chunk dict with metadata.s3_uri and metadata.ai_description
  2. Groups it with surrounding paragraphs into a semantic chunk
  3. For large tables (> max_table_size): uses ai_description as VDB content,
     keeps s3_uri as the raw-retrieval pointer — both were set by Stage 1.
  4. For small tables: keeps raw table as VDB content, carries ai_description
     as supplementary metadata.

The decision of "use ai_description vs raw content" IS chunker logic —
it knows target_size and max_table_size. The generation of those values
is NOT chunker logic — that happened in Stage 1.

-------------------------------------------------------------------------------
FLUSH RULE PRIORITY
-------------------------------------------------------------------------------

  0. EMPTY FILTER   — len(content) < 10 → discard (empty boundary markers)
  1. IMAGE ROUTE    — image/picture/figure chunks → standalone, use ai_description
                      as content, s3_uri in metadata
  2. LARGE TABLE    — table chunks > max_table_size → standalone, use
                      ai_description as content, s3_uri in metadata
  3. HARD BREAK     — major section boundary (breadcrumb root changes) → flush
  4. MAX GUARD      — adding chunk would exceed max_size AND buf >= min_size → flush
  ADD               — append to buffer
  5. TARGET HIT     — buf >= target_size AND next chunk is not a header → flush
  6. EOF            — flush remaining buffer, merge small tail if possible

-------------------------------------------------------------------------------
OUTPUT SCHEMA
-------------------------------------------------------------------------------

Normal text chunk:
  {
    "content":  "## Introduction\\n\\nThis study evaluates...",
    "metadata": {
      "breadcrumbs":       "Introduction",
      "char_count":        1543,
      "num_atomic_chunks": 4,
      "chunk_types":       ["header", "paragraph", "paragraph", "list"]
    }
  }

Image chunk:
  {
    "content":  "1. FIGURE TYPE — Kaplan-Meier...",   ← ai_description from Stage 1
    "metadata": {
      "breadcrumbs":  "Results > Survival",
      "type":         "image_offloaded",
      "s3_uri":       "s3://bucket/doc/images/fig_p5_1.png",
      "char_count":   1105,
      "num_atomic_chunks": 1,
      "chunk_types":  ["image_offloaded"]
    }
  }

Large table chunk:
  {
    "content":  "1. PURPOSE — The table presents...",  ← ai_description from Stage 1
    "metadata": {
      "breadcrumbs":  "Results > Efficacy",
      "type":         "table_offloaded",
      "s3_uri":       "s3://bucket/doc/tables/p3_table_1.md",
      "char_count":   1820,
      "num_atomic_chunks": 1,
      "chunk_types":  ["table_offloaded"]
    }
  }

Small table chunk (stays in VDB as raw text):
  {
    "content":  "| Treatment | N | ... |",
    "metadata": {
      "breadcrumbs":    "Methods > Dosing",
      "ai_description": "1. PURPOSE — ...",   ← carried through for Stage 3
      "s3_uri":         "s3://bucket/doc/tables/p3_table_2.md",
      "char_count":     340,
      "num_atomic_chunks": 1,
      "chunk_types":    ["table"]
    }
  }

Formula chunk (stays in VDB; ai_description makes it searchable):
  {
    "content":  "Cmax = Dose / Vd x e^(-ke*t)",      ← raw formula preserved
    "metadata": {
      "ai_description": "One-compartment PK model...",← makes formula searchable
      "breadcrumbs":    "Methods > PK Analysis",
      ...
    }
  }
"""

import re
import html
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Minimum content length to be a real chunk.
# Stage 1 already filtered PAGE_HEADER/PAGE_FOOTER by label — they never
# reach this file. This guard only catches empty boundary markers (edge case,
# e.g. a table that exported zero rows).
_MIN_CONTENT_LEN = 10


# =============================================================================
# CONTENT FILTERING
# =============================================================================

def is_empty_chunk(content: str) -> bool:
    """
    Return True for genuinely empty boundary markers.
    NOT a noise-filtering function — noise was removed in Stage 1.
    """
    return len(content.strip()) < _MIN_CONTENT_LEN


# =============================================================================
# BREADCRUMB UTILITIES
# =============================================================================

def breadcrumb_root(breadcrumb: str) -> str:
    """
    Extract the top-level section name from a breadcrumb path.

    Stage 1 writes breadcrumbs using " > " as separator.
    We also tolerate other common conventions.

    "Diarrhea > Grade 1/2 > Uncomp"  →  "Diarrhea"
    "Skin Toxicity"                   →  "Skin Toxicity"
    ""                                →  ""
    """
    if not breadcrumb:
        return ""
    for sep in (" > ", " / ", " | ", " :: "):
        if sep in breadcrumb:
            return breadcrumb.split(sep)[0].strip()
    return breadcrumb.strip()


def is_major_section_change(prev: str, curr: str) -> bool:
    """
    Return True when the breadcrumb root changes between two chunks.

    Major change → always flush:
      "Diarrhea" → "Skin Toxicity"

    Minor change → allow merge (accumulate to target_size):
      "Diarrhea" → "Diarrhea > Grade 1/2"

    We only flush on MAJOR changes — flushing on every sub-section change
    would produce tiny under-sized chunks for every subsection transition.
    """
    if not prev or not curr:
        # One side has no breadcrumb — can't compare, don't force flush.
        return False
    return breadcrumb_root(prev) != breadcrumb_root(curr)


# =============================================================================
# PARSING
# =============================================================================

def extract_chunks_from_markdown(markdown_text: str) -> List[Dict]:
    """
    Parse boundary-marked .md text from Stage 1 into a list of atomic chunks.

    Boundary format written by Stage 1:
      <!-- BOUNDARY_START type="table" id="p3_table_1" page="3"
           breadcrumbs="Results &gt; Efficacy"
           s3_uri="s3://bucket/doc/tables/p3_table_1.md"
           ai_description="1. PURPOSE &#x2014; ..." -->
      | raw markdown |
      <!-- BOUNDARY_END type="table" id="p3_table_1" -->

    Two parsing corrections applied here:

    1. Line-ending normalisation (Windows files use \\r\\n):
       The boundary regex uses literal \\n. A file with \\r\\n line endings
       would produce zero matches — every chunk silently lost.
       Fix: normalise to \\n before matching.

    2. HTML entity unescaping:
       Stage 1 escapes attribute values before writing:
         " → &quot;   (prevents parser regex breaking on quoted terms)
         newline → space
       html.unescape() reverses this so consumers see the original text.

    Returns list of dicts:
      {
        'id':       'p3_table_1',
        'type':     'table',
        'page':     '3',
        'content':  '| raw markdown |',
        'metadata': {
            'breadcrumbs':    'Results > Efficacy',   ← unescaped
            'ai_description': '1. PURPOSE — ...',     ← unescaped
            's3_uri':         's3://bucket/...',
            'rows': '8', 'columns': '5', ...
        }
      }
    """
    # Normalise Windows \\r\\n → \\n before regex matching
    markdown_text = markdown_text.replace('\r\n', '\n').replace('\r', '\n')

    pattern = r'<!-- BOUNDARY_START (.*?) -->\n(.*?)\n<!-- BOUNDARY_END (.*?) -->'
    chunks: List[Dict] = []

    for start_attrs, content, _ in re.findall(pattern, markdown_text, re.DOTALL):
        # Parse key="value" pairs. Values may contain HTML entities (&quot; etc.)
        # because Stage 1 escaped them before writing.
        raw_attrs = dict(re.findall(r'(\w+)="([^"]*)"', start_attrs))
        attrs     = {k: html.unescape(v) for k, v in raw_attrs.items()}

        chunk: Dict = {
            'id':      attrs.get('id',   'unknown'),
            'type':    attrs.get('type', 'unknown'),
            'page':    attrs.get('page', '0'),
            'content': content.strip(),
        }

        # Everything except the three primary fields goes into metadata:
        # breadcrumbs, ai_description, s3_uri, rows, columns,
        # image_filename, has_caption, char_count, word_count, language, etc.
        metadata = {k: v for k, v in attrs.items() if k not in ('id', 'type', 'page')}
        if metadata:
            chunk['metadata'] = metadata

        chunks.append(chunk)

    return chunks


def chunk_file(file_path: Path) -> List[Dict]:
    """Parse a single boundary-marked .md file into atomic chunks."""
    return extract_chunks_from_markdown(
        file_path.read_text(encoding='utf-8')
    )


def _natural_sort_key(path: Path) -> int:
    """
    Sort key that extracts the first integer from a filename.

    Prevents lexicographic ordering where page_10.md sorts before page_2.md.
    page_1 → 1, page_2 → 2, ..., page_10 → 10, page_11 → 11.
    Falls back to 0 for filenames with no digit.
    """
    match = re.search(r'\d+', path.name)
    return int(match.group()) if match else 0


def chunk_directory(dir_path: Path) -> Dict[str, List[Dict]]:
    """
    Parse all .md files in a directory and return a filename → chunks mapping.

    Handles three layouts produced by Stage 1:
      1. dir_path/*.md              — pages dir passed directly
      2. dir_path/pages/*.md        — single-doc root layout
      3. dir_path/*/pages/*.md      — batch-of-docs layout

    Files are sorted by page number (natural sort) not alphabetically,
    so chunk order matches document reading order even for 10+ page docs.
    """
    results: Dict[str, List[Dict]] = {}

    # Layout 1: flat pages dir
    md_files = sorted(dir_path.glob('*.md'), key=_natural_sort_key)
    if md_files:
        for f in md_files:
            results[f.name] = chunk_file(f)
        return results

    # Layout 2: single doc with pages/ subdirectory
    pages_dir = dir_path / 'pages'
    if pages_dir.exists():
        for f in sorted(pages_dir.glob('*.md'), key=_natural_sort_key):
            results[f.name] = chunk_file(f)
        return results

    # Layout 3: batch of docs, each with pages/ subdirectory
    for pd in sorted(dir_path.glob('*/pages')):
        for f in sorted(pd.glob('*.md'), key=_natural_sort_key):
            results[f"{pd.parent.name}/{f.name}"] = chunk_file(f)

    return results


# =============================================================================
# SEMANTIC CHUNKING
# =============================================================================

def create_semantic_chunks(
    chunks: List[Dict],
    target_size: int = 1500,
    min_size: int   = 800,
    max_size: int   = 3000,
    max_table_size: int = 2000,
) -> List[Dict]:
    """
    Group atomic chunks into coherent semantic chunks.

    Parameters:
      chunks         — atomic chunks from chunk_directory() or extract_chunks_from_markdown()
      target_size    — target char count per semantic chunk (~1500)
      min_size       — minimum size before a chunk can be flushed (800)
      max_size       — hard ceiling per chunk (3000)
      max_table_size — tables larger than this are treated as offloaded;
                       their ai_description becomes the VDB content

    Note: NO s3_client, NO llm_client, NO figures_dir parameters.
    All s3_uris and ai_descriptions were set by Stage 1 and are already
    in each chunk's metadata. This function only reads them — never uploads
    or generates anything.

    ── FLUSH RULES (in priority order) ─────────────────────────────────────

    0. EMPTY FILTER
       Chunks with fewer than _MIN_CONTENT_LEN chars are discarded.
       These are empty boundary markers — a table that exported zero rows,
       for example. Real noise was already removed by Stage 1.

    1. IMAGE / PICTURE ROUTE
       All image-type chunks are routed standalone:
         content  = ai_description (the vision LLM result from Stage 1)
         s3_uri   = carried through to metadata
       Why standalone: images are binary assets. Their ai_description is
       self-contained and should not be merged with surrounding text —
       it would dilute both the image embedding and the text embedding.

    2. LARGE TABLE ROUTE
       Table chunks exceeding max_table_size chars are routed standalone:
         content  = ai_description (the 7-dimension LLM result from Stage 1)
         s3_uri   = carried through to metadata
       Why standalone: oversized tables degrade VDB vector quality if
       merged with text. The ai_description is a complete, self-contained
       analytical summary.
       Small tables stay in the buffer and are merged with surrounding text.

    3. HARD BREAK — major section change
       If the incoming chunk's breadcrumb root differs from the current
       buffer root, flush before adding. Prevents merging "Introduction"
       content with "Adverse Events" content regardless of buffer size.

    4. MAX GUARD
       If adding this chunk would push the buffer over max_size AND the
       buffer already has enough content (>= min_size), flush first.
       The "AND >= min_size" condition prevents flushing a buffer that is
       still too small — those must keep accumulating even if temporarily
       over max_size.

    5. TARGET HIT
       Once buffer_size >= target_size, flush — unless the next chunk is
       a header, in which case hold. A section header belongs with the
       content that follows it, not stranded at the bottom of the previous
       chunk.

    6. EOF + TAIL MERGE
       After the loop, flush any remaining buffer. If the remainder is
       below min_size, merge into the last semantic chunk if:
         a. Same major section root
         b. Last chunk is not an offloaded asset
         c. Combined size stays within max_size
       Prevents tiny trailing subsections becoming isolated orphan chunks.
    """
    semantic_chunks: List[Dict] = []
    buffer: List[Dict]          = []
    buffer_size: int            = 0
    current_breadcrumb: Optional[str] = None

    # ── Inner helpers ─────────────────────────────────────────────────────────

    def next_is_header(idx: int) -> bool:
        """
        True if the next chunk in the list is a header.
        Used to delay flush at target_size so the header enters the
        next chunk alongside the section content it introduces.
        """
        return idx + 1 < len(chunks) and chunks[idx + 1]['type'] == 'header'

    def flush() -> None:
        """
        Emit current buffer as a single semantic chunk and reset state.

        Combines buffered atomic chunks into one text block.
        Collects ai_description values from table chunks in the buffer —
        these were generated by Stage 1 and are useful to Stage 3
        without requiring a new LLM call.
        """
        nonlocal buffer, buffer_size

        if not buffer:
            return

        parts: List[str]           = []
        ai_descriptions: List[str] = []

        for c in buffer:
            stripped = c['content'].strip()
            if stripped:
                parts.append(stripped)

            # Carry Stage 1 ai_descriptions for small tables/formulas/code
            # that stayed in the buffer. Stage 3 (enrichment) can use these
            # directly without generating new descriptions.
            desc = c.get('metadata', {}).get('ai_description', '')
            if desc and 'unavailable' not in desc:
                ai_descriptions.append(desc)

        if not parts:
            buffer.clear()
            buffer_size = 0
            return

        combined = '\n\n'.join(parts)
        sc: Dict = {
            'combined_content': combined,
            'chunk_ids':        [c['id']   for c in buffer],
            'breadcrumbs':      current_breadcrumb,
            'char_count':       len(combined),
            'num_chunks':       len(buffer),
            'chunk_types':      [c['type'] for c in buffer],
        }
        if ai_descriptions:
            # First one wins — multiple tables in one semantic chunk is uncommon
            sc['ai_description'] = ai_descriptions[0]

        semantic_chunks.append(sc)
        buffer.clear()
        buffer_size = 0

    def make_standalone(chunk: Dict, content: str, kind: str) -> Dict:
        """
        Build a semantic chunk dict for a standalone routed asset
        (offloaded image or large table).

        content  = ai_description from Stage 1 (what the VDB embeds)
        s3_uri   = pointer to raw asset in S3 (set by Stage 1)
        breadcrumb comes from the chunk's own boundary attr (accurate).
        """
        bc = chunk.get('metadata', {}).get('breadcrumbs', current_breadcrumb or '')
        result: Dict = {
            'combined_content': content,
            'chunk_ids':        [chunk['id']],
            'breadcrumbs':      bc,
            'char_count':       len(content),
            'num_chunks':       1,
            'chunk_types':      [kind],
        }
        s3_uri = chunk.get('metadata', {}).get('s3_uri', '')
        if s3_uri:
            result['s3_uri'] = s3_uri
        return result

    # ── Main loop ─────────────────────────────────────────────────────────────

    for idx, chunk in enumerate(chunks):
        chunk_type = chunk['type']
        breadcrumb = chunk.get('metadata', {}).get('breadcrumbs', '')
        chunk_size = len(chunk['content'].strip())

        # ── 0. Empty filter ───────────────────────────────────────────────────
        if is_empty_chunk(chunk['content']):
            logger.debug("Discarded empty chunk %s", chunk['id'])
            continue

        # ── 1. Image route ────────────────────────────────────────────────────
        # Images are never merged with text — their ai_description is a
        # self-contained visual analysis that should embed on its own.
        if chunk_type in ('picture', 'image', 'figure'):
            flush()
            ai_desc = chunk.get('metadata', {}).get('ai_description', '').strip()
            if not ai_desc:
                # Stage 1 should always provide this — log if missing.
                # Fall back to the raw content (Markdown image ref or base64 stub)
                # truncated to max_size so the VDB chunk is never empty.
                # An empty string here would reach generate_embeddings() and
                # cause a 400 Bad Request from the OpenAI embeddings API.
                logger.warning(
                    "Image chunk %s has no ai_description — using raw content fallback",
                    chunk['id'],
                )
                ai_desc = chunk['content'].strip()[:max_size] or (
                    f"[Image: {chunk['id']} — description unavailable]"
                )
            semantic_chunks.append(
                make_standalone(chunk, ai_desc, "image_offloaded")
            )
            current_breadcrumb = breadcrumb
            continue

        # ── 2. Large table route ──────────────────────────────────────────────
        # Tables exceeding max_table_size would make VDB chunks oversized and
        # degrade retrieval quality. Use ai_description as the VDB content.
        # The raw Markdown is in S3 (s3_uri set by Stage 1) for exact retrieval.
        if chunk_type == 'table' and chunk_size > max_table_size:
            flush()
            ai_desc = chunk.get('metadata', {}).get('ai_description', '').strip()
            if not ai_desc:
                logger.warning(
                    "Large table %s has no ai_description — using truncated raw content fallback",
                    chunk['id'],
                )
                # Truncate to max_table_size so it stays manageable.
                # Still better than an empty string which would cause a 400
                # from the OpenAI embeddings API for the downstream Stage 4.
                ai_desc = chunk['content'].strip()[:max_table_size] or (
                    f"[Table: {chunk['id']} — description unavailable]"
                )
            semantic_chunks.append(
                make_standalone(chunk, ai_desc, "table_offloaded")
            )
            current_breadcrumb = breadcrumb
            continue

        # ── 3. Hard break: major section boundary ─────────────────────────────
        # "Introduction" → "Methods" = flush.
        # "Methods" → "Methods > Statistics" = allow merge (minor change).
        if buffer and is_major_section_change(current_breadcrumb or '', breadcrumb):
            flush()

        # ── 4. Max guard ──────────────────────────────────────────────────────
        # Prevent any semantic chunk from exceeding max_size.
        # Only flush if the buffer already has enough content to stand alone.
        before_header = next_is_header(idx)
        if buffer_size + chunk_size > max_size and buffer_size >= min_size:
            flush()

        # ── Add to buffer ─────────────────────────────────────────────────────
        buffer.append(chunk)
        buffer_size        += chunk_size
        current_breadcrumb  = breadcrumb

        # ── 5. Target hit ─────────────────────────────────────────────────────
        # Reached target_size — flush unless the next item is a header
        # (keep header with the content that follows it).
        if buffer_size >= target_size and not before_header:
            flush()

    # ── 6. EOF + tail merge ───────────────────────────────────────────────────
    # Handle remaining buffer. Merge small tails into the previous chunk
    # instead of emitting isolated tiny orphan chunks.
    if buffer and buffer_size < min_size and semantic_chunks:
        last       = semantic_chunks[-1]
        last_bc    = last.get('breadcrumbs', '')
        last_types = last.get('chunk_types', [])

        can_merge = (
            not is_major_section_change(last_bc, current_breadcrumb or '')
            and 'table_offloaded' not in last_types
            and 'image_offloaded' not in last_types
            and last['char_count'] + buffer_size <= max_size
        )

        if can_merge:
            tail = '\n\n'.join(c['content'].strip() for c in buffer)
            last['combined_content'] += '\n\n' + tail
            last['chunk_ids'].extend(c['id']   for c in buffer)
            last['chunk_types'].extend(c['type'] for c in buffer)
            last['num_chunks'] += len(buffer)
            last['char_count']  = len(last['combined_content'])
            logger.debug("Tail-merged %d chunk(s) into previous semantic chunk.", len(buffer))
            buffer.clear()
            buffer_size = 0
        else:
            flush()
    else:
        flush()

    return semantic_chunks


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_chunks_for_output(
    semantic_chunks: List[Dict],
    keep_ids: bool = False,
) -> List[Dict]:
    """
    Convert internal semantic chunk dicts to the clean output schema for Stage 3.

    Output schema:
      {
        "content":  "...",
        "metadata": {
          "breadcrumbs":       "Results > Adverse Events",
          "char_count":        1543,
          "num_atomic_chunks": 4,
          "chunk_types":       ["header", "paragraph", "list", "table"],
          # offloaded assets:
          "type":    "table_offloaded" | "image_offloaded",
          "s3_uri":  "s3://...",
          # small tables / formulas / code that stayed in VDB:
          "ai_description": "1. PURPOSE — ...",
          # debugging / lineage (keep_ids=True only):
          "chunk_ids": ["p3_table_1", ...]
        }
      }

    chunk_types is ALWAYS included — Stage 3 needs it to know whether a
    chunk contains code or formula blocks and should skip PII redaction.
    """
    result = []
    for chunk in semantic_chunks:
        chunk_types = chunk.get('chunk_types', [])
        out: Dict = {
            'content':  chunk['combined_content'],
            'metadata': {
                'breadcrumbs':       chunk.get('breadcrumbs', ''),
                'char_count':        chunk['char_count'],
                'num_atomic_chunks': chunk['num_chunks'],
                # Always include chunk_types — Stage 3 uses this to decide
                # which enrichment operations are appropriate (e.g. skip PII
                # redaction for 'code' and 'formula' chunk types).
                'chunk_types':       chunk_types,
            },
        }

        # Tag offloaded assets so Stage 3 knows to retrieve from S3
        if 'table_offloaded' in chunk_types:
            out['metadata']['type'] = 'table_offloaded'
        elif 'image_offloaded' in chunk_types:
            out['metadata']['type'] = 'image_offloaded'

        # S3 pointer for raw asset retrieval
        if chunk.get('s3_uri'):
            out['metadata']['s3_uri'] = chunk['s3_uri']

        # ai_description for small tables / formulas / code that stayed in VDB.
        # Stage 1 generated this; it flows here via chunk['metadata']['ai_description']
        # → flush()'s ai_descriptions collector → semantic chunk.
        # Stage 3 uses it as enrichment context without a new LLM call.
        if chunk.get('ai_description'):
            out['metadata']['ai_description'] = chunk['ai_description']

        if keep_ids:
            out['metadata']['chunk_ids'] = chunk['chunk_ids']

        result.append(out)
    return result