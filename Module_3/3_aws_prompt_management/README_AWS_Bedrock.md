# AWS Bedrock Prompt Management Guide

Complete guide for managing prompts as enterprise resources using AWS Bedrock Prompt Management service.

## What is AWS Bedrock Prompt Management?

AWS Bedrock Prompt Management is a service that stores, versions, and manages your AI prompts as centralized resources in AWS, similar to how you manage code in Git or infrastructure in CloudFormation.

### The Problem It Solves

**Without Prompt Management:**
```python
# Prompts scattered across codebase
PROMPT_1 = "Write an email to {{name}}..."  # In file1.py
PROMPT_2 = "Generate report for {{data}}..."  # In file2.py
PROMPT_3 = "Analyze {{text}}..."  # In file3.py

# Issues:
# - No version control for prompts
# - Changes require code 3_deployment
# - No rollback capability
# - Hard to share across teams
# - No governance or approval workflow
```

**With Prompt Management:**
```python
# All prompts stored in AWS Bedrock
# Application just references them by ID
response = manager.invoke_prompt(
    prompt_id="customer-email-v1",
    variables={"name": "John", "order": "12345"},
    version="3"  # Pin to tested version
)

# Benefits:
# - Centralized storage
# - Full version history
# - Easy rollback
# - Team collaboration
# - Audit trails
```

---

## Key Concepts

### 1. Prompt
A reusable template with variables and configuration.

Example:
```
Dear {{customer_name}},

Thank you for order {{order_id}}. Your {{product_name}} will arrive on {{delivery_date}}.

Configuration:
  Model: Claude 3.5 Sonnet
  Temperature: 0.7
  Max Tokens: 500
```

### 2. Variables
Placeholders in prompt text that you fill at runtime.

Syntax: `{{variable_name}}`

Example:
```python
prompt_text = "Hello {{name}}, your order {{order_id}} is {{status}}."

variables = {
    "name": "Alice",
    "order_id": "ORD-123",
    "status": "shipped"
}

# Becomes: "Hello Alice, your order ORD-123 is shipped."
```

### 3. Versions
Immutable snapshots of a prompt.

Workflow:
1. Edit prompt in DRAFT mode
2. Test thoroughly
3. Create version (makes it immutable)
4. Deploy to production

Version numbers: "1", "2", "3", etc.

### 4. Aliases (Planned Feature)
Named pointers to specific versions.

Example:
```
production -> version 5
staging    -> version 6
latest     -> version 6
```

---

## Installation

### Step 1: Install Dependencies

```bash
pip install boto3 python-dotenv
```

### Step 2: Configure AWS Credentials

**Option A: AWS CLI**
```bash
aws configure
```

Enter:
- AWS Access Key ID
- AWS Secret Access Key
- Default region: us-east-1
- Default output format: json

**Option B: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_key_here
export AWS_SECRET_ACCESS_KEY=your_secret_here
export AWS_DEFAULT_REGION=us-east-1
```

**Option C: IAM Role**
If running on EC2, Lambda, or ECS, attach an IAM role with Bedrock permissions.

### Step 3: Verify Setup

```bash
aws bedrock list-prompts
```

Should return a list (may be empty if no prompts created yet).

---

## Required IAM Permissions

Create an IAM policy with these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:CreatePrompt",
        "bedrock:GetPrompt",
        "bedrock:ListPrompts",
        "bedrock:UpdatePrompt",
        "bedrock:DeletePrompt",
        "bedrock:CreatePromptVersion",
        "bedrock:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

Attach this policy to your IAM user or role.

---

## Quick Start

### Create Your First Managed Prompt

```python
from aws_bedrock_prompt_management import BedrockPromptManager

# Initialize manager
manager = BedrockPromptManager(region_name="us-east-1")

# Create a prompt
result = manager.create_prompt(
    name="greeting-email",
    description="Friendly greeting email template",
    prompt_text="""
    Write a warm greeting email to {{customer_name}}.
    Mention their recent purchase of {{product_name}}.
    Keep it under 100 words.
    """,
    variables=["customer_name", "product_name"],
    temperature=0.7
)

print(f"Created prompt ID: {result['prompt_id']}")
```

### Use the Prompt

```python
# Invoke the prompt with actual values
response = manager.invoke_prompt(
    prompt_id=result['prompt_id'],
    variables={
        "customer_name": "Sarah Johnson",
        "product_name": "Premium Coffee Maker"
    }
)

print(response)  # Generated email
```

---

## Complete Workflow Example

### Development Workflow

```python
manager = BedrockPromptManager()

# Step 1: Create initial prompt
result = manager.create_prompt(
    name="order-confirmation",
    description="Order confirmation email",
    prompt_text="Dear {{name}}, your order {{id}} is confirmed.",
    variables=["name", "id"]
)

prompt_id = result['prompt_id']

# Step 2: Test it
response = manager.invoke_prompt(
    prompt_id=prompt_id,
    variables={"name": "John", "id": "123"}
)
print(response)

# Step 3: Refine prompt
manager.update_prompt(
    prompt_id=prompt_id,
    prompt_text="Dear {{name}}, thank you! Order {{id}} confirmed. Arrives {{date}}."
)

# Step 4: Test again
# ... verify improvements ...

# Step 5: Create version for production
version = manager.create_prompt_version(
    prompt_id=prompt_id,
    description="Tested and approved for production"
)

print(f"Production version: {version['version']}")

# Step 6: Use versioned prompt in production
response = manager.invoke_prompt(
    prompt_id=prompt_id,
    variables={"name": "Alice", "id": "456", "date": "Dec 25"},
    version=version['version']  # Pin to specific version
)
```

### Production Deployment Pattern

```python
# config.py
CUSTOMER_EMAIL_PROMPT_ID = "abc123xyz"
CUSTOMER_EMAIL_VERSION = "5"  # Update this when promoting new version

# application.py
def send_customer_email(customer_name, order_id):
    manager = BedrockPromptManager()
    
    email_content = manager.invoke_prompt(
        prompt_id=CUSTOMER_EMAIL_PROMPT_ID,
        variables={
            "customer_name": customer_name,
            "order_id": order_id
        },
        version=CUSTOMER_EMAIL_VERSION  # Always pin production to version
    )
    
    send_email(customer_email, email_content)
```

---

## Advanced Usage

### Multi-Environment Strategy

**What this means:**

In software development, you typically have multiple environments where your application runs:
- **Development** - Where developers write and test code
- **Staging** - A production-like environment for final testing
- **Production** - The live system that real users interact with

When managing prompts across these environments, you want different behaviors:
- Development should always use the latest version so developers can test changes immediately
- Staging should test a specific version before it goes to production
- Production should use a proven, stable version that won't change unexpectedly

Think of it like releasing a mobile app:
- Developers test the latest code on their machines
- Beta testers get a specific release candidate
- Regular users get the stable, approved version

**Why this matters:**

Without environment separation, a developer testing a new prompt could accidentally affect production users. With this strategy, you can safely test changes without risk.

**Real-world example:**

A customer service team wants to test a friendlier tone in their email responses. They test in staging first with real customer data but sending to test accounts. Once they verify it works well, they promote that version to production.

```python
# Different versions for different environments

# Development: Always use latest
dev_response = manager.invoke_prompt(
    prompt_id=prompt_id,
    variables=vars
    # No version = uses latest
)

# Staging: Test specific version
staging_response = manager.invoke_prompt(
    prompt_id=prompt_id,
    variables=vars,
    version="3"  # Testing version 3
)

# Production: Pin to stable version
prod_response = manager.invoke_prompt(
    prompt_id=prompt_id,
    variables=vars,
    version="2"  # Known-good version
)
```

### Rollback Strategy

**What this means:**

A rollback is reverting to a previous version of something when the new version has problems. In traditional software deployment, rolling back usually means:
- Redeploying old code
- Running database migrations in reverse
- Restarting servers
- Waiting 10-30 minutes for deployment

With Bedrock Prompt Management, rolling back a prompt is instant because you just change which version number you're using. The old version still exists and works perfectly.

Think of it like TV channels:
- Channel 5 is your current production prompt (version 5)
- Channel 6 is your new prompt (version 6)
- If viewers don't like channel 6, you just switch back to channel 5
- Both channels exist simultaneously, switching is instant

**Why this matters:**

Imagine you deploy a new email template on Friday afternoon and it starts generating emails that sound too casual or miss important information. Without rollback capability, you need to:
1. Fix the prompt
2. Test the fix
3. Deploy new code
4. Hope you got it right this time

With instant rollback:
1. Change version from "6" to "5" in your config
2. Problem solved in 30 seconds
3. Fix and test version 7 carefully next week

**Real-world example:**

An e-commerce company updates their product description generator to be more engaging. After deploying version 4, they notice it sometimes uses informal language that doesn't match their brand. Instead of rushing to fix it, they instantly roll back to version 3 while they refine version 5.

If a new version causes issues:

```python
# Current production on version 5
PROD_VERSION = "5"

# Deploy version 6
PROD_VERSION = "6"

# Issues found! Roll back
PROD_VERSION = "5"  # Instant rollback

# No code changes needed, just update version number
```

**Best practices for safe rollbacks:**

```python
# Keep a rollback variable in your config
CURRENT_VERSION = "6"
ROLLBACK_VERSION = "5"  # Previous known-good version

# Easy to switch
ACTIVE_VERSION = CURRENT_VERSION  # Normal operation
# or
ACTIVE_VERSION = ROLLBACK_VERSION  # When things go wrong

# Use in application
response = manager.invoke_prompt(
    prompt_id=PROMPT_ID,
    variables=data,
    version=ACTIVE_VERSION
)
```

**Monitoring to trigger rollbacks:**

```python
# Track success rate
success_rate = successful_responses / total_responses

# Automatic rollback if quality drops
if success_rate < 0.95:  # Less than 95% success
    print("Quality drop detected! Rolling back...")
    ACTIVE_VERSION = ROLLBACK_VERSION
    alert_team("Automatic rollback triggered")
```

### A/B Testing

**What this means:**

A/B testing is when you try two different versions of something with real users to see which performs better. Instead of guessing which prompt will work better, you let actual usage data tell you.

In traditional A/B testing:
- Version A: "Order confirmed. Thank you for your purchase."
- Version B: "Great news! Your order is confirmed. We're excited to get this to you!"

You show each version to 50% of users and measure:
- Which gets more positive responses
- Which generates fewer support tickets
- Which leads to more repeat purchases

With Bedrock Prompt Management, you can A/B test prompts without deploying new code. Just route half your traffic to version 3 and half to version 4.

Think of it like taste testing:
- Restaurant testing two soup recipes
- They serve recipe A to customers on Monday/Wednesday/Friday
- They serve recipe B to customers on Tuesday/Thursday/Saturday
- After two weeks, they see which got better reviews
- They make the winner their permanent menu item

**Why this matters:**

You might think a friendly, casual tone works better for customer emails, but maybe your customers actually prefer professional, concise language. A/B testing tells you what actually works, not what you think will work.

**Real-world example:**

A SaaS company has two prompt versions for their onboarding emails:
- Version 3: Direct and to-the-point
- Version 4: Friendly with emojis and casual language

They run both for two weeks and measure:
- Email open rates
- Click-through rates  
- Trial-to-paid conversion rates

Results show version 3 actually converts better, even though version 4 feels more modern. Data wins over intuition.

```python
import random

def generate_email(customer_data):
    # 50% traffic to old version, 50% to new
    version = "3" if random.random() < 0.5 else "4"
    
    response = manager.invoke_prompt(
        prompt_id=EMAIL_PROMPT_ID,
        variables=customer_data,
        version=version
    )
    
    log_ab_test(version, customer_data['id'])
    return response
```

**More sophisticated A/B testing:**

```python
# 70% on stable version, 30% testing new version
def get_version_for_user(user_id):
    # Use user_id for consistent experience
    # Same user always gets same version
    hash_value = hash(user_id) % 100
    
    if hash_value < 70:
        return "3"  # Stable version (70%)
    else:
        return "4"  # Test version (30%)

# User always sees same version
version = get_version_for_user(user_id)
response = manager.invoke_prompt(
    prompt_id=PROMPT_ID,
    variables=data,
    version=version
)

# Track results
log_metrics(
    user_id=user_id,
    version=version,
    response_quality=measure_quality(response)
)
```

**Analyzing A/B test results:**

```python
# After running for 2 weeks
results_v3 = get_metrics(version="3")
results_v4 = get_metrics(version="4")

print(f"Version 3: {results_v3['conversion_rate']}% conversion")
print(f"Version 4: {results_v4['conversion_rate']}% conversion")

# Statistical significance test
if is_significant_difference(results_v3, results_v4):
    winner = "3" if results_v3['conversion_rate'] > results_v4['conversion_rate'] else "4"
    print(f"Winner: Version {winner}")
    
    # Promote winner to 100% traffic
    PROD_VERSION = winner
else:
    print("No significant difference, keep testing")
```

**When to A/B test prompts:**

Good for A/B testing:
- Email subject lines (open rates)
- Call-to-action phrasing (click rates)
- Tone and style (engagement metrics)
- Length (short vs detailed)

Not good for A/B testing:
- Critical system prompts (too risky)
- Low-traffic use cases (not enough data)
- Prompts that must be consistent (legal, compliance)

---

## Best Practices

### 1. Naming Conventions

Use descriptive, hierarchical names:

```
Good:
  customer-email-order-confirmation
  support-ticket-auto-response
  product-description-generator

Bad:
  email1
  prompt2
  test
```

### 2. Variable Naming

Use clear, semantic names:

```
Good:
  {{customer_name}}
  {{order_total}}
  {{shipping_address}}

Bad:
  {{x}}
  {{data}}
  {{input1}}
```

### 3. Version Descriptions

Document what changed:

```python
manager.create_prompt_version(
    prompt_id=pid,
    description="Added empathy phrases for upset customers - tested with 100 samples"
)
```

### 4. Testing Before Versioning

```python
# Test with diverse inputs
test_cases = [
    {"name": "John", "order": "123"},
    {"name": "María García", "order": "456"},  # International
    {"name": "O'Brien", "order": "789"},  # Special chars
]

for case in test_cases:
    response = manager.invoke_prompt(prompt_id, case)
    assert validate_response(response)

# Only create version after all tests pass
manager.create_prompt_version(prompt_id)
```

### 5. Monitoring

```python
import logging

def invoke_with_monitoring(prompt_id, variables, version):
    start_time = time.time()
    
    try:
        response = manager.invoke_prompt(prompt_id, variables, version)
        
        latency = time.time() - start_time
        logging.info(f"Prompt {prompt_id} v{version}: {latency:.2f}s")
        
        return response
        
    except Exception as e:
        logging.error(f"Prompt {prompt_id} v{version} failed: {e}")
        raise
```

### 6. Cost Management

```python
# Use appropriate max_tokens
manager.create_prompt(
    name="short-response",
    max_tokens=100,  # Email subject line
    # ...
)

manager.create_prompt(
    name="long-response",
    max_tokens=2000,  # Full document
    # ...
)
```

---

## Comparison: Bedrock vs OpenAI

| Feature | AWS Bedrock | OpenAI |
|---------|-------------|--------|
| Prompt Storage | Centralized in AWS | Your codebase |
| Version Control | Built-in versioning | Manual (Git) |
| Rollback | Instant (change version) | Code deployment |
| Collaboration | AWS IAM permissions | Git workflow |
| Audit Trail | AWS CloudTrail | Git history |
| Cost | Pay per use + storage | Pay per use only |
| Setup Complexity | Higher (AWS setup) | Lower (API key) |
| Enterprise Features | Advanced governance | Basic |

### When to Use Bedrock Prompt Management

Use Bedrock when:
- You have multiple teams working on prompts
- You need enterprise governance and audit trails
- You want to decouple prompts from code deployments
- You're already using AWS infrastructure
- Compliance requires prompt versioning

Use OpenAI directly when:
- Single developer or small team
- Simple use cases
- Fast iteration more important than governance
- Don't want AWS complexity

---

## Troubleshooting

### Error: "Unable to locate credentials"

**Problem:** AWS credentials not configured

**Solution:**
```bash
aws configure
# Enter your credentials
```

### Error: "Access Denied"

**Problem:** IAM permissions insufficient

**Solution:**
1. Check IAM policy includes bedrock:* permissions
2. Verify user/role has policy attached
3. Check resource-level permissions

### Error: "Model not found"

**Problem:** Invalid model ID or model not available in region

**Solution:**
```python
# Use correct model ID
model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# Verify region
manager = BedrockPromptManager(region_name="us-east-1")
```

### Error: "Variable not found"

**Problem:** Missing variable in invoke call

**Solution:**
```python
# Get required variables first
prompt_info = manager.get_prompt(prompt_id)
required_vars = prompt_info['variables']
print(f"Required: {required_vars}")

# Provide all variables
manager.invoke_prompt(
    prompt_id=prompt_id,
    variables={var: value for var in required_vars}
)
```

---

## Cost Estimation

### Prompt Storage Cost
Very low - essentially free for typical usage.

Example:
- 100 prompts × 1KB each = 100KB storage
- Cost: < $0.01/month

### Model Invocation Cost
This is where costs occur. Same as direct model usage.

Claude 3.5 Sonnet pricing (as of Dec 2024):
- Input: $3.00 per million tokens
- Output: $15.00 per million tokens

Example calculation:
```
Email generation task:
  - Prompt: 200 tokens ($0.0006)
  - Response: 150 tokens ($0.0023)
  - Total per email: $0.0029

1000 emails per day = $2.90/day = $87/month
```

### Cost Optimization Tips

1. Use appropriate models:
   - Simple tasks: Claude Haiku (cheaper)
   - Complex tasks: Claude Sonnet

2. Limit max_tokens:
```python
# Don't use default 1000 for everything
manager.create_prompt(
    max_tokens=150  # Just enough for email subject
)
```

3. Cache common prompts in application layer

4. Use temperature=0 for deterministic tasks (slightly cheaper)

---

## Migration Guide

### From Hardcoded Prompts to Managed

**Before:**
```python
def generate_email(customer_name, order_id):
    prompt = f"""
    Write email to {customer_name} about order {order_id}.
    Keep it professional and under 100 words.
    """
    
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.choices[0].message.content
```

**After:**
```python
# One-time setup
manager = BedrockPromptManager()
prompt_result = manager.create_prompt(
    name="customer-order-email",
    prompt_text="""
    Write email to {{customer_name}} about order {{order_id}}.
    Keep it professional and under 100 words.
    """,
    variables=["customer_name", "order_id"]
)

# Save this in config
EMAIL_PROMPT_ID = prompt_result['prompt_id']

# In application
def generate_email(customer_name, order_id):
    return manager.invoke_prompt(
        prompt_id=EMAIL_PROMPT_ID,
        variables={
            "customer_name": customer_name,
            "order_id": order_id
        }
    )
```

---

## Additional Resources

**AWS Documentation:**
- https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-management.html

**Boto3 Bedrock Reference:**
- https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock.html

**AWS Bedrock Pricing:**
- https://aws.amazon.com/bedrock/pricing/

**IAM Best Practices:**
- https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html

---

## Support

For issues with this code:
- Review examples in aws_bedrock_prompt_management.py
- Check AWS credentials and permissions
- Verify region availability

For AWS Bedrock issues:
- AWS Support Console
- AWS Bedrock Documentation
- AWS Community Forums

---

## License

This code is provided as educational material for the Applied Generative AI course.

---

**Ready to get started?**

Run the complete examples:
```bash
python aws_bedrock_prompt_management.py
```
