"""
Quick Start Example – OpenAI API

This file provides a minimal, end-to-end example for interacting with
the OpenAI API using Python. It is intended for first-time users who
want to verify their setup and start sending prompts to an AI model
as quickly as possible.

The examples in this file demonstrate:
- Sending a simple question to the AI
- Performing text classification
- Generating structured or creative content
- Extracting structured information from 2_unstructured text
- Running the program in an interactive prompt mode

"""

import os
from openai import OpenAI


# Initialize OpenAI client
client = OpenAI()


def ask_ai(prompt: str, model: str = "gpt-4o") -> str:
    """
    Simple function to ask AI a question.
    
    Args:
        prompt: Your question or instruction
        model: Which AI model to use (default: gpt-4o)
        
    Returns:
        AI's response as text
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            n=2
        )
        print("\nAI's response:",response)
        for id,choice in enumerate(response.choices):
            print("#"*15)
            print("choice id:",id+1,"Message:",choice.message.content)
            print("#" * 15)
        return response.choices[0].message.content
        
    except Exception as e:
        return f"Error: {str(e)}\n\nMake sure OPENAI_API_KEY is set in your .env file"


# ----------------------------------------------------------------
# QUICK START EXAMPLES - Try these!
# ----------------------------------------------------------------

if __name__ == "__main__":
    print("-"*70)
    print("OpenAI API Quick Start Examples")
    print("-"*70)
    
    # Example 1: Simple question
    print("\nExample 1: Simple Question")
    print("-" * 70)
    response = ask_ai("What is machine learning? Explain in 2 sentences.")
    print(response)
    
    # # Example 2: Classification
    # print("\n\nExample 2: Text Classification")
    # print("-" * 70)
    # prompt = """
    # Classify this review as POSITIVE, NEGATIVE, or NEUTRAL:
    # "The product works but arrived 2 weeks late. Quality is good though."
    #
    # Answer with just the classification.
    # """
    # response = ask_ai(prompt)
    # print(response)
    #
    # # Example 3: Content Generation
    # print("\n\nExample 3: Content Generation")
    # print("-" * 70)
    # prompt = """
    # Write a professional email to a customer apologizing for delayed shipping.
    # Keep it under 100 words. Customer name: John. Order #12345.
    # """
    # response = ask_ai(prompt)
    # print(response)
    #
    # # Example 4: Data Extraction
    # print("\n\nExample 4: Data Extraction")
    # print("-" * 70)
    # prompt = """
    # Extract the following from this text and format as JSON:
    # - Product name
    # - Price
    # - Color
    #
    # Text: "I bought the UltraWidget Pro in blue color for $299.99"
    # """
    # response = ask_ai(prompt)
    # print(response)
    
    print("\n" + "-"*70)
    print("Quick start completed! Now try your own prompts.")
    print("-"*70)
    
    # Interactive mode
    print("\nTry it yourself! (Type 'quit' to exit)")
    print("-" * 70)
    
    while True:
        user_input = input("\nYour prompt: ")
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nGoodbye!")
            break
        
        if user_input.strip():
            print("\nAI Response:")
            print("-" * 70)
            response = ask_ai(user_input)
            print(response)
