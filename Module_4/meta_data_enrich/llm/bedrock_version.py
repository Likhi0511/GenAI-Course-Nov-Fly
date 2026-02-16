"""
enrich_pipeline_bedrock.py
--------------------------
AWS Bedrock-powered chunk enrichment pipeline using Claude Sonnet 4.
"""

import re
import json
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging & Stats
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

STATS = {
    'chunks_processed': 0,
    'bedrock_calls': 0,
    'bedrock_errors': 0,
    'entities_extracted': 0,
    'pii_replacements': 0,
    'input_tokens': 0,
    'output_tokens': 0,
}

# Local Regex for fast/free structured extraction
PATTERNS = {
    'monetary_values': re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([BMK])?'),
    'years': re.compile(r'(?:FY|CY)?\s*20\d{2}'),
}

# ---------------------------------------------------------------------------
# Bedrock Model IDs
# ---------------------------------------------------------------------------
BEDROCK_MODELS = {
    'claude-sonnet-4':    'us.anthropic.claude-sonnet-4-5-20251101-v1:0',
    'claude-sonnet-3-7':  'us.anthropic.claude-3-7-sonnet-20250219-v1:0',
    'claude-sonnet-3-5':  'us.anthropic.claude-3-5-sonnet-20241022-v2:0',
    'claude-haiku-3-5':   'us.anthropic.claude-3-5-haiku-20241022-v1:0',
}

DEFAULT_MODEL = 'claude-sonnet-4'

# ===========================================================================
# Bedrock Client Initialization
# ===========================================================================

def init_bedrock_client(
    region: str = 'us-east-1',
    profile: Optional[str] = None,
) -> Optional[object]:
    """
    Initialize a boto3 Bedrock Runtime client.

    Authentication is resolved in the standard AWS credential chain order:
      1. Explicit profile (--profile flag)
      2. Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      3. ~/.aws/credentials file
      4. IAM Instance Role / ECS Task Role
    """
    if not BOTO3_AVAILABLE:
        logger.error("boto3 not installed: pip install boto3")
        return None

    try:
        session_kwargs = {}
        if profile:
            session_kwargs['profile_name'] = profile

        session = boto3.Session(**session_kwargs)
        client = session.client('bedrock-runtime', region_name=region)
        logger.info(f"Bedrock client initialised | region={region} | profile={profile or 'default'}")
        return client
    except (BotoCoreError, Exception) as e:
        logger.error(f"Failed to init Bedrock client: {e}")
        return None


# ===========================================================================
# The "Intelligence" Call
# ===========================================================================

def analyze_chunk_with_bedrock(
    text: str,
    client,
    model_id: str,
) -> Dict:
    """
    Calls Bedrock Converse API with Claude Sonnet 4 to perform:
      - PII redaction (names, personal emails, phones, home addresses)
      - Named Entity Recognition (PERSON, ORG, DATE, GPE, MONEY)
      - Key phrase extraction (top-5 financial / business signals)

    Returns a parsed dict, or {} on any error.
    """
    system_prompt = (
        "You are a privacy expert and financial data analyst. "
        "Your responses must be valid JSON only — no markdown, no code fences, no commentary."
    )

    user_prompt = f"""Analyze the following text and return a single JSON object with exactly these three keys:

1. "redacted_text"
   - Redact ONLY highly sensitive individual identifiers:
     Personal Names, Personal Emails, Personal Phone Numbers, specific Home Addresses.
   - Use the format [REDACTED_TYPE] (e.g. [REDACTED_PERSON], [REDACTED_EMAIL]).
   - DO NOT REDACT:
     * Dates like "2025", "Q1", "January", or fiscal years.
     * Geographies like "USA", "Japan", or "Europe".
     * Company names (e.g. "Morgan Stanley", "Apple").
     * Generic professional roles (e.g. "Analyst", "Manager").
   - CONTEXT RULE: If a date refers to a person's birthday, redact it.
     If it is a report date or fiscal period, keep it.

2. "entities"
   An object with lists under these keys:
   - "PERSON"       — individual names
   - "ORGANIZATION" — companies or institutions
   - "DATE"         — temporal references such as "FY25" or "2024-11-20"
   - "GPE"          — countries, cities, or states
   - "MONEY"        — financial amounts such as "$5.5M"

3. "key_phrases"
   A list of the top 5 noun phrases that capture the core financial or business signal.

Text to analyse:
{text}"""

    try:
        response = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={
                "maxTokens": 1024,
                "temperature": 0.0,   # deterministic for data extraction
            },
        )

        # Track token usage when available
        usage = response.get('usage', {})
        STATS['input_tokens'] += usage.get('inputTokens', 0)
        STATS['output_tokens'] += usage.get('outputTokens', 0)

        STATS['bedrock_calls'] += 1

        raw_text = response['output']['message']['content'][0]['text']

        # Strip accidental markdown fences Claude might still emit
        raw_text = re.sub(r'^```(?:json)?\s*', '', raw_text.strip(), flags=re.IGNORECASE)
        raw_text = re.sub(r'\s*```$', '', raw_text.strip())

        return json.loads(raw_text)

    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"Bedrock ClientError [{error_code}]: {e}")
        STATS['bedrock_errors'] += 1
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from model response: {e}")
        STATS['bedrock_errors'] += 1
        return {}
    except Exception as e:
        logger.error(f"Unexpected Bedrock error: {e}")
        STATS['bedrock_errors'] += 1
        return {}


# ===========================================================================
# Processing Logic
# ===========================================================================

def enrich_chunk(chunk: Dict, client, model_id: str) -> Dict:
    """Enrich a single chunk with AI analysis + local regex extraction."""
    text = chunk.get('content') or chunk.get('text', '')
    if not text.strip():
        return chunk

    if 'metadata' not in chunk:
        chunk['metadata'] = {}

    # 1. AI analysis via Bedrock
    analysis = analyze_chunk_with_bedrock(text, client, model_id)

    if analysis:
        # --- Redaction ---
        redacted = analysis.get('redacted_text', text)
        if redacted and redacted != text:
            chunk['content_sanitised'] = redacted
            chunk['metadata']['pii_redacted'] = True
            STATS['pii_replacements'] += 1

        # --- Entities ---
        entities = analysis.get('entities', {})
        chunk['metadata']['entities'] = entities
        STATS['entities_extracted'] += sum(
            len(v) for v in entities.values() if isinstance(v, list)
        )

        # --- Key Phrases ---
        chunk['metadata']['key_phrases'] = analysis.get('key_phrases', [])

    # 2. Local regex (fast, free, deterministic)
    monetary = PATTERNS['monetary_values'].findall(text)
    chunk['metadata']['monetary_values'] = [
        f"${amt}{sfx}" if sfx else f"${amt}"
        for amt, sfx in monetary
    ]

    STATS['chunks_processed'] += 1
    return chunk


def run_pipeline(
    input_file: str,
    region: str,
    profile: Optional[str],
    model_alias: str,
    output_dir: Optional[str] = None,
):
    model_id = BEDROCK_MODELS.get(model_alias, BEDROCK_MODELS[DEFAULT_MODEL])
    logger.info(f"Model: {model_alias} -> {model_id}")

    client = init_bedrock_client(region=region, profile=profile)
    if not client:
        return

    input_path = Path(input_file).resolve()
    with open(input_path, 'r') as f:
        data = json.load(f)

    chunks = data.get('chunks', [])
    logger.info(f"Processing {len(chunks)} chunks via Bedrock...")

    enriched_chunks = [enrich_chunk(c, client, model_id) for c in chunks]

    # Output directory: explicit flag > same directory as input file
    out_dir = Path(output_dir).resolve() if output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / (input_path.stem + "_enriched_bedrock.json")
    with open(output_path, 'w') as f:
        json.dump({'chunks': enriched_chunks, 'stats': STATS}, f, indent=2)

    logger.info(f"Done. Saved to {output_path}")
    print(json.dumps(STATS, indent=2))


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bedrock/Claude Sonnet 4 chunk enrichment pipeline"
    )
    parser.add_argument(
        'input_file',
        help="Path to input JSON file with a 'chunks' list",
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        '--profile',
        default=None,
        help="AWS credential profile name (optional)",
    )
    parser.add_argument(
        '--model',
        default=DEFAULT_MODEL,
        choices=list(BEDROCK_MODELS.keys()),
        help=f"Bedrock model alias (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        '--output_dir',
        default=None,
        help="Directory to write enriched output (default: same directory as input file)",
    )
    args = parser.parse_args()

    run_pipeline(
        input_file=args.input_file,
        region=args.region,
        profile=args.profile,
        model_alias=args.model,
        output_dir=args.output_dir,
    )