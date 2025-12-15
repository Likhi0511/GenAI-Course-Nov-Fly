"""
Configuration module for NL2SQL agent
Provides shared instances of LLM and Store (following the pattern from your example)
"""

import os
import logging
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pinecone_store import PineconeStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize LLM
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0
)

# Initialize embeddings
embeddings = OpenAIEmbeddings(
    model='text-embedding-3-small'
)

# Initialize Pinecone store (global singleton)
store = PineconeStore(
    index_name='nl2sql-semantic-memory',
    embeddings=embeddings
)

logger.info("=" * 70)
logger.info("NL2SQL Configuration Initialized")
logger.info("=" * 70)
logger.info(f"  LLM Model: gpt-4")
logger.info(f"  Embedding Model: text-embedding-3-small")
logger.info(f"  Pinecone Index: nl2sql-semantic-memory")
logger.info("=" * 70)