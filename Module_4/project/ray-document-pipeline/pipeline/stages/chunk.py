"""
===============================================================================
comprehensive_chunker.py  -  Boundary-Aware Semantic Chunker  v2
===============================================================================

Author  : Prudhvi  |  Thoughtworks
Stage   : 2 of 5  (Extract -> Chunk -> Enrich -> Embed -> Store)

-------------------------------------------------------------------------------
SINGLE RESPONSIBILITY
-------------------------------------------------------------------------------

This module does exactly TWO things:

  1. PARSE  - Read boundary-marked .md files written by Stage 1 and extract
              atomic chunks (one per document element).

  2. GROUP  - Group atomic chunks into semantic chunks respecting section
              boundaries and hard size limits.

This module has:
  NO boto3          - no S3 calls of any kind
  NO openai         - no AI description generation
  NO base64         - no image handling
  NO re-measurement - never re-measures raw content to decide if table is large

Dependencies: re, html, logging, pathlib  (pure text processing only)

-------------------------------------------------------------------------------
STAGE 1 -> STAGE 2 CONTRACT
-------------------------------------------------------------------------------

Stage 1 writes ALL decisions. Stage 2 trusts them completely.

  is_large="yes"       -> route as standalone, never enter buffer
  is_large="no"        -> normal buffer accumulation
  s3_uri="s3://..."    -> pass through to chunk metadata unchanged
  ai_description="..." -> IGNORED by Stage 2 (already in body text as blockquote)
  breadcrumbs="..."    -> section boundary detection

The AI description lives in chunk['content'] as a Markdown blockquote (> ...).
Stage 2 uses chunk['content'] directly as VDB content. It never reads
ai_description from boundary attrs.

WHY LARGE TABLE BODY IS JUST THE DESCRIPTION:
  Stage 1 writes large table body = caption + description blockquote + S3 link.
  NO raw Markdown inline. So chunk['content'] for a large table is ~2000 chars
  (the description) not 65k (the raw Markdown).

  CRITICAL: We CANNOT use len(chunk['content']) > threshold to detect large
  tables because Stage 1 already wrote only the description (~2000 chars) into
  the body. That length is BELOW the threshold, so content-length detection
  would incorrectly route the large table into the buffer instead of standalone.
  is_large="yes" attr is the ONLY reliable routing signal for large tables.

-------------------------------------------------------------------------------
FLUSH RULE PRIORITY  (evaluated in this order for every chunk)
-------------------------------------------------------------------------------

  0. EMPTY FILTER  - len(content) < 10  -> discard silently
  1. IMAGE ROUTE   - type in (image, picture, figure)
                     -> flush buffer, emit standalone
                     -> chunk['content'] is the VDB content (description blockquote)
  2. LARGE TABLE   - is_large="yes" attr
                     -> flush buffer, emit standalone
                     -> chunk['content'] is the VDB content (description blockquote)
  3. HARD BREAK    - major section boundary change -> flush buffer
  4. MAX GUARD     - adding chunk would exceed max_size AND buf >= min_size -> flush
  ADD              - append chunk to buffer, update buffer_size
  5. TARGET HIT    - buffer_size >= target_size AND next chunk is not a header -> flush
  6. EOF + TAIL    - flush remainder; merge small tail into previous if possible

-------------------------------------------------------------------------------
OUTPUT SCHEMA
-------------------------------------------------------------------------------

Normal text / small table chunk:
  {
    "content":  "## Introduction\n\nThis study evaluates...",
    "metadata": {
      "breadcrumbs":       "Introduction",
      "char_count":        1543,
      "num_atomic_chunks": 4,
      "chunk_types":       ["header", "paragraph", "paragraph", "list"]
    }
  }

Large table chunk (content = description written by Stage 1 into body):
  {
    "content": "*Caption:* Table 3\n> 1. PURPOSE - ...\n*Full table: s3://...*",
    "metadata": {
      "breadcrumbs":       "Results > Efficacy",
      "type":              "table_offloaded",
      "s3_uri":            "s3://bucket/doc/tables/p3_table_1.md",
      "char_count":        1820,
      "num_atomic_chunks": 1,
      "chunk_types":       ["table_offloaded"]
    }
  }

Image chunk (content = description written by Stage 1 into body):
  {
    "content": "**Image**\n*Caption:* Figure 1\n![fig](s3://...)\n> 1. FIGURE TYPE...",
    "metadata": {
      "breadcrumbs":       "Results > Survival",
      "type":              "image_offloaded",
      "s3_uri":            "s3://bucket/doc/images/fig_p5_1.png",
      "char_count":        1105,
      "num_atomic_chunks": 1,
      "chunk_types":       ["image_offloaded"]
    }
  }

-------------------------------------------------------------------------------
QUERY-TIME RETRIEVAL FOR LARGE TABLES  (handled by query layer, not here)
-------------------------------------------------------------------------------

  1. VDB search finds chunk via description match
     (description includes key numbers: HR, p-values, CIs written by Stage 1)
  2. Query layer sees metadata.type = "table_offloaded" + metadata.s3_uri
  3. Fetches raw Markdown from S3
  4. Passes description + full table to LLM
  5. LLM produces precise numeric answer (HR=0.62, p=0.002, etc.)
"""

import re
import html
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum body length to qualify as a real chunk.
# Guards against empty boundary markers (table exported zero rows etc.)
_MIN_CONTENT_LEN = 10


# =============================================================================
# CONTENT FILTERING
# =============================================================================

def is_empty_chunk(content: str) -> bool:
    """Return True for genuinely empty boundary markers."""
    return len(content.strip()) < _MIN_CONTENT_LEN


# =============================================================================
# BREADCRUMB UTILITIES
# =============================================================================

def breadcrumb_root(breadcrumb: str) -> str:
    """
    Extract the top-level section name from a breadcrumb path.

    "Results > Efficacy > Subgroup"  ->  "Results"
    "Safety"                          ->  "Safety"
    ""                                ->  ""
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

    Major change (flush):       "Results"  ->  "Safety"
    Minor change (allow merge): "Results"  ->  "Results > Subgroup"
    """
    if not prev or not curr:
        return False
    return breadcrumb_root(prev) != breadcrumb_root(curr)


# =============================================================================
# PARSING
# =============================================================================

def extract_chunks_from_markdown(markdown_text: str) -> List[Dict]:
    """
    Parse boundary-marked .md text produced by Stage 1 into atomic chunks.

    Boundary format produced by Stage 1:
      <!-- BOUNDARY_START type="table" id="p3_table_1" page="3"
           is_large="yes" breadcrumbs="Results &gt; Efficacy"
           s3_uri="s3://bucket/doc/tables/p3_table_1.md"
           ai_description="1. PURPOSE &#x2014; ..." -->
      *Caption:* Table 3 - Efficacy Results
      > 1. PURPOSE - The table presents...
      *Full table data available at: s3://...*
      <!-- BOUNDARY_END type="table" id="p3_table_1" -->

    Two parsing corrections applied automatically:

      1. Line-ending normalisation (Windows \\r\\n -> \\n):
         The boundary regex uses literal \\n. CRLF files produce zero matches
         without this step.

      2. HTML entity unescaping:
         Stage 1 escapes attribute values so HTML-comment syntax stays valid.
         html.unescape() reverses this so consumers see original text.

    NOTE on ai_description attr:
      It is parsed into chunk['metadata'] but Stage 2 never reads it for
      routing or content decisions. The description is already present in
      chunk['content'] as a Markdown blockquote written by Stage 1.
      The attr flows through to output for monitoring/audit tools only.

    Returns list of dicts:
      {
        'id':       'p3_table_1',
        'type':     'table',
        'page':     '3',
        'content':  '*Caption:*...\\n> 1. PURPOSE...',   <- body text
        'metadata': {
            'breadcrumbs':    'Results > Efficacy',      <- html unescaped
            'is_large':       'yes',
            's3_uri':         's3://bucket/...',
            'rows':           '8',
            'columns':        '5',
            'ai_description': '...',                     <- present, not used by Stage 2
        }
      }
    """
    markdown_text = markdown_text.replace('\r\n', '\n').replace('\r', '\n')

    pattern = r'<!-- BOUNDARY_START (.*?) -->\n(.*?)\n<!-- BOUNDARY_END (.*?) -->'
    chunks: List[Dict] = []

    for start_attrs, content, _ in re.findall(pattern, markdown_text, re.DOTALL):
        raw_attrs = dict(re.findall(r'(\w+)="([^"]*)"', start_attrs))
        attrs     = {k: html.unescape(v) for k, v in raw_attrs.items()}

        chunk: Dict = {
            'id':      attrs.get('id',   'unknown'),
            'type':    attrs.get('type', 'unknown'),
            'page':    attrs.get('page', '0'),
            'content': content.strip(),
        }

        metadata = {k: v for k, v in attrs.items()
                    if k not in ('id', 'type', 'page')}
        if metadata:
            chunk['metadata'] = metadata

        chunks.append(chunk)

    return chunks


def chunk_file(file_path: Path) -> List[Dict]:
    """
    Parse a single boundary-marked .md file into atomic chunks.

    Tries UTF-8 first. Falls back to latin-1 with replacement if the file
    is not valid UTF-8. The boundary regex operates on ASCII-range characters
    so latin-1 decoded content parses correctly either way.
    """
    try:
        text = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        logger.warning(
            "chunk_file: %s is not valid UTF-8 - falling back to latin-1. "
            "Check Stage 1 write path for encoding issues.",
            file_path.name,
        )
        text = file_path.read_text(encoding='latin-1', errors='replace')
    return extract_chunks_from_markdown(text)


def _natural_sort_key(path: Path) -> int:
    """
    Sort key that extracts the first integer from a filename.
    Prevents lexicographic ordering: page_10.md before page_2.md.
    """
    match = re.search(r'\d+', path.name)
    return int(match.group()) if match else 0


def chunk_directory(dir_path: Path) -> Dict[str, List[Dict]]:
    """
    Parse all .md files in a directory. Returns filename -> chunks mapping.

    Handles three Stage 1 output layouts automatically:
      Layout 1: dir_path/*.md              (pages dir passed directly)
      Layout 2: dir_path/pages/*.md        (single-doc root layout)
      Layout 3: dir_path/*/pages/*.md      (batch-of-docs layout)

    Files sorted by page number (natural sort) to preserve document reading order.
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
    target_size: int    = 1500,
    min_size: int       = 800,
    max_size: int       = 3000,
    max_table_size: int = 2000,
) -> List[Dict]:
    """
    Group atomic chunks into coherent semantic chunks for the VDB.

    Parameters:
      chunks         - atomic chunks from chunk_directory() / extract_chunks_from_markdown()
      target_size    - target char count per semantic chunk (default 1500)
      min_size       - minimum size before a chunk can be flushed (default 800)
      max_size       - hard ceiling per chunk (default 3000)
      max_table_size - fallback threshold ONLY for tables missing the is_large attr
                       (backward compat with old Stage 1 output that predates the attr)

    ROUTING LOGIC:
      Images and large tables are always routed standalone via make_standalone().
      make_standalone() uses chunk['content'] directly as the VDB content.
      Stage 1 already wrote the AI description as a Markdown blockquote in the body.
      No attr reading, no fallback generation, no placeholder strings.

      s3_uri is passed through from boundary attr to output metadata so the
      query layer can fetch raw assets for precise numeric answers at query time.

    WHAT THIS FUNCTION DOES NOT DO:
      - Call OpenAI
      - Call S3 / boto3
      - Generate AI descriptions
      - Re-measure raw table content to decide if a table is large
      - Read ai_description attr (it is already in chunk['content'])
    """
    semantic_chunks: List[Dict] = []
    buffer: List[Dict]          = []
    buffer_size: int            = 0
    current_breadcrumb: Optional[str] = None

    # ── Inner helpers ─────────────────────────────────────────────────────

    def next_is_header(idx: int) -> bool:
        """
        True if the next chunk is a header.
        Delays flush so the header enters the NEXT semantic chunk with its
        own content rather than being stranded at the bottom of the current one.
        """
        return (idx + 1 < len(chunks) and
                chunks[idx + 1]['type'] == 'header')

    def flush() -> None:
        """
        Emit current buffer as a single semantic chunk and reset state.
        Collects any s3_uri values from buffered elements and passes the
        first one through to output metadata.
        """
        nonlocal buffer, buffer_size

        if not buffer:
            return

        parts:   List[str] = []
        s3_uris: List[str] = []

        for c in buffer:
            stripped = c['content'].strip()
            if stripped:
                parts.append(stripped)
            uri = c.get('metadata', {}).get('s3_uri', '')
            if uri:
                s3_uris.append(uri)

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
        if s3_uris:
            sc['s3_uri'] = s3_uris[0]

        semantic_chunks.append(sc)
        buffer.clear()
        buffer_size = 0

    def make_standalone(chunk: Dict, kind: str) -> Dict:
        """
        Build a standalone semantic chunk for an image or large table.

        Uses chunk['content'] directly as VDB content.
        Stage 1 wrote the AI description as plain body text (Markdown blockquote).
        No attr reading, no fallback generation, no placeholder strings.

        If chunk['content'] is empty that is a Stage 1 bug, not Stage 2's concern.

        s3_uri passed through from boundary attr for query-layer retrieval:
          - Images:       points to PNG in S3
          - Large tables: points to raw Markdown in S3
                          Query layer fetches this for precise numeric answers.
        """
        meta    = chunk.get('metadata', {})
        bc      = meta.get('breadcrumbs', current_breadcrumb or '')
        content = chunk['content'].strip()

        result: Dict = {
            'combined_content': content,
            'chunk_ids':        [chunk['id']],
            'breadcrumbs':      bc,
            'char_count':       len(content),
            'num_chunks':       1,
            'chunk_types':      [kind],
        }

        s3_uri = meta.get('s3_uri', '')
        if s3_uri:
            result['s3_uri'] = s3_uri

        return result

    # ── Main loop ──────────────────────────────────────────────────────────

    for idx, chunk in enumerate(chunks):
        chunk_type = chunk['type']
        breadcrumb = chunk.get('metadata', {}).get('breadcrumbs', '')
        meta       = chunk.get('metadata', {})
        chunk_size = len(chunk['content'].strip())

        # ── Large table detection ──────────────────────────────────────────
        #
        # PRIMARY: is_large attr from Stage 1  (always use this when present)
        #
        # CRITICAL: Do NOT use chunk_size > max_table_size when is_large attr
        # is present. Stage 1 writes only the description (~2000 chars) into
        # the body for large tables. chunk_size would be ~2000 which is BELOW
        # max_table_size (2000), so content-length detection would incorrectly
        # route large tables into the buffer instead of standalone.
        #
        # FALLBACK: content length only when is_large attr is genuinely absent
        # from the boundary marker. This handles .md files written by old Stage 1
        # versions that predate the is_large attr.
        # When attr is present (even as "no"), we trust it completely.
        is_large_attr  = meta.get('is_large', '')
        is_large_table = chunk_type == 'table' and (
            is_large_attr == 'yes'
            or (is_large_attr == ''              # attr genuinely absent (old Stage 1)
                and chunk_size > max_table_size)
        )

        # ── 0. Empty filter ───────────────────────────────────────────────
        if is_empty_chunk(chunk['content']):
            logger.debug("Discarded empty chunk  id=%s", chunk['id'])
            continue

        # ── 1. Image route ────────────────────────────────────────────────
        # chunk['content'] already IS the VDB content. Written by Stage 1:
        #   **Image**
        #   *Caption:* Figure 1 - Kaplan-Meier OS curve
        #   ![fig_p5_1.png](s3://bucket/doc/images/fig_p5_1.png)
        #   > 1. FIGURE TYPE - Kaplan-Meier curve...
        #   > 2. CONTENT - x-axis shows time in months...
        # Route standalone, use body directly. No attr reading.
        if chunk_type in ('picture', 'image', 'figure'):
            flush()
            semantic_chunks.append(make_standalone(chunk, 'image_offloaded'))
            current_breadcrumb = breadcrumb
            continue

        # ── 2. Large table route ──────────────────────────────────────────
        # chunk['content'] already IS the VDB content. Written by Stage 1:
        #   *Caption:* Table 3 - Efficacy Outcomes
        #   > 1. PURPOSE - The table presents OS, PFS and ORR across arms...
        #   > 4. STATISTICS - HR=0.62 (95% CI 0.45-0.84, p=0.002) for arm B...
        #   *Full table data available at: s3://bucket/doc/tables/p3_table_1.md*
        # Route standalone, use body directly.
        # s3_uri in metadata -> query layer fetches raw Markdown for precise answers.
        if is_large_table:
            flush()
            semantic_chunks.append(make_standalone(chunk, 'table_offloaded'))
            current_breadcrumb = breadcrumb
            continue

        # ── 3. Hard break: major section boundary ─────────────────────────
        if buffer and is_major_section_change(current_breadcrumb or '', breadcrumb):
            flush()

        # ── 4. Max guard ──────────────────────────────────────────────────
        before_header = next_is_header(idx)
        if buffer_size + chunk_size > max_size and buffer_size >= min_size:
            flush()

        # ── Add to buffer ─────────────────────────────────────────────────
        buffer.append(chunk)
        buffer_size        += chunk_size
        current_breadcrumb  = breadcrumb

        # ── 5. Target hit ─────────────────────────────────────────────────
        if buffer_size >= target_size and not before_header:
            flush()

    # ── 6. EOF + tail merge ───────────────────────────────────────────────
    # Merge small trailing buffers into the previous chunk rather than
    # emitting orphan chunks with very little content.
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
            last['chunk_ids'].extend(c['id']    for c in buffer)
            last['chunk_types'].extend(c['type'] for c in buffer)
            last['num_chunks'] += len(buffer)
            last['char_count']  = len(last['combined_content'])
            logger.debug(
                "Tail-merged %d chunk(s) into previous semantic chunk.", len(buffer)
            )
            buffer.clear()
            buffer_size = 0
        else:
            flush()
    else:
        flush()

    logger.info(
        "Chunking complete - %d atomic chunks -> %d semantic chunks",
        len(chunks), len(semantic_chunks),
    )
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

    Output schema per chunk:
      {
        "content":  "...",
        "metadata": {
          "breadcrumbs":       "Results > Adverse Events",
          "char_count":        1543,
          "num_atomic_chunks": 4,
          "chunk_types":       ["header", "paragraph", "list", "table"],

          # offloaded assets only:
          "type":    "table_offloaded" | "image_offloaded",
          "s3_uri":  "s3://bucket/doc/tables/p3_table_1.md",

          # debugging only (keep_ids=True):
          "chunk_ids": ["p3_table_1", ...]
        }
      }

    Notes:
      - chunk_types always included. Stage 3 uses it to decide enrichment operations
        (e.g. skip PII redaction for code/formula chunks).

      - type field ("table_offloaded" / "image_offloaded") included for offloaded
        assets so the query layer identifies chunks needing S3 hydration.

      - s3_uri included when present. Stage 5 stores it in Pinecone metadata.
        Query layer reads it to fetch raw assets:
          table_offloaded -> raw Markdown -> LLM gets full table for numeric answers
          image_offloaded -> PNG -> display / visual context
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
                'chunk_types':       chunk_types,
            },
        }

        # Tag offloaded assets so query layer knows to fetch from S3
        if 'table_offloaded' in chunk_types:
            out['metadata']['type'] = 'table_offloaded'
        elif 'image_offloaded' in chunk_types:
            out['metadata']['type'] = 'image_offloaded'

        # s3_uri: raw asset pointer for query-time retrieval.
        #   table_offloaded -> raw Markdown (.md) in S3
        #     query layer: fetch + pass to LLM -> precise numeric answer
        #   image_offloaded -> PNG in S3
        #     stored in Pinecone metadata for display / visual context
        if chunk.get('s3_uri'):
            out['metadata']['s3_uri'] = chunk['s3_uri']

        if keep_ids:
            out['metadata']['chunk_ids'] = chunk['chunk_ids']

        result.append(out)

    return result