"""
Test Client for NL2SQL API with Pinecone
"""

import requests
import json


class NL2SQLPineconeClient:
    """Client for NL2SQL API with Pinecone"""
    
    def __init__(self, base_url: str = "http://localhost:8002"):
        self.base_url = base_url

    def health_check(self):
        """Check API health"""
        response = requests.get(f"{self.base_url}/health")
        return response.json()

    def generate_query(self, question: str, database: str = "ecommerce"):
        """Generate SQL query from natural language"""
        payload = {
            "question": question,
            "database": database
        }

        response = requests.post(
            f"{self.base_url}/query",
            json=payload
        )

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return None

    def explain_query(self, question: str):
        """Get query with detailed explanation"""
        payload = {"question": question}

        response = requests.post(
            f"{self.base_url}/query/explain",
            json=payload
        )

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return None


def main():
    """Test the API"""

    client = NL2SQLPineconeClient()

    # Health check
    print("Health Check:")
    print(json.dumps(client.health_check(), indent=2))
    print("\n" + "="*70 + "\n")

    # Test queries
    test_questions = [
        "Show me all customers in California",
        "Find products matching search keywords for catalog browsing and product discovery.",
        "What are the top 5 products by revenue?",
        "List orders from last month with their total amounts"
    ]

    for question in test_questions:
        print(f"Question: {question}")
        print("-" * 70)

        result = client.generate_query(question)
        
        if result:
            print(f"\n📊 SQL Query:")
            print(result['sql_query'])

            print(f"\n💡 Explanation:")
            print(result['explanation'])

            print(f"\n📋 Tables Used: {', '.join(result['relevant_tables'])}")
            print(f"🎯 Confidence: {result['confidence']}")

            # Display context details
            if result.get('context_used'):
                context = result['context_used']

                print(f"\n🗂️  Context Retrieved from Pinecone:")
                print("-" * 70)

                # Show columns
                if context.get('columns'):
                    print(f"\n📌 Columns ({len(context['columns'])} found):")
                    for col in context['columns'][:5]:  # Show top 5
                        print(f"  • {col['table']}.{col['column']} (score: {col['relevance_score']})")
                        print(f"    {col['description']}")
                        print()

                # Show relationships
                if context.get('relationships'):
                    print(f"\n🔗 Relationships ({len(context['relationships'])} found):")
                    for rel in context['relationships'][:3]:  # Show top 3
                        print(f"  • Score: {rel['relevance_score']}")
                        if rel.get('join_condition'):
                            print(f"    Join: {rel['join_condition']}")
                        print(f"    {rel['description']}")
                        print()

                # Show example queries
                if context.get('example_queries'):
                    print(f"\n📝 Similar Query Examples ({len(context['example_queries'])} found):")
                    for i, example in enumerate(context['example_queries'], 1):
                        print(f"\n  Example {i} (score: {example['relevance_score']}):")
                        if example.get('use_case'):
                            print(f"    Use Case: {example['use_case']}")
                        if example.get('sql_examples'):
                            print(f"    SQL Patterns:")
                            for sql in example['sql_examples'][:2]:  # Show top 2 SQL examples
                                print(f"      • {sql}")
                        else:
                            print(f"    {example['summary']}")

                # Show tables summary
                if context.get('tables'):
                    print(f"\n📚 Tables Summary:")
                    for table_name, table_info in context['tables'].items():
                        cols = len(table_info.get('columns', []))
                        rels = len(table_info.get('relationships', []))
                        print(f"  • {table_name}: {cols} columns, {rels} relationships")
                        if table_info.get('description'):
                            print(f"    {table_info['description'][:100]}...")

        print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
