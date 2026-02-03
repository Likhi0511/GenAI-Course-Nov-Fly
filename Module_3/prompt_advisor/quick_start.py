"""
Quick Start Example - Prompt Advisor
Run this to test the system with a single problem
"""

import os
from prompt_advisor import PromptAdvisor

def main():
    print("🎯 Quick Start - Prompt Advisor")
    print("=" * 80)
    
    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n⚠️  No API key found!")
        print("Please set your OpenAI API key:")
        print("  export OPENAI_API_KEY='your-key-here'")
        print("\nOr enter it now:")
        api_key = input("API Key: ").strip()
        
        if not api_key:
            print("❌ Cannot proceed without API key")
            return
    
    # Initialize advisor
    print("\n🔧 Initializing advisor...")
    try:
        advisor = PromptAdvisor(api_key=api_key, model="gpt-4o")
        print("✅ Advisor initialized successfully!")
    except Exception as e:
        print(f"❌ Error initializing advisor: {e}")
        return
    
    # Get problem from user or use example
    print("\n" + "=" * 80)
    print("📝 Describe Your Business Problem")
    print("=" * 80)
    print("\nExamples:")
    print("1. E-commerce product recommendation system")
    print("2. Customer service chatbot")
    print("3. Financial risk assessment")
    print("4. Marketing campaign planning")
    print("5. Custom problem (type your own)")
    
    choice = input("\nSelect example (1-5) or press Enter for custom: ").strip()
    
    examples = {
        "1": """We need to build an AI system that recommends products to customers 
based on their browsing history, past purchases, and similar customer profiles. 
The system should explain why each product is recommended and handle multiple 
product categories with varying levels of inventory.""",
        
        "2": """Design a customer service chatbot for a telecommunications company 
that needs to handle billing inquiries, technical support, and service upgrades. 
The bot must escalate complex issues to human agents and maintain context across 
multiple conversation turns.""",
        
        "3": """Develop a system to assess loan application risks by analyzing 
applicant credit history, income stability, debt-to-income ratio, and economic 
indicators. The system must provide transparent reasoning for each decision and 
comply with fair lending regulations.""",
        
        "4": """Create a comprehensive marketing campaign for launching a new 
sustainable fashion line. We need to develop messaging that resonates with 
environmentally conscious millennials, plan social media content, and measure 
campaign effectiveness through engagement metrics."""
    }
    
    if choice in examples:
        problem = examples[choice]
        print(f"\n📋 Using Example {choice}:")
        print(problem)
    else:
        print("\n📋 Enter your problem (press Ctrl+D or Ctrl+Z when done):")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        problem = "\n".join(lines)
    
    if not problem.strip():
        print("❌ No problem provided")
        return
    
    # Analyze the problem
    print("\n" + "=" * 80)
    print("🤔 Analyzing your problem...")
    print("=" * 80)
    
    try:
        result = advisor.analyze_problem(problem)
        
        # Display formatted results
        formatted = advisor.format_recommendation(result)
        print(f"\n{formatted}")
        
        # Save to file
        filename = "recommendation_output.txt"
        with open(filename, 'w') as f:
            f.write("BUSINESS PROBLEM\n")
            f.write("=" * 80 + "\n")
            f.write(f"{problem}\n\n")
            f.write(formatted)
        
        print(f"\n💾 Results saved to: {filename}")
        
        # Option to analyze another problem
        print("\n" + "=" * 80)
        another = input("\nAnalyze another problem? (y/n): ").strip().lower()
        if another == 'y':
            main()
        else:
            print("\n👋 Thanks for using Prompt Advisor!")
            
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        print("\nTroubleshooting tips:")
        print("1. Check your API key is valid")
        print("2. Ensure you have OpenAI API credits")
        print("3. Check your internet connection")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
