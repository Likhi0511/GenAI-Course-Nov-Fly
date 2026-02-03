from typing import Optional, Literal

from fastapi import FastAPI
from openai import BaseModel
from pydantic import Field


class AnalyzeRequest(BaseModel):
    """
    Request model for the analyze endpoint.

    This Pydantic model defines the structure and validation rules for
    incoming analysis requests. FastAPI automatically validates requests
    against this schema and returns 422 errors for invalid data.

    Attributes:
        problem (str): The business problem to analyze (minimum 10 characters).
                      This ensures users provide meaningful problem descriptions.
        mode (str): Analysis mode - either 'fast' or 'deep'.
                   Fast mode gives quick single recommendation.
                   Deep mode generates multiple options with LLM judge.
                   Defaults to 'fast' for backwards compatibility.
        model (str): OpenAI model to use for analysis.
                    Options: gpt-4o, gpt-4o-mini, gpt-3.5-turbo, etc.
                    Defaults to 'gpt-4o' for best quality.

    Example:
        {
            "problem": "Build a recommendation system for products",
            "mode": "fast",
            "model": "gpt-4o"
        }
    """
    # Problem description field with validation
    # Field(...) means this is required (no default value)
    # min_length ensures meaningful input
    problem: str = Field(
        ...,  # Required field indicator
        description="Business problem to analyze",
        min_length=10  # Minimum 10 characters to ensure quality input
    )

    # Analysis mode field with default value
    mode: Literal["fast", "deep"] = Field(
        default="fast",  # Default to fast mode if not specified
        description="Analysis mode: 'fast' or 'deep'"
    )

    # OpenAI model selection with default
    model: str = Field(
        default="gpt-4o",  # Default to best model
        description="OpenAI model to use"
    )

    # Configuration class for Pydantic model
    class Config:
        # Example data shown in API documentation
        json_schema_extra = {
            "example": {
                "problem": "Build a recommendation system for e-commerce products based on user behavior",
                "mode": "fast",
                "model": "gpt-4o"
            }
        }



app = FastAPI(
    title="Prompt Advisor API",  # API name shown in documentation
    description="Analyze business problems and get AI-powered prompt template and technique recommendations",
    version="1.0.0"  # API version for tracking changes
)

@app.post('/api/v1/analyze')
def analyze(request: AnalyzeRequest):
    print(request)
    return {"status": "ok"}


# This block only runs when the file is executed directly (not imported)
# Allows running the API with: python main.py
if __name__ == "__main__":
    # Import uvicorn server
    import uvicorn

    # Run the FastAPI application
    # host="0.0.0.0" makes it accessible from other machines
    # port=8000 is the default HTTP port for the API
    uvicorn.run(
        app,  # FastAPI application instance
        host="0.0.0.0",  # Listen on all network interfaces
        port=8000  # Port number
    )