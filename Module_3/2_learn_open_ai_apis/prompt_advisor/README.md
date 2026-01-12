# 🎯 Intelligent Prompt Template & Technique Advisor

An AI-powered system that analyzes business problems and recommends the most appropriate **prompt template** and **prompt technique** using OpenAI's GPT models.

## 📋 Overview

This tool helps you choose the right prompting approach for your specific use case by analyzing your business problem and recommending:

1. **Prompt Template** - Structured frameworks like R-T-F, SOIVE, TAG, DREAM, etc.
2. **Prompt Technique** - Advanced methods like Chain of Thought, Tree of Thought, Self-Consistency, etc.

## 🌟 Features

- **Intelligent Analysis**: Uses GPT-4 to analyze problem characteristics
- **10 Prompt Templates**: Comprehensive coverage of popular frameworks
- **7 Prompt Techniques**: Advanced prompting methods
- **Detailed Reasoning**: Explains why each recommendation is appropriate
- **Example Prompts**: Generates concrete examples for your use case
- **Multiple Interfaces**: 
  - Command-line Python script
  - Interactive Streamlit web app
- **Export Options**: Download recommendations as JSON or text

## 📦 Installation

### Prerequisites

- Python 3.8 or higher
- OpenAI API key

### Setup

1. **Clone or download the files**

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Configure API key**:

   **Option 1: Environment Variable**
   ```bash
   export OPENAI_API_KEY='your-api-key-here'
   ```

   **Option 2: .env file**
   ```bash
   cp .env.example .env
   # Edit .env and add your API key
   ```

   **Option 3: Pass directly in code**
   ```python
   advisor = PromptAdvisor(api_key='your-api-key-here')
   ```

## 🚀 Usage

### Command Line Interface

Run the main script with example problems:

```bash
python prompt_advisor.py
```

This will analyze 4 example business problems and save detailed recommendations to text files.

### Streamlit Web Interface

Launch the interactive web app:

```bash
streamlit run app.py
```

Then open your browser to `http://localhost:8501`

### Programmatic Usage

```python
from prompt_advisor import PromptAdvisor

# Initialize
advisor = PromptAdvisor(api_key='your-key', model='gpt-4o')

# Analyze a problem
problem = """
We need to develop a customer churn prediction system 
that analyzes user behavior patterns, subscription history, 
and engagement metrics to identify at-risk customers.
"""

result = advisor.analyze_problem(problem)

# Get formatted output
formatted = advisor.format_recommendation(result)
print(formatted)

# Access specific parts
template = result['recommended_template']
technique = result['recommended_technique']
example = result['example_prompt']
```

## 📚 Available Templates

### 1. **R-T-F** (Role-Task-Format)
- **Components**: Role, Task, Format
- **Best for**: Creative content and marketing
- **Use cases**: Advertising, storytelling, content generation

### 2. **S-O-I-V-E** (Situation-Objective-Implementation-Vision-Execution)
- **Components**: Situation, Objective, Limitations, Vision, Execution
- **Best for**: Complex projects with constraints
- **Use cases**: Project management, feature development

### 3. **T-A-G** (Task-Action-Goal)
- **Components**: Task, Action, Goal
- **Best for**: Performance-oriented tasks
- **Use cases**: Team evaluation, goal tracking

### 4. **D-R-E-A-M** (Define-Research-Execute-Analyse-Measure)
- **Components**: Define, Research, Execute, Analyse, Measure
- **Best for**: Data-driven projects
- **Use cases**: Product development, research projects

### 5. **B-A-B** (Before-After-Bridge)
- **Components**: Task (Before), Action, Bridge (Outcome)
- **Best for**: Transformation initiatives
- **Use cases**: Problem-solution, improvement projects

### 6. **P-A-C-T** (Problem-Approach-Compromise-Test)
- **Components**: Problem, Approach, Compromise, Test
- **Best for**: Complex problems with trade-offs
- **Use cases**: Customer engagement, solution design

### 7. **C-A-R-E** (Context-Action-Result-Example)
- **Components**: Context, Action, Result, Example
- **Best for**: Narrative-driven content
- **Use cases**: Case studies, marketing campaigns

### 8. **F-O-C-U-S** (Frame-Outline-Conduct-Understand-Summarise)
- **Components**: Frame, Outline, Conduct, Understand, Summarise
- **Best for**: Campaigns requiring feedback
- **Use cases**: Marketing campaigns, research studies

### 9. **R-I-S-E** (Role-Input-Steps-Expectation)
- **Components**: Role, Input, Steps, Expectation
- **Best for**: Step-by-step strategic planning
- **Use cases**: Content strategy, multi-step processes

### 10. **M-I-N-D-S** (Map-Investigate-Navigate-Develop-Sustain)
- **Components**: Map, Investigate, Navigate, Develop, Sustain
- **Best for**: Strategic market planning
- **Use cases**: Market analysis, competitive research

## 🎓 Available Techniques

### 1. **Chain of Thought Prompting**
- Breaks down complex problems into step-by-step reasoning
- Best for: Math problems, logical reasoning, complex analysis

### 2. **Tree of Thought Prompting**
- Explores multiple reasoning paths simultaneously
- Best for: Creative problem solving, strategic planning

### 3. **Self-Consistency Prompting**
- Generates multiple responses and selects most consistent
- Best for: Tasks requiring high accuracy and reliability

### 4. **Maieutic Prompting**
- Uses Socratic questioning to refine responses
- Best for: Deep analysis, critical thinking

### 5. **Complexity-Based Prompting**
- Adjusts prompt complexity based on task difficulty
- Best for: Systems handling varied task complexity

### 6. **Least to Most Prompting**
- Solves problems from simple to complex progressively
- Best for: Educational contexts, skill building

### 7. **Self-Refine Prompting**
- Iteratively refines outputs through self-critique
- Best for: High-quality outputs requiring iterations

## 📊 Example Output

```
================================================================================
📋 PROMPT TEMPLATE & TECHNIQUE RECOMMENDATION
================================================================================

🔍 PROBLEM ANALYSIS
--------------------------------------------------------------------------------
Complexity Level: HIGH
Requires Creativity: ✗
Requires Data Analysis: ✓
Has Constraints: ✓
Requires Step-by-Step: ✓

Key Characteristics:
  • Data-driven decision making
  • Requires measurable outcomes
  • Multi-step process needed
  • Regulatory compliance required

✨ RECOMMENDED PROMPT TEMPLATE
--------------------------------------------------------------------------------
Template: Define-Research-Execute-Analyse-Measure (D-R-E-A-M)

Why This Template:
The D-R-E-A-M framework is ideal because it provides a comprehensive 
approach for data-driven projects. It ensures proper problem definition, 
thorough research, systematic execution, detailed analysis, and measurable 
outcomes - all critical for your requirements.

How to Apply:
1. DEFINE: Clearly state the problem and objectives
2. RESEARCH: Gather relevant data and potential solutions
3. EXECUTE: Implement the chosen approach
4. ANALYSE: Evaluate results against metrics
5. MEASURE: Quantify impact and success

🎯 RECOMMENDED PROMPT TECHNIQUE
--------------------------------------------------------------------------------
Technique: Chain of Thought Prompting

Why This Technique:
Chain of Thought is perfect for this problem because it requires transparent, 
step-by-step reasoning through complex analysis. This technique ensures the 
AI shows its work, making the decision-making process auditable and 
understandable.

How to Apply:
Include explicit instructions to "think step by step" and "show your reasoning" 
at each stage of the analysis.

📝 EXAMPLE PROMPT
--------------------------------------------------------------------------------
[Detailed example prompt using the recommended template and technique]
================================================================================
```

## 🎨 Streamlit Interface Features

The web interface provides:

- **Interactive Analysis**: Enter problems and get instant recommendations
- **Example Problems**: Pre-loaded examples for different domains
- **Visual Metrics**: See problem characteristics at a glance
- **Reference Guides**: Browse all templates and techniques
- **Export Options**: Download as JSON or formatted text
- **Model Selection**: Choose between different OpenAI models

## 🔧 Configuration

### Model Selection

You can use different OpenAI models:

```python
# Most capable (default)
advisor = PromptAdvisor(model='gpt-4o')

# Cost-effective
advisor = PromptAdvisor(model='gpt-4o-mini')

# Legacy models
advisor = PromptAdvisor(model='gpt-4-turbo')
advisor = PromptAdvisor(model='gpt-3.5-turbo')
```

### Temperature Settings

The system uses `temperature=0.7` for balanced creativity and consistency. You can modify this in the code if needed.

## 📝 Example Use Cases

### E-commerce Product Recommendations
```python
problem = """
Build an AI system that recommends products based on browsing history, 
past purchases, and similar customer profiles. Must explain recommendations 
and handle multiple product categories.
"""
# Likely recommendation: D-R-E-A-M template + Chain of Thought technique
```

### Customer Service Chatbot
```python
problem = """
Design a customer service chatbot for telecommunications that handles 
billing, technical support, and upgrades. Must escalate complex issues 
and maintain conversation context.
"""
# Likely recommendation: R-I-S-E template + Tree of Thought technique
```

### Marketing Campaign Planning
```python
problem = """
Create a marketing campaign for sustainable fashion targeting millennials. 
Need messaging, social media content, and engagement metrics.
"""
# Likely recommendation: F-O-C-U-S template + Self-Consistency technique
```

## 🤝 Contributing

This is an educational tool developed for learning purposes. Feel free to:

- Extend the template database
- Add new prompt techniques
- Improve the analysis logic
- Enhance the UI/UX

## 📄 License

This project is provided for educational purposes. Please ensure compliance with OpenAI's usage policies.

## 🙏 Acknowledgments

- Prompt templates based on best practices from the AI community
- Prompt techniques from research papers and industry practices
- Inspired by Denis Panjuta's prompt framework guide

## 📞 Support

For issues or questions:
1. Check the troubleshooting section below
2. Review OpenAI API documentation
3. Ensure your API key is valid and has credits

## 🐛 Troubleshooting

### API Key Issues
```bash
# Check if key is set
echo $OPENAI_API_KEY

# Set key in current session
export OPENAI_API_KEY='your-key'
```

### Import Errors
```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade
```

### Streamlit Port Conflicts
```bash
# Use different port
streamlit run app.py --server.port 8502
```

## 🔮 Future Enhancements

- [ ] Support for custom templates and techniques
- [ ] Multi-language support
- [ ] Integration with other LLM providers
- [ ] Prompt performance tracking
- [ ] A/B testing capabilities
- [ ] Template effectiveness analytics

---

**Built with ❤️ for the AI community**
