"""
Logger configuration for NL2SQL agent
"""

import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('nl2sql_agent.log')
    ]
)

logger = logging.getLogger(__name__)
