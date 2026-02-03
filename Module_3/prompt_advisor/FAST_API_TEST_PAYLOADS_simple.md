# 🧪 Test Payloads for Prompt Advisor API

## Test Payload 1: Fast Mode - Healthcare AI Diagnostic System

### Problem Description
Design and implement an AI-powered clinical decision support system for emergency departments that can analyze patient vital signs, medical history, lab results, and real-time symptoms to provide differential diagnoses with confidence scores, flag critical conditions requiring immediate intervention, integrate with existing electronic health records (EHR) systems, maintain HIPAA compliance, explain reasoning in medical terminology for physicians while also providing patient-friendly summaries, handle edge cases like conflicting test results or incomplete data, prioritize diagnoses based on severity and likelihood, and continuously learn from physician feedback to improve accuracy over time while maintaining audit trails for all recommendations.

### cURL Command
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-openai-api-key-here" \
  -d '{
    "problem": "Design and implement an AI-powered clinical decision support system for emergency departments that can analyze patient vital signs, medical history, lab results, and real-time symptoms to provide differential diagnoses with confidence scores, flag critical conditions requiring immediate intervention, integrate with existing electronic health records (EHR) systems, maintain HIPAA compliance, explain reasoning in medical terminology for physicians while also providing patient-friendly summaries, handle edge cases like conflicting test results or incomplete data, prioritize diagnoses based on severity and likelihood, and continuously learn from physician feedback to improve accuracy over time while maintaining audit trails for all recommendations.",
    "mode": "fast",
    "model": "gpt-4o"
  }'
```

### Postman/JSON Body
```json
{
  "problem": "Design and implement an AI-powered clinical decision support system for emergency departments that can analyze patient vital signs, medical history, lab results, and real-time symptoms to provide differential diagnoses with confidence scores, flag critical conditions requiring immediate intervention, integrate with existing electronic health records (EHR) systems, maintain HIPAA compliance, explain reasoning in medical terminology for physicians while also providing patient-friendly summaries, handle edge cases like conflicting test results or incomplete data, prioritize diagnoses based on severity and likelihood, and continuously learn from physician feedback to improve accuracy over time while maintaining audit trails for all recommendations.",
  "mode": "fast",
  "model": "gpt-4o"
}
```

### Python Code
```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    headers={
        "Content-Type": "application/json",
        "X-API-Key": "your-openai-api-key-here"
    },
    json={
        "problem": "Design and implement an AI-powered clinical decision support system for emergency departments that can analyze patient vital signs, medical history, lab results, and real-time symptoms to provide differential diagnoses with confidence scores, flag critical conditions requiring immediate intervention, integrate with existing electronic health records (EHR) systems, maintain HIPAA compliance, explain reasoning in medical terminology for physicians while also providing patient-friendly summaries, handle edge cases like conflicting test results or incomplete data, prioritize diagnoses based on severity and likelihood, and continuously learn from physician feedback to improve accuracy over time while maintaining audit trails for all recommendations.",
        "mode": "fast",
        "model": "gpt-4o"
    }
)

result = response.json()
print(f"Recommended Template: {result['recommended_template']['acronym']}")
print(f"Recommended Technique: {result['recommended_technique']['name']}")
print(f"\nReasoning: {result['recommended_template']['reasoning']}")
```

### Expected Analysis
- **Complexity**: High
- **Requires Creativity**: Low (systematic approach needed)
- **Requires Data Analysis**: Yes (medical data, vital signs, lab results)
- **Has Constraints**: Yes (HIPAA compliance, EHR integration, real-time processing)
- **Requires Step-by-Step**: Yes (diagnostic workflow, prioritization)

### Likely Recommendation
- **Template**: D-R-E-A-M (Define-Research-Execute-Analyse-Measure) or R-I-S-E (Role-Input-Steps-Expectation)
- **Technique**: Chain of Thought (for transparent medical reasoning) or Complexity-Based (handling varied scenarios)

---

## Test Payload 2: Deep Mode - Multi-Agent Financial Trading Platform

### Problem Description
Architect a sophisticated multi-agent AI system for autonomous cryptocurrency and forex trading that employs sentiment analysis agents monitoring social media and news feeds, technical analysis agents identifying chart patterns and market indicators, fundamental analysis agents evaluating macroeconomic data and geopolitical events, risk management agents enforcing position limits and stop-losses, portfolio optimization agents balancing asset allocation across multiple exchanges, arbitrage detection agents exploiting price discrepancies between markets, all coordinated by a meta-agent that synthesizes signals from individual agents using ensemble methods while adapting trading strategies based on market regime detection (bull, bear, sideways, high volatility), backtesting all decisions against historical data before execution, implementing sophisticated order routing to minimize slippage and market impact, maintaining detailed transaction logs for regulatory compliance, providing real-time explainability for all trades to satisfy stakeholder oversight, handling network latency and exchange API limitations gracefully, and incorporating continuous reinforcement learning from realized profits and losses to evolve strategies while avoiding overfitting to recent market conditions.

### cURL Command
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-openai-api-key-here" \
  -d '{
    "problem": "Architect a sophisticated multi-agent AI system for autonomous cryptocurrency and forex trading that employs sentiment analysis agents monitoring social media and news feeds, technical analysis agents identifying chart patterns and market indicators, fundamental analysis agents evaluating macroeconomic data and geopolitical events, risk management agents enforcing position limits and stop-losses, portfolio optimization agents balancing asset allocation across multiple exchanges, arbitrage detection agents exploiting price discrepancies between markets, all coordinated by a meta-agent that synthesizes signals from individual agents using ensemble methods while adapting trading strategies based on market regime detection (bull, bear, sideways, high volatility), backtesting all decisions against historical data before execution, implementing sophisticated order routing to minimize slippage and market impact, maintaining detailed transaction logs for regulatory compliance, providing real-time explainability for all trades to satisfy stakeholder oversight, handling network latency and exchange API limitations gracefully, and incorporating continuous reinforcement learning from realized profits and losses to evolve strategies while avoiding overfitting to recent market conditions.",
    "mode": "deep",
    "model": "gpt-4o"
  }'
```

### Postman/JSON Body
```json
{
  "problem": "Architect a sophisticated multi-agent AI system for autonomous cryptocurrency and forex trading that employs sentiment analysis agents monitoring social media and news feeds, technical analysis agents identifying chart patterns and market indicators, fundamental analysis agents evaluating macroeconomic data and geopolitical events, risk management agents enforcing position limits and stop-losses, portfolio optimization agents balancing asset allocation across multiple exchanges, arbitrage detection agents exploiting price discrepancies between markets, all coordinated by a meta-agent that synthesizes signals from individual agents using ensemble methods while adapting trading strategies based on market regime detection (bull, bear, sideways, high volatility), backtesting all decisions against historical data before execution, implementing sophisticated order routing to minimize slippage and market impact, maintaining detailed transaction logs for regulatory compliance, providing real-time explainability for all trades to satisfy stakeholder oversight, handling network latency and exchange API limitations gracefully, and incorporating continuous reinforcement learning from realized profits and losses to evolve strategies while avoiding overfitting to recent market conditions.",
  "mode": "deep",
  "model": "gpt-4o"
}
```

### Python Code
```python
import requests
import json

response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    headers={
        "Content-Type": "application/json",
        "X-API-Key": "your-openai-api-key-here"
    },
    json={
        "problem": "Architect a sophisticated multi-agent AI system for autonomous cryptocurrency and forex trading that employs sentiment analysis agents monitoring social media and news feeds, technical analysis agents identifying chart patterns and market indicators, fundamental analysis agents evaluating macroeconomic data and geopolitical events, risk management agents enforcing position limits and stop-losses, portfolio optimization agents balancing asset allocation across multiple exchanges, arbitrage detection agents exploiting price discrepancies between markets, all coordinated by a meta-agent that synthesizes signals from individual agents using ensemble methods while adapting trading strategies based on market regime detection (bull, bear, sideways, high volatility), backtesting all decisions against historical data before execution, implementing sophisticated order routing to minimize slippage and market impact, maintaining detailed transaction logs for regulatory compliance, providing real-time explainability for all trades to satisfy stakeholder oversight, handling network latency and exchange API limitations gracefully, and incorporating continuous reinforcement learning from realized profits and losses to evolve strategies while avoiding overfitting to recent market conditions.",
        "mode": "deep",
        "model": "gpt-4o"
    }
)

result = response.json()

print("=" * 80)
print("DEEP ANALYSIS RESULTS")
print("=" * 80)

# Show all options evaluated
print(f"\n📊 Total Options Evaluated: {len(result['all_options'])}")
for i, option in enumerate(result['all_options'], 1):
    eval_data = result['evaluations'][i-1]
    print(f"\nOption {i}: {option['template']['acronym']} + {option['technique']['name']}")
    print(f"  Total Score: {eval_data['total_score']}/40")
    print(f"  Scores: Fit={eval_data['scores']['problem_fit']}, "
          f"Clarity={eval_data['scores']['clarity']}, "
          f"Effectiveness={eval_data['scores']['effectiveness']}, "
          f"Flexibility={eval_data['scores']['flexibility']}")
    print(f"  Strengths: {', '.join(option['strengths'][:2])}")
    print(f"  Weaknesses: {', '.join(option['weaknesses'][:2])}")

# Show winner
print(f"\n🏆 WINNER: {result['recommended_template']['acronym']} + {result['recommended_technique']['name']}")
print(f"Reasoning: {result['winner_reasoning'][:200]}...")

# Save detailed results
with open('deep_analysis_result.json', 'w') as f:
    json.dump(result, f, indent=2)
print(f"\n💾 Full results saved to: deep_analysis_result.json")
```

### Expected Analysis
- **Complexity**: Very High
- **Requires Creativity**: Medium (novel agent coordination strategies)
- **Requires Data Analysis**: Yes (market data, performance metrics)
- **Has Constraints**: Yes (regulatory, latency, exchange limits)
- **Requires Step-by-Step**: Yes (agent workflow, decision pipeline)

### Likely Options in Deep Mode
1. **D-R-E-A-M + Tree of Thought**: For exploring multiple trading strategies simultaneously
2. **M-I-N-D-S + Self-Consistency**: For market strategy with validated decisions
3. **R-I-S-E + Chain of Thought**: For step-by-step agent coordination with reasoning

### Deep Mode Expected Output Structure
```json
{
  "mode": "deep",
  "all_options": [
    {
      "option_number": 1,
      "template": {"acronym": "D-R-E-A-M", "name": "..."},
      "technique": {"name": "Tree of Thought Prompting"},
      "reasoning": "Allows parallel exploration of trading strategies...",
      "strengths": [
        "Handles multiple agent coordination naturally",
        "Built-in data analysis framework"
      ],
      "weaknesses": [
        "May be overly complex for simple decisions",
        "Requires significant computational resources"
      ]
    },
    // ... 2 more options
  ],
  "evaluations": [
    {
      "option_number": 1,
      "scores": {
        "problem_fit": 9,
        "clarity": 8,
        "effectiveness": 9,
        "flexibility": 8
      },
      "total_score": 34,
      "analysis": "Excellent match for multi-agent systems..."
    }
    // ... 2 more evaluations
  ],
  "winner_reasoning": "Selected for highest problem fit and effectiveness scores...",
  "recommended_template": {"acronym": "D-R-E-A-M", "name": "..."},
  "recommended_technique": {"name": "Tree of Thought Prompting"}
}
```

---

## 🎯 Why These Problems Are Complex

### Problem 1: Healthcare AI (Fast Mode)
**Complexity Factors:**
- ✅ Multiple data sources (vitals, history, labs, symptoms)
- ✅ Real-time processing requirements
- ✅ Regulatory constraints (HIPAA)
- ✅ Dual audience (physicians + patients)
- ✅ Safety-critical (life and death decisions)
- ✅ Uncertainty handling (conflicting data)
- ✅ Continuous learning requirement
- ✅ Audit trail necessity
- ✅ Integration challenges (EHR systems)

### Problem 2: Trading Platform (Deep Mode)
**Complexity Factors:**
- ✅ Multi-agent coordination
- ✅ Multiple analysis types (sentiment, technical, fundamental)
- ✅ Real-time decision making
- ✅ Risk management constraints
- ✅ Market regime adaptation
- ✅ Regulatory compliance
- ✅ Distributed system challenges (latency, API limits)
- ✅ Reinforcement learning loop
- ✅ Explainability requirements
- ✅ Overfitting prevention

---

## 📝 Quick Copy-Paste Commands

### Fast Mode (Healthcare)
```bash
# cURL
curl -X POST http://localhost:8000/api/v1/analyze/fast \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-key" \
  -d '{"problem": "Design and implement an AI-powered clinical decision support system for emergency departments that can analyze patient vital signs, medical history, lab results, and real-time symptoms to provide differential diagnoses with confidence scores, flag critical conditions requiring immediate intervention, integrate with existing electronic health records (EHR) systems, maintain HIPAA compliance, explain reasoning in medical terminology for physicians while also providing patient-friendly summaries, handle edge cases like conflicting test results or incomplete data, prioritize diagnoses based on severity and likelihood, and continuously learn from physician feedback to improve accuracy over time while maintaining audit trails for all recommendations."}'
```

### Deep Mode (Trading)
```bash
# cURL
curl -X POST http://localhost:8000/api/v1/analyze/deep \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-key" \
  -d '{"problem": "Architect a sophisticated multi-agent AI system for autonomous cryptocurrency and forex trading that employs sentiment analysis agents monitoring social media and news feeds, technical analysis agents identifying chart patterns and market indicators, fundamental analysis agents evaluating macroeconomic data and geopolitical events, risk management agents enforcing position limits and stop-losses, portfolio optimization agents balancing asset allocation across multiple exchanges, arbitrage detection agents exploiting price discrepancies between markets, all coordinated by a meta-agent that synthesizes signals from individual agents using ensemble methods while adapting trading strategies based on market regime detection (bull, bear, sideways, high volatility), backtesting all decisions against historical data before execution, implementing sophisticated order routing to minimize slippage and market impact, maintaining detailed transaction logs for regulatory compliance, providing real-time explainability for all trades to satisfy stakeholder oversight, handling network latency and exchange API limitations gracefully, and incorporating continuous reinforcement learning from realized profits and losses to evolve strategies while avoiding overfitting to recent market conditions."}'
```

---

## ⏱️ Expected Performance

### Fast Mode (Healthcare)
- **Time**: ~8-12 seconds
- **API Calls**: 1
- **Cost**: ~$0.03-0.08 (gpt-4o)
- **Output**: Single recommendation with detailed reasoning

### Deep Mode (Trading)
- **Time**: ~20-30 seconds
- **API Calls**: 2
- **Cost**: ~$0.08-0.15 (gpt-4o)
- **Output**: 3 options evaluated + winner selection

---

## 🔍 What to Look For in Results

### Fast Mode Response Check:
✅ `recommended_template.acronym` is populated
✅ `recommended_technique.name` is populated
✅ `example_prompt` is generated
✅ `problem_analysis.complexity` shows "high"
✅ `metadata.mode` equals "fast"

### Deep Mode Response Check:
✅ `all_options` contains 3 different combinations
✅ `evaluations` has scores for all 3 options
✅ `winner_reasoning` explains the selection
✅ Each option has `strengths` and `weaknesses`
✅ `metadata.mode` equals "deep"

---

**Ready to test! 🚀**
