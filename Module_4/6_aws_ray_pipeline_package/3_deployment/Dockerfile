# Dockerfile for Ray Document Processing Pipeline
# 
# This image contains all dependencies for running the pipeline
# including Docling, OpenAI, Pinecone, and AWS integrations
#
# Author: Prudhvi
# Organization: Thoughtworks

FROM rayproject/ray:2.9.0-py39

# Set working directory
WORKDIR /app

# Install system dependencies
RUN sudo apt-get update && sudo apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    && sudo rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy all pipeline code
COPY .. /app/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV RAY_ADDRESS=auto

# Expose Ray ports
EXPOSE 6379 8265 10001

# Default command (can be overridden)
CMD ["python", "ray_orchestrator.py"]
