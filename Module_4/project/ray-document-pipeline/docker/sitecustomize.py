"""
sitecustomize.py — injected by Dockerfile to force UTF-8 I/O on every
Python interpreter that starts inside this container, including Ray workers.

ROOT CAUSE THIS FIXES
---------------------
Clinical/pharma PDFs commonly contain Windows PUA (Private Use Area)
characters — e.g. U+F0B7 (Wingdings bullet) — that Docling correctly
preserves in extracted text. When this text flows into Pinecone metadata
and the HTTP transport layer (urllib3 / httpx) serialises the request body,
it may attempt Latin-1 encoding and raise:

    UnicodeEncodeError: 'latin-1' codec can't encode character '\\uf0b7'
    in position 134109: Body ('\\uf0b7') is not valid Latin-1.
    Use body.encode('utf-8') if you want to send it encoded in UTF-8.

Forcing UTF-8 at the interpreter level tells Python's I/O stack and the
underlying C library to use UTF-8 for all text operations, which propagates
into the HTTP client's string-handling codepath.

NOTE: load_embeddings_to_pinecone.py sanitize_text() provides a second line
of defence at the application level (named PUA replacements + latin-1
encode/ignore fallback). Both layers together make the pipeline robust
against any Unicode surprises from future document sources.
"""
import sys
import io


def _ensure_utf8(stream, name):
    """Re-wrap a stdio stream in UTF-8 if it is not already."""
    if stream is None:
        return
    try:
        if hasattr(stream, "buffer") and getattr(stream, "encoding", "").lower() != "utf-8":
            object.__setattr__(
                sys, name,
                io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
            )
    except Exception:
        pass  # Never crash sitecustomize — fail silently


_ensure_utf8(sys.stdin,  "stdin")
_ensure_utf8(sys.stdout, "stdout")
_ensure_utf8(sys.stderr, "stderr")