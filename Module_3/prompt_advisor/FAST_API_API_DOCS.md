# 🚀 Prompt Advisor REST API

Complete REST API for the Prompt Advisor. Call from Postman, cURL, or any HTTP client.

## 📦 Quick Start

### 1. Install Dependencies
```bash
pip install fastapi uvicorn pydantic openai
```

### 2. Run the API
```bash
# Development mode (auto-reload)
uvicorn api:app --reload

# Production mode
uvicorn api:app --host 0.0.0.0 --port 8000
```

### 3. Access Documentation
- **Interactive Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

---

## 🔑 Authentication

**OpenAI API Key Required**

Provide your OpenAI API key via:

**Option 1: HTTP Header (Recommended)**
```
X-API-Key: sk-your-openai-key-here
```

**Option 2: Environment Variable**
```bash
export OPENAI_API_KEY='sk-your-openai-key-here'
```

---

## 📍 API Endpoints

### **GET /** - Root
Get API information

```bash
curl http://localhost:8000/
```

**Response:**
```json
{
  "message": "Prompt Advisor API",
  "version": "1.0.0",
  "docs": "/docs",
  "endpoints": {
    "analyze": "/api/v1/analyze",
    "templates": "/api/v1/templates",
    "techniques": "/api/v1/techniques"
  }
}
```

---

### **GET /health** - Health Check
Check API status

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "templates_count": 10,
  "techniques_count": 7
}
```

---

### **GET /api/v1/templates** - List Templates
Get all available prompt templates

```bash
curl http://localhost:8000/api/v1/templates
```

**Response:**
```json
{
  "count": 10,
  "templates": [
    {
      "name": "Role-Task-Format",
      "acronym": "R-T-F",
      "components": ["Role", "Task", "Format"],
      "use_cases": ["Creative content", "Marketing"],
      "best_for": "Creative and content generation tasks"
    }
    // ... more templates
  ]
}
```

---

### **GET /api/v1/techniques** - List Techniques
Get all available prompt techniques

```bash
curl http://localhost:8000/api/v1/techniques
```

**Response:**
```json
{
  "count": 7,
  "techniques": [
    {
      "name": "Chain of Thought Prompting",
      "description": "Breaks down complex problems...",
      "use_cases": ["Math problems", "Logical reasoning"],
      "best_for": "Problems requiring multi-step reasoning"
    }
    // ... more techniques
  ]
}
```

---

### **POST /api/v1/analyze** - Analyze Problem
Main endpoint - analyze business problem and get recommendations

#### Request Body
```json
{
  "problem": "Build a recommendation system for products",
  "mode": "fast",
  "model": "gpt-4o"
}
```

**Fields:**
- `problem` (required): Your business problem (min 10 chars)
- `mode` (optional): `"fast"` or `"deep"` (default: `"fast"`)
- `model` (optional): OpenAI model (default: `"gpt-4o"`)

#### cURL Example - Fast Mode
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-key-here" \
  -d '{
    "problem": "Build a recommendation system for e-commerce products based on user behavior and purchase history",
    "mode": "fast"
  }'
```

#### cURL Example - Deep Mode
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-key-here" \
  -d '{
    "problem": "Design a complex multi-agent AI system for customer service",
    "mode": "deep"
  }'
```

#### Response - Fast Mode
```json
{
  "mode": "fast",
  "problem_analysis": {
    "complexity": "high",
    "requires_creativity": false,
    "requires_data_analysis": true,
    "has_constraints": true,
    "requires_step_by_step": true,
    "key_characteristics": [
      "Data-driven decision making",
      "Personalization required"
    ]
  },
  "recommended_template": {
    "name": "Define-Research-Execute-Analyse-Measure",
    "acronym": "D-R-E-A-M",
    "reasoning": "This framework is ideal for data-driven projects...",
    "application": "1. Define the recommendation goals..."
  },
  "recommended_technique": {
    "name": "Chain of Thought Prompting",
    "reasoning": "Provides transparent reasoning...",
    "application": "Include explicit step-by-step instructions..."
  },
  "example_prompt": "Using the D-R-E-A-M framework...",
  "metadata": {
    "mode": "fast",
    "model": "gpt-4o",
    "input_length": 95
  }
}
```

#### Response - Deep Mode
```json
{
  "mode": "deep",
  "problem_analysis": {
    "complexity": "high",
    "key_characteristics": [
      "Multiple approaches evaluated",
      "LLM-judged selection"
    ]
  },
  "all_options": [
    {
      "option_number": 1,
      "template": {"acronym": "D-R-E-A-M", "name": "..."},
      "technique": {"name": "Chain of Thought Prompting"},
      "reasoning": "...",
      "strengths": ["...", "..."],
      "weaknesses": ["...", "..."],
      "example_prompt": "..."
    }
    // ... 2 more options
  ],
  "evaluations": [
    {
      "option_number": 1,
      "scores": {
        "problem_fit": 9,
        "clarity": 8,
        "effectiveness": 9,
        "flexibility": 7
      },
      "total_score": 33,
      "analysis": "Strong match for data analysis needs..."
    }
    // ... evaluations for other options
  ],
  "recommended_template": {
    "acronym": "D-R-E-A-M",
    "name": "Define-Research-Execute-Analyse-Measure"
  },
  "recommended_technique": {
    "name": "Chain of Thought Prompting"
  },
  "winner_reasoning": "Selected for highest problem fit...",
  "example_prompt": "...",
  "metadata": {
    "mode": "deep",
    "model": "gpt-4o",
    "input_length": 95
  }
}
```

---

### **POST /api/v1/analyze/fast** - Quick Analysis
Convenience endpoint for fast mode

```bash
curl -X POST http://localhost:8000/api/v1/analyze/fast \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-key-here" \
  -d '{
    "problem": "Create a chatbot for customer support"
  }'
```

---

### **POST /api/v1/analyze/deep** - Deep Analysis
Convenience endpoint for deep mode

```bash
curl -X POST http://localhost:8000/api/v1/analyze/deep \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-key-here" \
  -d '{
    "problem": "Build a complex recommendation engine"
  }'
```

---

### **GET /api/v1/templates/{acronym}** - Get Specific Template
Get details for a specific template

```bash
curl http://localhost:8000/api/v1/templates/D-R-E-A-M
```

**Response:**
```json
{
  "name": "Define-Research-Execute-Analyse-Measure",
  "acronym": "D-R-E-A-M",
  "components": ["Define", "Research", "Execute", "Analyse", "Measure"],
  "use_cases": ["Product development", "Research projects"],
  "description": "Comprehensive problem-solving...",
  "best_for": "Data-driven projects requiring analysis"
}
```

---

### **GET /api/v1/techniques/{name}** - Get Specific Technique
Get details for a specific technique (partial match)

```bash
curl http://localhost:8000/api/v1/techniques/chain
```

**Response:**
```json
{
  "name": "Chain of Thought Prompting",
  "description": "Breaks down complex problems...",
  "use_cases": ["Math problems", "Logical reasoning"],
  "best_for": "Problems requiring multi-step reasoning"
}
```

---

## 📮 Postman Collection

### Import into Postman

1. **Create New Collection**: "Prompt Advisor API"
2. **Set Collection Variables**:
   - `base_url`: `http://localhost:8000`
   - `api_key`: `your-openai-api-key`

3. **Add Requests**:

#### Request 1: Health Check
```
GET {{base_url}}/health
```

#### Request 2: List Templates
```
GET {{base_url}}/api/v1/templates
```

#### Request 3: Analyze (Fast Mode)
```
POST {{base_url}}/api/v1/analyze
Headers:
  Content-Type: application/json
  X-API-Key: {{api_key}}
Body (raw JSON):
{
  "problem": "Build a recommendation system for products",
  "mode": "fast"
}
```

#### Request 4: Analyze (Deep Mode)
```
POST {{base_url}}/api/v1/analyze
Headers:
  Content-Type: application/json
  X-API-Key: {{api_key}}
Body (raw JSON):
{
  "problem": "Design a complex AI system",
  "mode": "deep"
}
```

---

## 🐍 Python Client Example

```python
import requests

# Configuration
BASE_URL = "http://localhost:8000"
API_KEY = "your-openai-api-key"

headers = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
}

# Fast analysis
response = requests.post(
    f"{BASE_URL}/api/v1/analyze",
    headers=headers,
    json={
        "problem": "Build a recommendation system",
        "mode": "fast"
    }
)

result = response.json()
print(f"Template: {result['recommended_template']['acronym']}")
print(f"Technique: {result['recommended_technique']['name']}")

# Deep analysis
response = requests.post(
    f"{BASE_URL}/api/v1/analyze/deep",
    headers=headers,
    json={
        "problem": "Complex AI system design",
        "model": "gpt-4o"
    }
)

result = response.json()
print(f"\nAll Options:")
for opt in result['all_options']:
    print(f"- {opt['template']['acronym']} + {opt['technique']['name']}")

print(f"\nWinner: {result['winner_reasoning']}")
```

---

## 🔧 Error Handling

### Common Error Responses

#### 401 - Unauthorized
```json
{
  "detail": "OpenAI API key required. Provide via X-API-Key header..."
}
```

#### 400 - Bad Request
```json
{
  "detail": "Mode must be 'fast' or 'deep'"
}
```

#### 404 - Not Found
```json
{
  "detail": "Template 'XYZ' not found"
}
```

#### 500 - Server Error
```json
{
  "detail": "Analysis failed: ..."
}
```

---

## 🚀 Deployment

### Docker
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prompt_advisor_complete.py api.py ./

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Run
```bash
docker build -t prompt-advisor-api .
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-xxx prompt-advisor-api
```

### Heroku
```bash
# Procfile
web: uvicorn api:app --host 0.0.0.0 --port $PORT
```

### AWS Lambda (with Mangum)
```python
from mangum import Mangum
handler = Mangum(app)
```

---

## 📊 Performance

**Fast Mode:**
- Response time: ~5 seconds
- API calls: 1
- Cost: ~$0.01-0.05 (gpt-4o)

**Deep Mode:**
- Response time: ~15 seconds
- API calls: 2
- Cost: ~$0.03-0.10 (gpt-4o)

---

## 🔒 Security

- Always use HTTPS in production
- Store API keys securely (environment variables)
- Rate limiting recommended for production
- Consider authentication for public APIs

---

## 📝 Notes

- API uses CORS middleware (allow all origins by default)
- Automatic Unicode handling for all inputs
- Interactive documentation at `/docs`
- Health check endpoint for monitoring
- Supports both fast and deep analysis modes

---

## 🆘 Troubleshooting

**API won't start:**
```bash
# Install dependencies
pip install fastapi uvicorn pydantic

# Check port availability
lsof -i :8000
```

**401 Error:**
```bash
# Set API key
export OPENAI_API_KEY='sk-...'

# Or use header
curl -H "X-API-Key: sk-..." ...
```

**Slow responses:**
- Use `gpt-4o-mini` for faster responses
- Use fast mode instead of deep mode
- Check network connectivity

---

**Your API is ready! 🎉**
