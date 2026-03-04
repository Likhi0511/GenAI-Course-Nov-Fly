"""
core/encoding.py — Unicode Encoding, Sanitisation & JSON I/O

Consolidated from:
  - utils.py           : read_json_robust(), write_json_utf8(), _ENCODING_FALLBACKS
  - load_embeddings_to_pinecone.py : patch_urllib3_latin1(), sanitize_for_transport(),
                                     sanitize_metadata()

This module is the SINGLE SOURCE OF TRUTH for all encoding-related logic
in the pipeline. Every stage and the Pinecone loader import from here.

Why centralise encoding?
  - The Latin-1 UnicodeEncodeError in Stage 5 had multiple attempted fixes
    scattered across Dockerfile env vars, sitecustomize.py, and inline hacks.
    None worked because they targeted the wrong code path (Python stdio vs
    urllib3 HTTP body encoding).
  - Consolidating here means one place to fix, test, and reason about.

Components:
  1. patch_urllib3_latin1()   — ROOT CAUSE fix for Pinecone Latin-1 errors
  2. sanitize_for_transport() — Defence-in-depth: dynamic Unicode → Latin-1 safe
  3. sanitize_metadata()      — Apply sanitisation to all metadata string values
  4. read_json_robust()       — Read JSON files regardless of byte encoding
  5. write_json_utf8()        — Write JSON with explicit UTF-8 + ensure_ascii=False

Author: Prudhvi | Thoughtworks
"""

import json as _json
import logging
import unicodedata

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. urllib3 Latin-1 Transport Patch  (ROOT CAUSE FIX)
# ===========================================================================
#
# WHY THIS IS NEEDED
# ------------------
# The Pinecone SDK serialises upsert payloads to a JSON *string* and passes
# it to urllib3 as the HTTP request body. urllib3 then calls body.encode()
# using Latin-1 (ISO-8859-1), which is the default charset for HTTP/1.1
# text bodies per RFC 2616 §3.7.1.
#
# Any Unicode character above U+00FF (e.g. smart quotes U+2019, em dash
# U+2014, Wingdings bullets U+F0B7) cannot be represented in Latin-1 and
# raises UnicodeEncodeError.
#
# Environment-level fixes (PYTHONIOENCODING, LANG, sitecustomize.py) only
# affect Python's stdio streams — they have NO effect on urllib3's internal
# body encoding path.
#
# THE FIX
# -------
# Intercept urllib3.HTTPConnectionPool.urlopen() and pre-encode any str
# body to UTF-8 bytes BEFORE urllib3 touches it. Once the body is already
# bytes, urllib3 sends it as-is — no Latin-1 encoding step.
#
# This is exactly what the error message itself suggests:
#   "Use body.encode('utf-8') if you want to send it encoded in UTF-8."
#
# The patch is idempotent — calling it multiple times is safe.
# ===========================================================================

_urllib3_patched = False


def patch_urllib3_latin1():
    """
    Monkey-patch urllib3 to pre-encode string bodies as UTF-8.

    This prevents UnicodeEncodeError for ANY non-Latin-1 character in
    Pinecone metadata — no character-level sanitisation needed.

    Safe to call multiple times (idempotent via _urllib3_patched flag).
    """
    global _urllib3_patched
    if _urllib3_patched:
        return

    try:
        import urllib3

        _original_urlopen = urllib3.HTTPConnectionPool.urlopen

        def _utf8_urlopen(self, method, url, body=None, headers=None, **kw):
            if isinstance(body, str):
                body = body.encode('utf-8')
                # Ensure Content-Type declares UTF-8 so the server decodes correctly
                if headers is None:
                    headers = {}
                ct = headers.get('Content-Type', headers.get('content-type', ''))
                if 'application/json' in ct and 'charset' not in ct:
                    headers['Content-Type'] = ct + '; charset=utf-8'
            return _original_urlopen(self, method, url, body=body, headers=headers, **kw)

        urllib3.HTTPConnectionPool.urlopen = _utf8_urlopen
        _urllib3_patched = True
        logger.info("urllib3 patched: string bodies will be encoded as UTF-8")
    except Exception as e:
        logger.warning(f"urllib3 patch failed ({e}) — falling back to metadata sanitisation")


# ===========================================================================
# 2. Generic Unicode Sanitiser  (DEFENCE IN DEPTH)
# ===========================================================================
#
# Even with the urllib3 patch above, we sanitise metadata as a safety net:
#   - Protects against future SDK changes that bypass urllib3
#   - Handles raw byte contamination (error #3: 0xa3 invalid start byte)
#   - Works even if the monkey-patch is disabled
#
# The sanitiser uses unicodedata.category() and unicodedata.name() to
# determine replacements DYNAMICALLY — zero hardcoded character mappings.
# Any character outside Latin-1 range is replaced based on its Unicode
# category (punctuation → ASCII punctuation, symbols → space, etc.).
# ===========================================================================

def sanitize_for_transport(text: str) -> str:
    """
    Ensure a string survives Latin-1 encoding by HTTP transport layers.

    Strategy:
      1. Handle raw bytes / mixed encoding (fixes 0xa3 invalid start byte)
      2. NFC-normalise Unicode
      3. For each char above U+00FF, use unicodedata to find the best
         Latin-1-safe replacement based on its Unicode category and name.

    This is fully generic — handles ANY Unicode character without hardcoding.

    Args:
        text: Input string (may contain non-Latin-1 characters)

    Returns:
        String where every character is in the Latin-1 range (U+0000–U+00FF)
    """
    if not text:
        return text

    # --- Step 1: Fix raw byte contamination ---
    # If somehow a bytes object arrives, decode it safely
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='replace')

    # Force a clean UTF-8 round-trip to catch surrogate pairs / stray bytes
    text = text.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')

    # --- Step 2: NFC normalise ---
    text = unicodedata.normalize('NFC', text)

    # --- Step 3: Fast path — if already Latin-1-safe, return immediately ---
    try:
        text.encode('latin-1')
        return text
    except UnicodeEncodeError:
        pass

    # --- Step 4: Character-by-character replacement for non-Latin-1 chars ---
    result = []
    for ch in text:
        cp = ord(ch)

        # Latin-1 safe — keep as-is
        if cp <= 0xFF:
            result.append(ch)
            continue

        # Try NFKD decomposition (handles ligatures, accented forms, etc.)
        decomposed = unicodedata.normalize('NFKD', ch)
        safe = ''.join(c for c in decomposed if ord(c) <= 0xFF)
        if safe:
            result.append(safe)
            continue

        # Category-based replacement using Unicode metadata (fully dynamic)
        name = unicodedata.name(ch, '')
        cat = unicodedata.category(ch)

        if cat == 'Pd' or 'DASH' in name or 'MINUS' in name:
            # Dash punctuation: em dash, en dash, figure dash, etc.
            result.append('-')
        elif 'QUOTATION' in name or 'APOSTROPHE' in name:
            # Any quotation mark variant → ASCII quote
            result.append("'" if 'SINGLE' in name or 'APOSTROPHE' in name else '"')
        elif 'BULLET' in name or 'DOT' in name and cat.startswith('P'):
            result.append('*')
        elif 'ELLIPSIS' in name:
            result.append('...')
        elif cat.startswith('P'):
            # Other punctuation → space
            result.append(' ')
        elif cat == 'Sc':
            # Currency symbols
            result.append('$' if 'DOLLAR' in name else ' ')
        elif cat.startswith('Z'):
            # Separators (line/paragraph/space variants)
            result.append(' ')
        elif cat.startswith('S'):
            # Other symbols
            result.append(' ')
        elif cat == 'Cf':
            # Format characters (zero-width joiners, BOM, etc.) → drop
            pass
        elif cat == 'Co':
            # Private Use Area (U+E000–U+F8FF) — commonly Wingdings bullets
            # in clinical/pharma PDFs. Map to asterisk (bullet equivalent).
            result.append('*')
        else:
            # Truly unknown: replace with Unicode replacement indicator
            result.append('?')

    return ''.join(result)


# ===========================================================================
# 3. Metadata Sanitiser
# ===========================================================================

def sanitize_metadata(meta: dict) -> dict:
    """
    Apply sanitize_for_transport() to every string value in a flat metadata dict.

    Pinecone metadata is flat key-value pairs — this iterates all values and
    sanitises strings. Non-string values (int, float, bool) pass through unchanged.
    """
    sanitised = {}
    for key, value in meta.items():
        if isinstance(value, str):
            sanitised[key] = sanitize_for_transport(value)
        else:
            sanitised[key] = value
    return sanitised


# ===========================================================================
# 4. Robust JSON Reader
# ===========================================================================

# Explicit fallback chain tried in order when auto-detection fails.
# latin-1 is ALWAYS last — it accepts every byte 0x00–0xFF without error,
# making it an unconditional safety net.
_ENCODING_FALLBACKS = ["utf-8", "utf-8-sig", "windows-1252", "latin-1"]


def read_json_robust(path: str) -> dict:
    """
    Read a JSON file safely regardless of its byte encoding.

    Strategy (four-pass):
      1. Read raw bytes — never raises, no encoding assumption
      2. charset-normalizer auto-detection (ships with requests/openai)
      3. Explicit fallback chain: utf-8 → utf-8-sig → windows-1252 → latin-1
      4. latin-1 + errors='replace' — unconditional last resort, never fails

    latin-1 can decode every possible byte value (0x00–0xFF maps 1:1 to
    Unicode codepoints U+0000–U+00FF) so step 4 is mathematically guaranteed
    to succeed. Any genuinely undecodable byte becomes U+FFFD (replacement char).

    A WARNING is logged when a non-UTF-8 encoding is used so you can trace
    which upstream stage wrote the file with the wrong encoding.

    Args:
        path: Path to the JSON file (str or Path).

    Returns:
        Parsed dict or list.

    Raises:
        FileNotFoundError  — file does not exist.
        json.JSONDecodeError — file is not valid JSON after decoding.
        (Never raises UnicodeDecodeError.)
    """
    raw = open(str(path), "rb").read()

    text = None
    detected_enc = None

    # Pass 1 — charset-normalizer (accurate, handles Windows-1252 vs Latin-1)
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best is not None:
            detected_enc = best.encoding
            text = str(best)
            logger.debug("read_json_robust: %s detected as %s", path, detected_enc)
    except ImportError:
        logger.debug("read_json_robust: charset-normalizer not available, using fallback chain")
    except Exception as exc:
        logger.debug("read_json_robust: charset-normalizer error (%s), using fallback chain", exc)

    # Pass 2 — explicit fallback chain
    if text is None:
        for enc in _ENCODING_FALLBACKS:
            try:
                text = raw.decode(enc)
                detected_enc = enc
                logger.debug("read_json_robust: %s decoded with fallback %s", path, enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue

    # Pass 3 — unconditional latin-1 with replacement (can never fail)
    if text is None:
        text = raw.decode("latin-1", errors="replace")
        detected_enc = "latin-1-replace"
        logger.warning("read_json_robust: %s — used latin-1 replace fallback", path)

    # Warn when the file was not clean UTF-8 so the bad write can be hunted down
    if detected_enc not in ("utf-8", "utf-8-sig", None):
        logger.warning(
            "read_json_robust: %s decoded as '%s' — "
            "an upstream stage wrote non-UTF-8 JSON. "
            "Check bare open() / json.dump() calls in the stage that produced this file.",
            path, detected_enc,
        )

    return _json.loads(text)


# ===========================================================================
# 5. UTF-8 JSON Writer
# ===========================================================================

def write_json_utf8(path: str, data, indent: int = 2) -> None:
    """
    Write data to a JSON file with UTF-8 encoding and ensure_ascii=False.

    ensure_ascii=False stores Unicode characters as real characters (e.g. ×)
    rather than escape sequences (\\u00d7). This keeps files human-readable
    AND prevents downstream readers from misidentifying the encoding.

    If you write  json.dump(data, f, indent=2)  without ensure_ascii=False,
    Python escapes every non-ASCII byte to \\uXXXX which is safe but makes
    the files larger and harder to inspect. More importantly, some third-party
    tools (older boto3 versions, some AWS SDK internals) may then decode the
    \\uXXXX escapes using the system default encoding instead of UTF-8,
    reintroducing the exact bytes that caused the decode crash.

    Args:
        path:   File path to write (str or Path).
        data:   Dict or list to serialise.
        indent: JSON indentation spaces (default 2).
    """
    with open(str(path), "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=indent, ensure_ascii=False)
