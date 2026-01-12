"""
Prompt Advisor - Complete System in One File
Analyzes business problems and recommends the best prompt template and technique
"""

import os
import json
import re
import unicodedata
from typing import Dict, List
from openai import OpenAI
from dataclasses import dataclass


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


# ============================================================================
# MAIN ADVISOR CLASS
# ============================================================================

class PromptAdvisor:
    """Analyzes business problems and recommends templates and techniques"""

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.templates = TEMPLATES
        self.techniques = TECHNIQUES

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean text to handle Unicode and special characters"""
        if not text:
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

        return text.strip()

    def _build_system_prompt(self) -> str:
        """Build the system prompt with all templates and techniques"""
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

        return f"""You are an expert prompt engineering advisor. Analyze business problems and recommend the most appropriate prompt template and technique.

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

    def _build_deep_analysis_prompt(self) -> str:
        """Build system prompt for generating multiple recommendations"""
        templates_info = "\n".join([f"- {t.acronym}: {t.best_for}" for t in self.templates])
        techniques_info = "\n".join([f"- {t.name}: {t.best_for}" for t in self.techniques])

        return f"""You are an expert prompt engineering advisor. Generate 3 DIFFERENT combinations of templates and techniques for the given problem.

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

    def _build_judge_prompt(self, problem: str, options: List[Dict]) -> str:
        """Build prompt for LLM judge to evaluate options"""
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

        return f"""You are an expert judge evaluating prompt engineering approaches.

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

    def analyze_problem(self, business_problem: str, mode: str = "fast") -> Dict:
        """
        Analyze a problem and recommend template and technique

        Args:
            business_problem: Description of the business problem
            mode: "fast" for quick analysis, "deep" for comprehensive evaluation

        Returns:
            Dictionary with recommendations and reasoning
        """
        try:
            # Clean the text
            cleaned = self.clean_text(business_problem)

            if not cleaned:
                return {"error": "Problem description is empty"}

            if mode == "fast":
                # Fast mode: Single recommendation
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._build_system_prompt()},
                        {"role": "user", "content": f"Analyze this business problem:\n\n{cleaned}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7
                )

                result = json.loads(response.choices[0].message.content)
                result["mode"] = "fast"
                return result

            elif mode == "deep":
                # Deep mode: Generate multiple options
                print("🔍 Generating multiple options...")
                response1 = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._build_deep_analysis_prompt()},
                        {"role": "user", "content": f"Generate 3 different approaches for:\n\n{cleaned}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.9  # Higher creativity for diverse options
                )

                options_result = json.loads(response1.choices[0].message.content)
                options = options_result.get("options", [])

                # Use LLM as judge to evaluate
                print("⚖️  Evaluating options...")
                response2 = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an expert judge evaluating prompt engineering approaches."},
                        {"role": "user", "content": self._build_judge_prompt(cleaned, options)}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3  # Lower for consistent judging
                )

                judge_result = json.loads(response2.choices[0].message.content)

                # Combine results
                winner_num = judge_result["winner"]["option_number"]
                winner_option = options[winner_num - 1]

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

                return result

        except Exception as e:
            return {"error": f"Error: {str(e)}"}

    def format_recommendation(self, result: Dict) -> str:
        """Format the recommendation for display"""
        if "error" in result:
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
        return "\n".join(output)


# ============================================================================
# SIMPLE CLI INTERFACE
# ============================================================================

def main():
    """Simple command-line interface"""
    print("🎯 Prompt Advisor")
    print("=" * 80)

    # Get API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n⚠️  Set your API key:")
        print("export OPENAI_API_KEY='your-key-here'")
        api_key = input("\nOr enter it now: ").strip()
        if not api_key:
            print("❌ Cannot proceed without API key")
            return

    # Initialize
    print("\n🔧 Initializing advisor...")
    try:
        advisor = PromptAdvisor(api_key=api_key)
        print("✅ Ready!")
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    # Select mode
    print("\n📊 Select Analysis Mode:")
    print("1. ⚡ Fast (Quick single recommendation)")
    print("2. 🔬 Deep (Multiple options + LLM Judge evaluation)")

    mode_choice = input("\nEnter 1 or 2 (default: 1): ").strip()
    mode = "deep" if mode_choice == "2" else "fast"

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

    if not problem.strip():
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
    with open(filename, 'w') as f:
        f.write(f"Problem:\n{problem}\n\n")
        f.write(f"Mode: {mode.upper()}\n\n")
        f.write(advisor.format_recommendation(result))
    print(f"\n💾 Saved to: {filename}")


if __name__ == "__main__":
    main()