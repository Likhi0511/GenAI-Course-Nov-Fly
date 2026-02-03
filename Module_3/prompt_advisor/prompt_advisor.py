"""
Prompt Advisor - Complete System in One File
Analyzes business problems and recommends the best prompt template and technique

Enhanced with comprehensive logging for monitoring and debugging:
- Structured logging with timestamps and context
- OpenAI API request/response logging
- Performance timing for all operations
- Error tracking with stack traces
"""

import os
import json
import re
import unicodedata
from typing import Dict, List
from openai import OpenAI
from dataclasses import dataclass
import logging
import sys
import time
from datetime import datetime


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Configure structured logging for production-ready monitoring
# This provides detailed information about operations, API calls, and performance

# Create custom logger for the application
logger = logging.getLogger("prompt_advisor")
logger.setLevel(logging.INFO)

# Create console handler with structured formatting
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Define structured log format with timestamp, level, and context
# Format: timestamp | level | logger_name | message
formatter = logging.Formatter(
    fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(console_handler)

# Prevent log propagation to avoid duplicate logs
logger.propagate = False


# ============================================================================
# LOGGING UTILITIES
# ============================================================================

class LogContext:
    """
    Context manager for structured logging with timing information.

    This utility automatically logs the start and end of operations,
    including execution time. Useful for tracking performance and
    identifying bottlenecks.

    Example:
        with LogContext("analyze_problem", mode="fast"):
            result = advisor.analyze_problem(problem)
        # Automatically logs: Started analyze_problem and Completed analyze_problem (1.23s)
    """

    def __init__(self, operation: str, **context):
        """
        Initialize logging context.

        Args:
            operation (str): Name of the operation being logged
            **context: Additional context fields to include in logs
        """
        self.operation = operation
        self.context = context
        self.start_time = None

    def __enter__(self):
        """Log operation start and record start time."""
        self.start_time = time.time()
        context_str = " | ".join(f"{k}={v}" for k, v in self.context.items())
        logger.info(f"Started {self.operation} | {context_str}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Log operation completion with duration."""
        duration = time.time() - self.start_time
        context_str = " | ".join(f"{k}={v}" for k, v in self.context.items())

        if exc_type is None:
            # Operation succeeded
            logger.info(
                f"Completed {self.operation} | duration={duration:.3f}s | {context_str}"
            )
        else:
            # Operation failed
            logger.error(
                f"Failed {self.operation} | duration={duration:.3f}s | "
                f"error={exc_type.__name__}: {exc_val} | {context_str}"
            )

        # Don't suppress exceptions
        return False


def log_openai_request(operation: str, model: str, messages: List[Dict], **params):
    """
    Log OpenAI API request details.

    Args:
        operation (str): Type of operation (e.g., "fast_analysis", "deep_generation")
        model (str): Model being used
        messages (List[Dict]): Messages being sent to the API
        **params: Additional parameters (temperature, response_format, etc.)
    """
    # Calculate total tokens in messages (approximate)
    total_chars = sum(len(str(msg.get("content", ""))) for msg in messages)
    approx_tokens = total_chars // 4  # Rough estimate: 4 chars per token

    logger.info(
        f"OpenAI API Request | operation={operation} | model={model} | "
        f"messages_count={len(messages)} | approx_input_tokens={approx_tokens} | "
        f"temperature={params.get('temperature', 'default')} | "
        f"response_format={params.get('response_format', {}).get('type', 'text')}"
    )

    # Log message details (truncated for readability)
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        content_preview = content[:150] + "..." if len(content) > 150 else content
        logger.debug(
            f"  Message {i+1} | role={role} | length={len(content)} | "
            f"preview={content_preview}"
        )


def log_openai_response(operation: str, response, duration: float):
    """
    Log OpenAI API response details.

    Args:
        operation (str): Type of operation
        response: OpenAI API response object
        duration (float): Time taken for the API call
    """
    # Extract response details
    choice = response.choices[0]
    message_content = choice.message.content
    finish_reason = choice.finish_reason

    # Token usage information
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    total_tokens = usage.total_tokens if usage else 0

    logger.info(
        f"OpenAI API Response | operation={operation} | duration={duration:.3f}s | "
        f"finish_reason={finish_reason} | "
        f"prompt_tokens={prompt_tokens} | "
        f"completion_tokens={completion_tokens} | "
        f"total_tokens={total_tokens} | "
        f"response_length={len(message_content)}"
    )

    # Log response preview
    content_preview = message_content[:200] + "..." if len(message_content) > 200 else message_content
    logger.debug(f"  Response preview: {content_preview}")

    # Try to parse JSON and log structure
    try:
        parsed = json.loads(message_content)
        logger.debug(f"  Parsed JSON keys: {list(parsed.keys())}")
    except:
        logger.debug("  Response is not JSON")


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class PromptTemplate:
    name: str
    acronym: str
    components: List[str]
    use_cases: List[str]
    description: str
    best_for: str


@dataclass
class PromptTechnique:
    name: str
    description: str
    use_cases: List[str]
    best_for: str


# ============================================================================
# TEMPLATES DATABASE
# ============================================================================

TEMPLATES = [
    PromptTemplate(
        name="Role-Task-Format",
        acronym="R-T-F",
        components=["Role", "Task", "Format"],
        use_cases=["Creative content", "Marketing", "Advertising"],
        description="Define role, specify task, and set output format",
        best_for="Creative and content generation tasks"
    ),
    PromptTemplate(
        name="Situation-Objective-Implementation-Vision-Execution",
        acronym="S-O-I-V-E",
        components=["Situation", "Objective", "Limitations", "Vision", "Execution"],
        use_cases=["Project management", "Feature development", "Constrained projects"],
        description="Comprehensive project planning with constraints",
        best_for="Complex projects with tight deadlines and constraints"
    ),
    PromptTemplate(
        name="Task-Action-Goal",
        acronym="T-A-G",
        components=["Task", "Action", "Goal"],
        use_cases=["Performance evaluation", "Team assessment", "Goal tracking"],
        description="Define task, specify action, and set measurable goal",
        best_for="Performance-oriented tasks with clear metrics"
    ),
    PromptTemplate(
        name="Define-Research-Execute-Analyse-Measure",
        acronym="D-R-E-A-M",
        components=["Define", "Research", "Execute", "Analyse", "Measure"],
        use_cases=["Product development", "Research projects", "Data analysis"],
        description="Comprehensive problem-solving with research and measurement",
        best_for="Data-driven projects requiring analysis"
    ),
    PromptTemplate(
        name="Before-After-Bridge",
        acronym="B-A-B",
        components=["Task (Before)", "Action", "Bridge (Outcome)"],
        use_cases=["Problem-solution scenarios", "Improvement initiatives"],
        description="Show current state, desired state, and path to achieve it",
        best_for="Transformation and improvement initiatives"
    ),
    PromptTemplate(
        name="Problem-Approach-Compromise-Test",
        acronym="P-A-C-T",
        components=["Problem", "Approach", "Compromise", "Test"],
        use_cases=["Customer engagement", "Solution design", "Trade-offs"],
        description="Define problem, suggest approach, identify trade-offs, and test",
        best_for="Complex problems with trade-offs"
    ),
    PromptTemplate(
        name="Context-Action-Result-Example",
        acronym="C-A-R-E",
        components=["Context", "Action", "Result", "Example"],
        use_cases=["Storytelling", "Case studies", "Marketing campaigns"],
        description="Provide context, describe action, show results with examples",
        best_for="Narrative-driven content"
    ),
    PromptTemplate(
        name="Frame-Outline-Conduct-Understand-Summarise",
        acronym="F-O-C-U-S",
        components=["Frame", "Outline", "Conduct", "Understand", "Summarise"],
        use_cases=["Marketing campaigns", "Research studies", "Feedback analysis"],
        description="Comprehensive campaign framework with feedback loop",
        best_for="Campaigns requiring consumer feedback"
    ),
    PromptTemplate(
        name="Role-Input-Steps-Expectation",
        acronym="R-I-S-E",
        components=["Role", "Input", "Steps", "Expectation"],
        use_cases=["Content strategy", "Multi-step processes", "Planning"],
        description="Define role, provide input, outline steps, set expectations",
        best_for="Step-by-step strategic planning"
    ),
    PromptTemplate(
        name="Map-Investigate-Navigate-Develop-Sustain",
        acronym="M-I-N-D-S",
        components=["Map", "Investigate", "Navigate", "Develop", "Sustain"],
        use_cases=["Market analysis", "Competitive research", "Long-term strategy"],
        description="Comprehensive market planning from research to sustainability",
        best_for="Strategic market planning"
    ),
]

# Log templates loaded at module initialization
logger.info(f"Templates database loaded | count={len(TEMPLATES)}")


# ============================================================================
# TECHNIQUES DATABASE
# ============================================================================

TECHNIQUES = [
    PromptTechnique(
        name="Chain of Thought Prompting",
        description="Breaks down complex problems into step-by-step reasoning",
        use_cases=["Math problems", "Logical reasoning", "Complex analysis"],
        best_for="Problems requiring multi-step reasoning"
    ),
    PromptTechnique(
        name="Tree of Thought Prompting",
        description="Explores multiple reasoning paths simultaneously",
        use_cases=["Creative problem solving", "Strategic planning"],
        best_for="Problems with multiple solution paths"
    ),
    PromptTechnique(
        name="Self-Consistency Prompting",
        description="Generates multiple responses and selects most consistent",
        use_cases=["Validation", "Quality assurance", "Accuracy"],
        best_for="Tasks requiring high accuracy"
    ),
    PromptTechnique(
        name="Maieutic Prompting",
        description="Uses Socratic questioning to refine responses",
        use_cases=["Deep analysis", "Critical thinking"],
        best_for="Complex topics requiring deep exploration"
    ),
    PromptTechnique(
        name="Complexity-Based Prompting",
        description="Adjusts prompt complexity based on task difficulty",
        use_cases=["Adaptive systems", "Varied complexity"],
        best_for="Systems handling varied task complexity"
    ),
    PromptTechnique(
        name="Least to Most Prompting",
        description="Solves problems from simple to complex progressively",
        use_cases=["Learning", "Progressive problem solving"],
        best_for="Educational contexts or skill building"
    ),
    PromptTechnique(
        name="Self-Refine Prompting",
        description="Iteratively refines outputs through self-critique",
        use_cases=["Quality improvement", "Content polishing"],
        best_for="High-quality outputs requiring iterations"
    ),
]

# Log techniques loaded at module initialization
logger.info(f"Techniques database loaded | count={len(TECHNIQUES)}")


# ============================================================================
# MAIN ADVISOR CLASS
# ============================================================================

class PromptAdvisor:
    """Analyzes business problems and recommends templates and techniques"""

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        """
        Initialize the PromptAdvisor.

        Args:
            api_key (str): OpenAI API key (or use OPENAI_API_KEY env var)
            model (str): OpenAI model to use (default: gpt-4o)
        """
        logger.info(f"Initializing PromptAdvisor | model={model}")

        try:
            # Initialize OpenAI client
            self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
            self.model = model
            self.templates = TEMPLATES
            self.techniques = TECHNIQUES

            logger.info(
                f"PromptAdvisor initialized successfully | model={model} | "
                f"templates={len(self.templates)} | techniques={len(self.techniques)}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize PromptAdvisor | error={type(e).__name__}: {str(e)}")
            raise

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean text to handle Unicode and special characters.

        Args:
            text (str): Input text to clean

        Returns:
            str: Cleaned text with normalized Unicode and removed special characters
        """
        logger.debug(f"Cleaning text | input_length={len(text) if text else 0}")

        if not text:
            logger.debug("Text cleaning skipped | reason=empty_input")
            return text

        # Normalize Unicode
        text = unicodedata.normalize('NFKD', text)

        # Replace problematic characters
        replacements = {
            '\xa0': ' ', '\u200b': '', '\u2018': "'", '\u2019': "'",
            '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-',
            '\u2026': '...', '\u2032': "'", '\u2033': '"',
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        # Remove non-ASCII except common symbols
        text = re.sub(r'[^\x00-\x7F\u00A0-\u00FF]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)

        cleaned = text.strip()
        logger.debug(f"Text cleaned | output_length={len(cleaned)}")

        return cleaned

    def _build_system_prompt(self) -> str:
        """
        Build the system prompt with all templates and techniques.

        Returns:
            str: Complete system prompt for the LLM
        """
        logger.debug("Building system prompt for fast analysis")

        templates_info = "\n\n".join([
            f"**{t.acronym} ({t.name})**\n"
            f"Components: {', '.join(t.components)}\n"
            f"Best for: {t.best_for}"
            for t in self.templates
        ])

        techniques_info = "\n\n".join([
            f"**{t.name}**\n"
            f"Description: {t.description}\n"
            f"Best for: {t.best_for}"
            for t in self.techniques
        ])

        prompt = f"""You are an expert prompt engineering advisor. Analyze business problems and recommend the most appropriate prompt template and technique.

Available Prompt Templates:
{templates_info}

Available Prompt Techniques:
{techniques_info}

Analyze the problem and respond in JSON format:
{{
    "problem_analysis": {{
        "complexity": "low|medium|high",
        "requires_creativity": true|false,
        "requires_data_analysis": true|false,
        "has_constraints": true|false,
        "requires_step_by_step": true|false,
        "key_characteristics": ["list"]
    }},
    "recommended_template": {{
        "name": "Full name",
        "acronym": "ACRONYM",
        "reasoning": "Why this template",
        "application": "How to apply"
    }},
    "recommended_technique": {{
        "name": "Technique name",
        "reasoning": "Why this technique",
        "application": "How to apply"
    }},
    "example_prompt": "Complete example using template and technique"
}}"""

        logger.debug(f"System prompt built | length={len(prompt)}")
        return prompt

    def _build_deep_analysis_prompt(self) -> str:
        """
        Build system prompt for generating multiple recommendations.

        Returns:
            str: System prompt for deep analysis mode
        """
        logger.debug("Building system prompt for deep analysis")

        templates_info = "\n".join([f"- {t.acronym}: {t.best_for}" for t in self.templates])
        techniques_info = "\n".join([f"- {t.name}: {t.best_for}" for t in self.techniques])

        prompt = f"""You are an expert prompt engineering advisor. Generate 3 DIFFERENT combinations of templates and techniques for the given problem.

Available Templates:
{templates_info}

Available Techniques:
{techniques_info}

Generate 3 diverse recommendations and respond in JSON:
{{
    "options": [
        {{
            "option_number": 1,
            "template": {{"acronym": "...", "name": "..."}},
            "technique": {{"name": "..."}},
            "reasoning": "Why this combination works",
            "strengths": ["strength1", "strength2"],
            "weaknesses": ["weakness1", "weakness2"],
            "example_prompt": "Short example"
        }},
        // ... 2 more options
    ]
}}"""

        logger.debug(f"Deep analysis prompt built | length={len(prompt)}")
        return prompt

    def _build_judge_prompt(self, problem: str, options: List[Dict]) -> str:
        """
        Build prompt for LLM judge to evaluate options.

        Args:
            problem (str): Original business problem
            options (List[Dict]): List of options to evaluate

        Returns:
            str: Judge prompt with problem and options
        """
        logger.debug(f"Building judge prompt | options_count={len(options)}")

        options_text = ""
        for i, opt in enumerate(options, 1):
            options_text += f"""
Option {i}:
Template: {opt['template']['acronym']} - {opt['template']['name']}
Technique: {opt['technique']['name']}
Reasoning: {opt['reasoning']}
Strengths: {', '.join(opt['strengths'])}
Weaknesses: {', '.join(opt['weaknesses'])}

"""

        prompt = f"""You are an expert judge evaluating prompt engineering approaches.

PROBLEM:
{problem}

EVALUATE THESE OPTIONS:
{options_text}

Evaluate each option on these criteria (score 1-10):
1. Problem fit: How well does it match the problem requirements?
2. Clarity: How clear and actionable is the approach?
3. Effectiveness: How likely is it to produce good results?
4. Flexibility: How adaptable is it to variations?

Respond in JSON:
{{
    "evaluations": [
        {{
            "option_number": 1,
            "scores": {{
                "problem_fit": 8,
                "clarity": 9,
                "effectiveness": 8,
                "flexibility": 7
            }},
            "total_score": 32,
            "analysis": "Detailed analysis"
        }},
        // ... for all options
    ],
    "winner": {{
        "option_number": 1,
        "reasoning": "Why this is the best choice"
    }}
}}"""

        logger.debug(f"Judge prompt built | length={len(prompt)}")
        return prompt

    def analyze_problem(self, business_problem: str, mode: str = "fast") -> Dict:
        """
        Analyze a problem and recommend template and technique.

        Args:
            business_problem: Description of the business problem
            mode: "fast" for quick analysis, "deep" for comprehensive evaluation

        Returns:
            Dictionary with recommendations and reasoning
        """
        logger.info(f"=" * 80)
        logger.info(f"Starting problem analysis | mode={mode} | problem_length={len(business_problem)}")

        try:
            # Clean the text
            with LogContext("text_cleaning", input_length=len(business_problem)):
                cleaned = self.clean_text(business_problem)

            if not cleaned:
                logger.warning("Analysis aborted | reason=empty_problem_after_cleaning")
                return {"error": "Problem description is empty"}

            logger.info(f"Problem cleaned | original_length={len(business_problem)} | cleaned_length={len(cleaned)}")

            if mode == "fast":
                # Fast mode: Single recommendation
                logger.info("Running FAST mode analysis")

                # Build messages
                system_prompt = self._build_system_prompt()
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Analyze this business problem:\n\n{cleaned}"}
                ]

                # Log request
                log_openai_request(
                    operation="fast_analysis",
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    response_format={"type": "json_object"}
                )

                # Make API call with timing
                with LogContext("openai_api_call", api_operation="fast_analysis", model=self.model):
                    start_time = time.time()
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.7
                    )
                    api_duration = time.time() - start_time

                # Log response
                log_openai_response("fast_analysis", response, api_duration)

                # Parse result
                with LogContext("json_parsing", parse_operation="fast_analysis"):
                    result = json.loads(response.choices[0].message.content)

                result["mode"] = "fast"

                # Log recommendation summary
                template_acronym = result.get("recommended_template", {}).get("acronym", "unknown")
                technique_name = result.get("recommended_technique", {}).get("name", "unknown")
                logger.info(
                    f"Fast analysis completed | template={template_acronym} | "
                    f"technique={technique_name}"
                )

                return result

            elif mode == "deep":
                # Deep mode: Generate multiple options
                logger.info("Running DEEP mode analysis")

                # ============================================================
                # STEP 1: Generate Multiple Options
                # ============================================================
                print("🔍 Generating multiple options...")
                logger.info("Step 1: Generating multiple options")

                # Build messages for option generation
                deep_system_prompt = self._build_deep_analysis_prompt()
                messages1 = [
                    {"role": "system", "content": deep_system_prompt},
                    {"role": "user", "content": f"Generate 3 different approaches for:\n\n{cleaned}"}
                ]

                # Log request
                log_openai_request(
                    operation="deep_generation",
                    model=self.model,
                    messages=messages1,
                    temperature=0.9,
                    response_format={"type": "json_object"}
                )

                # Make API call with timing
                with LogContext("openai_api_call", api_operation="deep_generation", model=self.model):
                    start_time = time.time()
                    response1 = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages1,
                        response_format={"type": "json_object"},
                        temperature=0.9  # Higher creativity for diverse options
                    )
                    api_duration = time.time() - start_time

                # Log response
                log_openai_response("deep_generation", response1, api_duration)

                # Parse options
                with LogContext("json_parsing", parse_operation="deep_generation"):
                    options_result = json.loads(response1.choices[0].message.content)
                    options = options_result.get("options", [])

                logger.info(f"Options generated | count={len(options)}")

                # Log each option
                for i, opt in enumerate(options, 1):
                    template = opt.get("template", {}).get("acronym", "unknown")
                    technique = opt.get("technique", {}).get("name", "unknown")
                    logger.info(f"  Option {i} | template={template} | technique={technique}")

                # ============================================================
                # STEP 2: Use LLM as Judge to Evaluate
                # ============================================================
                print("⚖️  Evaluating options...")
                logger.info("Step 2: Evaluating options with LLM judge")

                # Build judge prompt and messages
                judge_prompt = self._build_judge_prompt(cleaned, options)
                messages2 = [
                    {"role": "system", "content": "You are an expert judge evaluating prompt engineering approaches."},
                    {"role": "user", "content": judge_prompt}
                ]

                # Log request
                log_openai_request(
                    operation="deep_evaluation",
                    model=self.model,
                    messages=messages2,
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )

                # Make API call with timing
                with LogContext("openai_api_call", api_operation="deep_evaluation", model=self.model):
                    start_time = time.time()
                    response2 = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages2,
                        response_format={"type": "json_object"},
                        temperature=0.3  # Lower for consistent judging
                    )
                    api_duration = time.time() - start_time

                # Log response
                log_openai_response("deep_evaluation", response2, api_duration)

                # Parse judge results
                with LogContext("json_parsing", parse_operation="deep_evaluation"):
                    judge_result = json.loads(response2.choices[0].message.content)

                # ============================================================
                # STEP 3: Combine Results
                # ============================================================
                logger.info("Step 3: Combining results and selecting winner")

                # Get winner
                # options = [0,1,2]
                # winner = 3 - 1 = 2
                winner_num = judge_result["winner"]["option_number"]
                winner_option = options[winner_num - 1]

                logger.info(
                    f"Winner selected | option_number={winner_num} | "
                    f"template={winner_option['template']['acronym']} | "
                    f"technique={winner_option['technique']['name']}"
                )

                # Log evaluation scores
                for eval_data in judge_result.get("evaluations", []):
                    opt_num = eval_data.get("option_number")
                    total_score = eval_data.get("total_score", 0)
                    logger.info(f"  Option {opt_num} | total_score={total_score}/40")

                # Format as standard result with additional deep analysis info
                result = {
                    "mode": "deep",
                    "problem_analysis": {
                        "complexity": "high",  # Deep mode for complex problems
                        "requires_creativity": True,
                        "requires_data_analysis": True,
                        "has_constraints": True,
                        "requires_step_by_step": True,
                        "key_characteristics": ["Multiple approaches evaluated", "LLM-judged selection"]
                    },
                    "recommended_template": winner_option["template"],
                    "recommended_technique": winner_option["technique"],
                    "all_options": options,
                    "evaluations": judge_result["evaluations"],
                    "winner_reasoning": judge_result["winner"]["reasoning"],
                    "example_prompt": winner_option["example_prompt"]
                }

                logger.info(
                    f"Deep analysis completed | winner_option={winner_num} | "
                    f"template={winner_option['template']['acronym']} | "
                    f"technique={winner_option['technique']['name']}"
                )

                return result

            else:
                logger.warning(f"Invalid mode specified | mode={mode} | valid_modes=['fast', 'deep']")
                return {"error": f"Invalid mode: {mode}. Use 'fast' or 'deep'"}

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed | error={str(e)}", exc_info=True)
            return {"error": f"Failed to parse API response: {str(e)}"}

        except Exception as e:
            logger.error(
                f"Analysis failed | mode={mode} | error={type(e).__name__}: {str(e)}",
                exc_info=True
            )
            return {"error": f"Error: {str(e)}"}

        finally:
            logger.info(f"=" * 80)

    def format_recommendation(self, result: Dict) -> str:
        """
        Format the recommendation for display.

        Args:
            result (Dict): Analysis result dictionary

        Returns:
            str: Formatted recommendation text
        """
        logger.debug("Formatting recommendation for display")

        if "error" in result:
            logger.debug(f"Formatting error message | error={result['error']}")
            return f"❌ {result['error']}"

        output = []
        output.append("=" * 80)
        output.append(f"📋 PROMPT RECOMMENDATION ({result.get('mode', 'fast').upper()} MODE)")
        output.append("=" * 80)

        # Analysis
        analysis = result.get("problem_analysis", {})
        output.append("\n🔍 PROBLEM ANALYSIS")
        output.append(f"Complexity: {analysis.get('complexity', 'N/A').upper()}")
        output.append(f"Creativity: {'✓' if analysis.get('requires_creativity') else '✗'}")
        output.append(f"Data Analysis: {'✓' if analysis.get('requires_data_analysis') else '✗'}")
        output.append(f"Constraints: {'✓' if analysis.get('has_constraints') else '✗'}")

        # Deep mode: Show all options
        if result.get("mode") == "deep" and result.get("all_options"):
            output.append("\n📊 ALL OPTIONS EVALUATED")
            output.append("-" * 80)
            for i, opt in enumerate(result["all_options"], 1):
                eval_data = result["evaluations"][i-1] if result.get("evaluations") else None
                output.append(f"\nOption {i}: {opt['template']['acronym']} + {opt['technique']['name']}")
                if eval_data:
                    output.append(f"Score: {eval_data['total_score']}/40")
                    output.append(f"Analysis: {eval_data['analysis']}")

        # Template
        template = result.get("recommended_template", {})
        output.append(f"\n✨ RECOMMENDED TEMPLATE: {template.get('acronym')}")
        output.append(f"{template.get('name')}")
        if result.get("mode") == "deep":
            output.append(f"\n🏆 Why Winner: {result.get('winner_reasoning')}")
        else:
            output.append(f"\nWhy: {template.get('reasoning', 'N/A')}")
            output.append(f"\nHow: {template.get('application', 'N/A')}")

        # Technique
        technique = result.get("recommended_technique", {})
        output.append(f"\n🎯 RECOMMENDED TECHNIQUE")
        output.append(f"{technique.get('name')}")
        if result.get("mode") == "fast":
            output.append(f"\nWhy: {technique.get('reasoning', 'N/A')}")
            output.append(f"\nHow: {technique.get('application', 'N/A')}")

        # Example
        if result.get("example_prompt"):
            output.append("\n📝 EXAMPLE PROMPT")
            output.append("-" * 80)
            output.append(result.get("example_prompt"))

        output.append("\n" + "=" * 80)

        formatted_output = "\n".join(output)
        logger.debug(f"Recommendation formatted | output_length={len(formatted_output)}")

        return formatted_output


# ============================================================================
# SIMPLE CLI INTERFACE
# ============================================================================

def main():
    """Simple command-line interface"""
    logger.info("=" * 80)
    logger.info("Starting Prompt Advisor CLI")
    logger.info("=" * 80)

    print("🎯 Prompt Advisor")
    print("=" * 80)

    # Get API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("API key not found in environment")
        print("\n⚠️  Set your API key:")
        print("export OPENAI_API_KEY='your-key-here'")
        api_key = input("\nOr enter it now: ").strip()
        if not api_key:
            logger.error("CLI aborted | reason=no_api_key")
            print("❌ Cannot proceed without API key")
            return
        logger.info("API key provided via user input")
    else:
        logger.info("API key found in environment")

    # Initialize
    print("\n🔧 Initializing advisor...")
    try:
        advisor = PromptAdvisor(api_key=api_key)
        print("✅ Ready!")
    except Exception as e:
        logger.error(f"CLI initialization failed | error={type(e).__name__}: {str(e)}")
        print(f"❌ Error: {e}")
        return

    # Select mode
    print("\n📊 Select Analysis Mode:")
    print("1. ⚡ Fast (Quick single recommendation)")
    print("2. 🔬 Deep (Multiple options + LLM Judge evaluation)")

    mode_choice = input("\nEnter 1 or 2 (default: 1): ").strip()
    mode = "deep" if mode_choice == "2" else "fast"

    logger.info(f"Mode selected | mode={mode} | user_choice={mode_choice}")

    if mode == "deep":
        print("\n🔬 Deep Analysis Mode selected:")
        print("  • Generates 3 different approaches")
        print("  • LLM judges each on 4 criteria")
        print("  • Selects best option")
        print("  • Takes ~15 seconds, 2 API calls")
    else:
        print("\n⚡ Fast Mode selected:")
        print("  • Single recommendation")
        print("  • Takes ~5 seconds, 1 API call")

    # Get problem
    print("\n📝 Enter your business problem (Ctrl+D when done):")
    print("-" * 80)

    lines = []
    try:
        while True:
            lines.append(input())
    except EOFError:
        pass

    problem = "\n".join(lines)

    logger.info(f"Problem received from user | length={len(problem)}")

    if not problem.strip():
        logger.warning("CLI aborted | reason=empty_problem")
        print("❌ No problem provided")
        return

    # Analyze
    mode_label = "🔬 Deep" if mode == "deep" else "⚡ Fast"
    print(f"\n{mode_label} analyzing...")

    result = advisor.analyze_problem(problem, mode=mode)

    # Display
    print("\n" + advisor.format_recommendation(result))

    # Save
    filename = f"recommendation_{mode}.txt"
    logger.info(f"Saving recommendation to file | filename={filename}")

    try:
        with open(filename, 'w') as f:
            f.write(f"Problem:\n{problem}\n\n")
            f.write(f"Mode: {mode.upper()}\n\n")
            f.write(advisor.format_recommendation(result))

        logger.info(f"Recommendation saved successfully | filename={filename}")
        print(f"\n💾 Saved to: {filename}")

    except Exception as e:
        logger.error(f"Failed to save recommendation | filename={filename} | error={str(e)}")
        print(f"\n⚠️  Failed to save: {e}")


if __name__ == "__main__":
    main()