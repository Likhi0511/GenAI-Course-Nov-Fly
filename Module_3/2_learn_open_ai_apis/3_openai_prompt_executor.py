"""
OpenAI API Prompt Executor - Comprehensive Learning Tool

This program demonstrates professional patterns for interacting with OpenAI APIs.
It covers all major prompt engineering techniques with working examples that can
be used as templates for production systems.

Each example is self-contained and demonstrates a specific pattern that solves
real-world problems in classification, content generation, data extraction,
conversation management, and structured output generation.


Prompt Engineering Patterns Explained
--------------------------------------------------------------------------------

Pattern 1: Simple Prompt
    Single user message with no context or history.
    Best for: One-off questions, quick tasks, standalone requests.
    Example: "Explain quantum computing in simple terms."

Pattern 2: System Prompt
    Defines AI behavior, personality, or constraints before user input.
    Best for: Consistent tone, role-playing, safety rules, domain expertise.
    Example: System="You are a medical expert" + User="Explain symptoms"

Pattern 3: Multi-Turn Conversation
    Maintains context across multiple exchanges.
    Best for: Chatbots, interviews, guided workflows, progressive disclosure.
    Example: Booking system that remembers what user already said.

Pattern 4: Structured JSON Output
    Forces response into machine-readable format.
    Best for: APIs, automation, data pipelines, agent systems.
    Example: Extract entities and return as {"name": "...", "date": "..."}.

Pattern 5: Streaming Response
    Delivers output incrementally as it generates.
    Best for: Chat interfaces, long responses, better user experience.
    Example: ChatGPT-style interfaces where text appears progressively.

Pattern 6: Few-Shot Learning
    Teaches by example rather than explanation.
    Best for: Custom formatting, unique classifications, pattern matching.
    Example: Show 3 input-output pairs, then process new input.

Pattern 7: Chain-of-Thought
    Asks AI to show reasoning steps before final answer.
    Best for: Math, logic, debugging, transparency, verification.
    Example: "Calculate dosage. Show your work step by step."

Pattern 8: COSTAR Framework
    Enterprise prompt structure for production consistency.
    Best for: Business systems, team alignment, quality control.
    Example: Explicitly define Context, Objective, Style, Tone, Audience, Format.

Pattern 9: Batch Processing
    Process multiple similar items efficiently.
    Best for: Data analysis, bulk operations, consistency checks.
    Example: Classify sentiment for 1000 reviews.

Pattern 10: Classification
    Categorize input into predefined groups.
    Best for: Routing, triage, sentiment analysis, content moderation.
    Example: "Is this email SPAM, URGENT, or NORMAL?"

--------------------------------------------------------------------------------
"""

import os
import json
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()


class OpenAIPromptExecutor:
    """
    Production-ready wrapper for OpenAI API calls.

    This class encapsulates common prompt engineering patterns with proper
    error handling, type hints, and documentation. Each method represents
    a proven pattern that can be copied into production code.

    Design principles:
        - Fail fast with clear error messages
        - Return simple types (str, dict) for easy integration
        - Provide sensible defaults for all parameters
        - Include docstrings with usage examples
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the OpenAI client.

        The API key can be provided directly or read from environment variable.
        If neither is available, initialization fails immediately with clear
        error message.

        Args:
            api_key (str, optional):
                OpenAI API key. If None, reads from OPENAI_API_KEY env variable.

        Raises:
            ValueError: If no API key is found in either location.

        Example:
            executor = OpenAIPromptExecutor()
            executor = OpenAIPromptExecutor(api_key="sk-...")
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Either:\n"
                "  1. Set OPENAI_API_KEY environment variable, or\n"
                "  2. Pass api_key parameter to constructor"
            )

        self.client = OpenAI(api_key=self.api_key)

    def execute_simple_prompt(
        self,
        prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """
        Execute a simple prompt with no conversation history.

        This is the most basic pattern. Use it for one-off questions where
        there is no need to maintain context or define specific AI behavior.

        Args:
            prompt (str):
                The question or instruction for the AI.
            model (str, default="gpt-4o"):
                OpenAI model to use. Options: gpt-4o, gpt-4o-mini, gpt-4-turbo
            temperature (float, default=0.7):
                Controls randomness. 0.0=deterministic, 2.0=very random
            max_tokens (int, default=1000):
                Maximum length of response in tokens (roughly 750 words)

        Returns:
            str: The AI-generated response text

        Example:
            executor = OpenAIPromptExecutor()
            answer = executor.execute_simple_prompt(
                "What is the capital of France?",
                temperature=0.0
            )
            print(answer)  # "The capital of France is Paris."
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content

        except Exception as e:
            return f"Error executing prompt: {str(e)}"

    def execute_with_system_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.7
    ) -> str:
        """
        Execute a prompt with system-level behavior instructions.

        The system prompt defines HOW the AI should behave (role, tone, rules).
        The user prompt defines WHAT the AI should respond to (the task).

        This pattern is essential for maintaining consistent behavior across
        multiple user interactions in production systems.

        Args:
            system_prompt (str):
                Instructions that define AI behavior. Examples:
                - "You are a helpful customer service agent."
                - "You are a Python expert. Provide code examples."
                - "You are a medical professional. Always cite sources."
            user_prompt (str):
                The actual user question or task.
            model (str, default="gpt-4o"):
                OpenAI model name
            temperature (float, default=0.7):
                Controls randomness

        Returns:
            str: AI-generated response following system instructions

        Example:
            executor = OpenAIPromptExecutor()
            response = executor.execute_with_system_prompt(
                system_prompt="You are a professional technical writer.",
                user_prompt="Explain recursion to a beginner."
            )

        Best Practices:
            - Keep system prompts clear and specific
            - Test with multiple user inputs to verify consistency
            - Use system prompts for safety rules and constraints
            - Don't repeat system prompt in every conversation turn
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature
            )
            return response.choices[0].message.content

        except Exception as e:
            return f"Error executing prompt: {str(e)}"

    def execute_conversation(
        self,
        conversation_history: List[Dict[str, str]],
        model: str = "gpt-4o",
        temperature: float = 0.7
    ) -> tuple[str, List[Dict[str, str]]]:
        """
        Execute a multi-turn conversation with full context preservation.

        The AI has no built-in memory. You must include the entire conversation
        history in every API call. This method manages that pattern and returns
        both the response and updated history.

        Args:
            conversation_history (List[Dict[str, str]]):
                List of message dictionaries with 'role' and 'content' keys.
                Roles: 'system', 'user', 'assistant'
            model (str, default="gpt-4o"):
                OpenAI model name
            temperature (float, default=0.7):
                Controls randomness

        Returns:
            tuple: (response_text, updated_conversation_history)
                The updated history includes the new assistant response

        Example:
            executor = OpenAIPromptExecutor()

            # Initialize conversation
            history = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What's the weather like?"}
            ]

            # Get first response
            response, history = executor.execute_conversation(history)
            print(response)

            # Continue conversation
            history.append({"role": "user", "content": "What about tomorrow?"})
            response, history = executor.execute_conversation(history)
            print(response)  # AI remembers we were talking about weather

        Memory Management:
            - Each API call costs tokens based on full history length
            - For long conversations, consider trimming old messages
            - Keep system message and last 5-10 turns for context
            - Store full history in database for audit trails

        Common Pattern for Chat Apps:
            while True:
                user_input = get_user_input()
                history.append({"role": "user", "content": user_input})
                response, history = executor.execute_conversation(history)
                display_to_user(response)
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=conversation_history,
                temperature=temperature
            )

            assistant_message = response.choices[0].message.content

            # Append AI response to conversation history
            conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message, conversation_history

        except Exception as e:
            return f"Error: {str(e)}", conversation_history

    def execute_with_json_output(
        self,
        prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        """
        Execute a prompt and force structured JSON output.

        This pattern is critical for systems that need machine-readable responses.
        The AI will only return valid JSON, making it safe to parse and use in
        automated workflows.

        Args:
            prompt (str):
                Prompt that requests JSON output. Must mention "JSON" in prompt.
            model (str, default="gpt-4o"):
                OpenAI model name
            temperature (float, default=0.0):
                Set to 0 for deterministic output in production systems

        Returns:
            Dict[str, Any]: Parsed JSON response as Python dictionary

        Example:
            executor = OpenAIPromptExecutor()

            prompt = '''
            Extract order details from this text and return JSON:
            "John ordered 2 laptops on Jan 15 for $2000"

            Return JSON with: customer_name, quantity, product, date, amount
            '''

            result = executor.execute_with_json_output(prompt)
            print(result["customer_name"])  # "John"
            print(result["amount"])          # 2000

        Critical Requirements:
            1. Always mention "JSON" in your prompt
            2. Specify the exact fields you want in the JSON
            3. Set temperature=0.0 for production consistency
            4. Handle parsing errors in your calling code

        Common Use Cases:
            - Data extraction from 2_unstructured text
            - Structured classification with multiple attributes
            - API responses that feed other systems
            - Agent outputs that trigger downstream actions

        Error Handling:
            If JSON parsing fails, returns {"error": "error message"}
            Always check for "error" key in response before using data
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except json.JSONDecodeError as e:
            return {"error": f"JSON parsing failed: {str(e)}"}
        except Exception as e:
            return {"error": f"API call failed: {str(e)}"}

    def execute_streaming(
        self,
        prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.7
    ):
        """
        Stream the response incrementally as it's generated.

        Streaming provides better user experience for chat applications by
        showing responses progressively rather than waiting for completion.

        Args:
            prompt (str):
                User prompt
            model (str, default="gpt-4o"):
                OpenAI model name
            temperature (float, default=0.7):
                Controls randomness

        Yields:
            str: Text chunks as they arrive from the API

        Example:
            executor = OpenAIPromptExecutor()

            # Display response as it generates
            for chunk in executor.execute_streaming("Write a story about AI"):
                print(chunk, end='', flush=True)
            print()  # New line after complete response

        Usage in Web Applications:
            Use with Server-Sent Events (SSE) or WebSockets to stream to browser

            @app.route('/chat')
            def chat():
                def generate():
                    for chunk in executor.execute_streaming(user_query):
                        yield f"data: {chunk}\n\n"
                return Response(generate(), mimetype='text/event-stream')

        Performance Notes:
            - Streaming does not reduce total API cost
            - Latency to first token is lower than non-streaming
            - Total time to completion is similar
            - User perception of speed is better

        When to Use Streaming:
            - Chat interfaces where users read as text appears
            - Long responses (500+ tokens)
            - Real-time user interfaces

        When NOT to Use Streaming:
            - Batch processing jobs
            - API endpoints that return complete responses
            - When you need to process entire response before showing it
        """
        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                stream=True
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\nError: {str(e)}"

    def execute_with_costar(
        self,
        context: str,
        objective: str,
        style: str,
        tone: str,
        audience: str,
        response_format: str,
        user_input: str,
        model: str = "gpt-4o"
    ) -> str:
        """
        Execute a prompt using the COSTAR enterprise framework.

        COSTAR provides structure and consistency for business-critical prompts.
        It ensures teams can collaborate on prompts and maintain quality across
        different use cases.

        Args:
            context (str):
                Background information, domain details, constraints
                Example: "You are writing for a healthcare SaaS platform"
            objective (str):
                Specific task to accomplish
                Example: "Write a product description that drives conversions"
            style (str):
                Writing style or approach
                Example: "Professional technical writer" or "Creative copywriter"
            tone (str):
                Emotional quality of response
                Example: "Confident and reassuring" or "Urgent and direct"
            audience (str):
                Who will read this
                Example: "Non-technical executives" or "Software developers"
            response_format (str):
                Expected structure of output
                Example: "Bullet points with examples" or "JSON with fields X, Y, Z"
            user_input (str):
                The specific task or content to process
            model (str, default="gpt-4o"):
                OpenAI model name

        Returns:
            str: AI-generated response following COSTAR specification

        Example:
            executor = OpenAIPromptExecutor()

            description = executor.execute_with_costar(
                context="E-commerce furniture store targeting millennials",
                objective="Create compelling product description",
                style="Creative copywriter with vivid language",
                tone="Warm and aspirational",
                audience="Homeowners age 25-40 who value design",
                response_format="Title, 2 paragraphs, 5 bullet points, call-to-action",
                user_input="Scandinavian oak dining table, seats 6, $899"
            )

        Benefits of COSTAR:
            - Consistency across teams and use cases
            - Easy to test variations (change one component at a time)
            - Self-documenting prompts
            - Reduces ambiguity and improves quality
            - Works well with prompt versioning systems

        When to Use COSTAR:
            - Production systems with quality requirements
            - Multi-person teams working on prompts
            - Complex domain-specific applications
            - When prompt maintenance is important

        Framework Component Guide:
            Context    = "Where and why we're doing this"
            Objective  = "What we're trying to accomplish"
            Style      = "How it should be written"
            Tone       = "How it should feel"
            Audience   = "Who it's for"
            Format     = "How it should be structured"
        """
        costar_prompt = f"""
Context: {context}

Objective: {objective}

Style: {style}

Tone: {tone}

Audience: {audience}

Response Format: {response_format}

Task:
{user_input}
"""
        return self.execute_simple_prompt(costar_prompt, model=model)


# Example demonstrations
# Each function shows a specific use case with realistic inputs and outputs


def example_1_simple_prompt():
    """
    Example 1: Basic question answering without context.

    Use this pattern when you need a quick answer and don't need to
    control AI behavior or maintain conversation history.
    """
    print("\n" + "-"*80)
    print("Example 1: Simple Prompt (Basic Q&A)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    prompt = "Explain what prompt engineering is in two sentences."
    print(f"Prompt: {prompt}\n")
    print("Response:")

    response = executor.execute_simple_prompt(prompt)
    print(response)


def example_2_system_prompt():
    """
    Example 2: Using system prompt to control AI personality and behavior.

    System prompts ensure consistent behavior across all user interactions.
    Critical for customer-facing applications.
    """
    print("\n" + "-"*80)
    print("Example 2: System Prompt (Behavior Control)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    system_prompt = (
        "You are a professional customer service agent for TechStore, "
        "an electronics retailer. You are empathetic, solution-focused, "
        "and always provide clear next steps."
    )
    user_prompt = "I received a damaged laptop in my order. What should I do?"

    print(f"System: {system_prompt}")
    print(f"User: {user_prompt}\n")
    print("Response:")

    response = executor.execute_with_system_prompt(system_prompt, user_prompt)
    print(response)


def example_3_json_output():
    """
    Example 3: Structured JSON output for automation and APIs.

    Forces AI to return machine-readable data that can be processed
    programmatically. Essential for production systems.
    """
    print("\n" + "-"*80)
    print("Example 3: Structured JSON Output (Automation)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    prompt = """
    Analyze this product review and return JSON with these fields:
    - sentiment (POSITIVE, NEGATIVE, NEUTRAL, or MIXED)
    - rating (1-5 scale)
    - key_issues (list of problems mentioned)
    - key_strengths (list of positive points)
    
    Review: "The laptop has amazing performance and a beautiful screen. 
    However, the battery life is disappointing and it runs quite hot 
    during intensive tasks."
    """

    print(f"Prompt: {prompt}\n")
    print("Response:")

    result = executor.execute_with_json_output(prompt)
    print(json.dumps(result, indent=2))


def example_4_conversation():
    """
    Example 4: Multi-turn conversation with context preservation.

    Demonstrates how to maintain conversation state for chatbots,
    customer service systems, or any interactive application.
    """
    print("\n" + "-"*80)
    print("Example 4: Multi-Turn Conversation (Context Management)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    # Initialize conversation with system prompt and first user message
    conversation = [
        {
            "role": "system",
            "content": "You are a medical appointment scheduler. Ask one question at a time."
        },
        {
            "role": "user",
            "content": "I need to book a doctor appointment."
        }
    ]

    print("Turn 1:")
    print(f"User: {conversation[1]['content']}")

    response, conversation = executor.execute_conversation(conversation)
    print(f"Assistant: {response}\n")

    # Continue conversation
    conversation.append({
        "role": "user",
        "content": "I've been having headaches for two weeks."
    })

    print("Turn 2:")
    print(f"User: {conversation[-1]['content']}")

    response, conversation = executor.execute_conversation(conversation)
    print(f"Assistant: {response}")


def example_5_streaming():
    """
    Example 5: Streaming response for better user experience.

    Shows text appearing progressively, like ChatGPT interface.
    Improves perceived performance for long responses.
    """
    print("\n" + "-"*80)
    print("Example 5: Streaming Response (Real-Time Output)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    prompt = "Write a short story about a robot learning to cook, in about 150 words."
    print(f"Prompt: {prompt}\n")
    print("Response (streaming):")
    print("-"*80)

    for chunk in executor.execute_streaming(prompt):
        print(chunk, end="", flush=True)

    print("\n")


def example_6_classification():
    """
    Example 6: Deterministic classification for routing and categorization.

    Uses temperature=0 to ensure consistent results. Critical for
    production systems that need reliable categorization.
    """
    print("\n" + "-"*80)
    print("Example 6: Classification Task (Consistent Categorization)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    prompt = """
    Classify the sentiment of this review as exactly one of:
    POSITIVE, NEGATIVE, or NEUTRAL
    
    Review: "The product is okay. Nothing special but it works as expected."
    
    Respond with only the classification.
    """

    print(f"Prompt: {prompt}\n")
    print("Response:")

    # temperature=0 ensures same result every time
    result = executor.execute_simple_prompt(prompt, temperature=0.0, max_tokens=10)
    print(result)


def example_7_costar():
    """
    Example 7: COSTAR framework for enterprise-grade prompts.

    Provides structure and consistency for business-critical applications.
    All prompt components are explicit and maintainable.
    """
    print("\n" + "-"*80)
    print("Example 7: COSTAR Framework (Enterprise Structure)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    print("COSTAR Components:")
    print("  Context: Furniture e-commerce for millennials")
    print("  Objective: Create compelling product description")
    print("  Style: Creative copywriter")
    print("  Tone: Warm and aspirational")
    print("  Audience: Homeowners age 25-40")
    print("  Format: Title, description, features, CTA\n")
    print("Response:")
    print("-"*80)

    response = executor.execute_with_costar(
        context="Modern furniture e-commerce platform targeting millennial homeowners",
        objective="Write a product description that drives conversions",
        style="Creative copywriter using vivid, benefit-focused language",
        tone="Warm and aspirational, helping customers envision the product in their home",
        audience="Millennial homeowners aged 25-40 who value design and quality",
        response_format="Product title, 2-paragraph description, 5 feature bullets, call-to-action",
        user_input="Scandinavian minimalist oak coffee table with hidden storage, $599"
    )

    print(response)


def example_8_batch_processing():
    """
    Example 8: Processing multiple items in batch.

    Efficient pattern for analyzing large datasets. Uses temperature=0
    for consistency across all items.
    """
    print("\n" + "-"*80)
    print("Example 8: Batch Processing (Multiple Items)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    reviews = [
        "Amazing product, exceeded all expectations!",
        "Complete waste of money, broke after one day.",
        "It's fine, does what it's supposed to do."
    ]

    print("Processing 3 customer reviews...\n")

    for i, review in enumerate(reviews, 1):
        prompt = f'Classify sentiment as POSITIVE, NEGATIVE, or NEUTRAL: "{review}"'
        sentiment = executor.execute_simple_prompt(prompt, temperature=0.0, max_tokens=10)
        print(f"{i}. Review: {review}")
        print(f"   Sentiment: {sentiment}\n")


def example_9_chain_of_thought():
    """
    Example 9: Chain-of-thought reasoning for transparent calculations.

    AI shows its work step-by-step. Critical for medical, financial,
    or safety-critical applications where reasoning must be verified.
    """
    print("\n" + "-"*80)
    print("Example 9: Chain-of-Thought Reasoning (Show Your Work)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    prompt = """
    A pediatric patient weighs 18 kg.
    The medication dosage is 80 mg per kg per day, divided into two doses.
    
    Calculate the dose per administration.
    Show your calculation steps clearly.
    """

    print(f"Prompt: {prompt}\n")
    print("Response:")
    print("-"*80)

    # temperature=0 for deterministic calculations
    response = executor.execute_simple_prompt(prompt, temperature=0.0)
    print(response)


def example_10_few_shot_learning():
    """
    Example 10: Few-shot learning by example.

    Teaches the AI a custom pattern by showing examples rather than
    explaining rules. Works well for unique formatting requirements.
    """
    print("\n" + "-"*80)
    print("Example 10: Few-Shot Learning (Learn by Example)")
    print("-"*80)

    executor = OpenAIPromptExecutor()

    prompt = """
    Learn the product code formatting pattern from these examples:
    
    Input: men's running shoes size 10 blue
    Output: MEN-SHOE-RUN-10-BLU
    
    Input: women's yoga mat purple extra thick
    Output: WOM-YOGA-MAT-PURP-XTK
    
    Input: kids backpack red 15 inch
    Output: KID-BACK-15-RED
    
    Now format this product:
    Input: women's tennis racket lightweight black
    Output:
    """

    print(f"Prompt: {prompt}\n")
    print("Response:")

    # temperature=0 for consistent pattern application
    response = executor.execute_simple_prompt(prompt, temperature=0.0, max_tokens=50)
    print(response)


def main():
    """
    Run all examples to demonstrate different prompt engineering patterns.

    Each example is independent and demonstrates a specific technique
    that can be adapted for production use.
    """
    print("\n" + "="*80)
    print("OpenAI Prompt Engineering - Complete Examples")
    print("="*80)
    print("\nThis program demonstrates 10 essential prompt patterns.")
    print("Each example shows a different technique for real-world applications.\n")

    try:
        example_1_simple_prompt()
        example_2_system_prompt()
        example_3_json_output()
        example_4_conversation()
        example_5_streaming()
        example_6_classification()
        example_7_costar()
        example_8_batch_processing()
        example_9_chain_of_thought()
        example_10_few_shot_learning()

        print("\n" + "="*80)
        print("All examples completed successfully")
        print("="*80)
        print("\nYou can now adapt these patterns for your own applications.")

    except Exception as e:
        print(f"\n\nError running examples: {str(e)}")
        print("Please verify your OPENAI_API_KEY is set correctly in .env file")


if __name__ == "__main__":
    main()