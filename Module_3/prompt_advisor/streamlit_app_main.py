"""
Streamlit Web App for Prompt Advisor - Complete in One File
"""

import streamlit as st
import os
from prompt_advisor import PromptAdvisor, TEMPLATES, TECHNIQUES
import json

# Page config
st.set_page_config(page_title="Prompt Advisor", page_icon="🎯", layout="wide")

# Initialize session state
if 'advisor' not in st.session_state:
    st.session_state.advisor = None
if 'result' not in st.session_state:
    st.session_state.result = None
if 'cleaned_problem' not in st.session_state:
    st.session_state.cleaned_problem = None

# Sidebar
with st.sidebar:
    st.title("⚙️ Settings")

    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        value=os.getenv("OPENAI_API_KEY", "")
    )

    model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])

    if st.button("Initialize", type="primary"):
        if api_key:
            try:
                st.session_state.advisor = PromptAdvisor(api_key=api_key, model=model)
                st.success("✅ Ready!")
            except Exception as e:
                st.error(f"❌ {str(e)}")
        else:
            st.error("Provide API key")

    st.divider()

    with st.expander("📚 Templates"):
        for t in TEMPLATES:
            st.write(f"**{t.acronym}** - {t.name}")

    with st.expander("🎯 Techniques"):
        for t in TECHNIQUES:
            st.write(f"**{t.name}**")

# Main content
st.title("🎯 Prompt Advisor")
st.write("Analyze your business problem and get AI-powered template and technique recommendations")

# Examples
examples = {
    "Custom": "",
    "E-commerce": "Build a recommendation system for products based on browsing history and purchases",
    "Chatbot": "Design a customer service chatbot for telecom billing and support",
    "Marketing": "Create a sustainable fashion marketing campaign for millennials",
    "Finance": "Develop a loan risk assessment system with transparent reasoning"
}

selected = st.selectbox("Choose example or write custom:", list(examples.keys()))

# Analysis mode selection
st.write("**Analysis Mode:**")
col_mode1, col_mode2 = st.columns(2)
with col_mode1:
    mode_selected = st.radio(
        "Select mode",
        ["⚡ Fast (Single recommendation)", "🔬 Deep Analysis (Multiple options + LLM Judge)"],
        help="Fast: Quick single recommendation (~5 sec, 1 API call)\nDeep: Generate 3 options, evaluate with LLM judge (~15 sec, 2 API calls)"
    )

mode = "fast" if "Fast" in mode_selected else "deep"

if mode == "deep":
    st.info("🔬 Deep Analysis will:\n1. Generate 3 different template+technique combinations\n2. Use LLM as judge to evaluate each on 4 criteria\n3. Select the best option based on scores")

problem = st.text_area(
    "Business Problem",
    value=examples[selected],
    height=150,
    placeholder="Describe your problem in detail..."
)

col1, col2 = st.columns([1, 4])

with col1:
    analyze = st.button("🔍 Analyze", type="primary", disabled=not st.session_state.advisor)
with col2:
    if st.button("🗑️ Clear"):
        st.session_state.result = None
        st.rerun()

# Analyze
if analyze and problem.strip():
    analysis_mode = "fast" if "Fast" in mode_selected else "deep"
    mode_label = "⚡ Fast" if analysis_mode == "fast" else "🔬 Deep"

    with st.spinner(f"{mode_label} analysis in progress..."):
        try:
            # Clean the problem text first using the advisor's clean_text method
            cleaned_problem = PromptAdvisor.clean_text(problem)
            st.session_state.cleaned_problem = cleaned_problem  # Store for later display
            st.session_state.result = st.session_state.advisor.analyze_problem(cleaned_problem, mode=analysis_mode)
        except Exception as e:
            # Clean the error message too
            error_msg = str(e)
            try:
                cleaned_error = PromptAdvisor.clean_text(error_msg)
            except:
                cleaned_error = "An encoding error occurred. Please try rephrasing your problem."
            st.session_state.result = {"error": cleaned_error}

# Display results
if st.session_state.result:
    result = st.session_state.result

    if "error" in result:
        # Clean the error message before displaying
        error_msg = result["error"]
        try:
            cleaned_error = PromptAdvisor.clean_text(error_msg) if isinstance(error_msg, str) else str(error_msg)
        except:
            cleaned_error = "An error occurred"
        st.error(cleaned_error)
    else:
        st.success("✅ Analysis Complete")

        # Show what was analyzed
        if st.session_state.get('cleaned_problem'):
            with st.expander("📄 Your Problem (as sent to AI)", expanded=False):
                st.write(st.session_state.cleaned_problem)

        # Deep analysis: Show all options evaluated
        if result.get("mode") == "deep" and result.get("all_options"):
            st.subheader("🔬 Deep Analysis: All Options Evaluated")

            for i, option in enumerate(result["all_options"], 1):
                eval_data = result["evaluations"][i-1] if result.get("evaluations") else {}

                # Determine if this is the winner
                is_winner = i == result.get("winner_reasoning", "").split()[0] if result.get("winner_reasoning") else False

                with st.expander(f"{'🏆 ' if is_winner else ''}Option {i}: {option['template']['acronym']} + {option['technique']['name']}", expanded=is_winner):
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.write(f"**Template:** {option['template']['name']}")
                        st.write(f"**Technique:** {option['technique']['name']}")
                        st.write(f"**Reasoning:** {option['reasoning']}")

                        st.write("**Strengths:**")
                        for strength in option.get('strengths', []):
                            st.write(f"- ✅ {strength}")

                        st.write("**Weaknesses:**")
                        for weakness in option.get('weaknesses', []):
                            st.write(f"- ⚠️ {weakness}")

                    with col2:
                        if eval_data.get('scores'):
                            st.metric("Total Score", f"{eval_data['total_score']}/40")
                            scores = eval_data['scores']
                            st.write(f"**Breakdown:**")
                            st.write(f"Problem Fit: {scores.get('problem_fit', 0)}/10")
                            st.write(f"Clarity: {scores.get('clarity', 0)}/10")
                            st.write(f"Effectiveness: {scores.get('effectiveness', 0)}/10")
                            st.write(f"Flexibility: {scores.get('flexibility', 0)}/10")

                    if eval_data.get('analysis'):
                        st.info(f"**Judge's Analysis:** {eval_data['analysis']}")

            st.divider()
            st.success(f"🏆 **Winner Selected:** {result.get('winner_reasoning', 'N/A')}")

        # Analysis
        st.subheader("🔍 Problem Analysis")
        analysis = result.get("problem_analysis", {})

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Complexity", analysis.get('complexity', 'N/A').upper())
        col2.metric("Creative", "✓" if analysis.get('requires_creativity') else "✗")
        col3.metric("Data", "✓" if analysis.get('requires_data_analysis') else "✗")
        col4.metric("Constraints", "✓" if analysis.get('has_constraints') else "✗")

        # Template
        st.subheader("✨ Recommended Template")
        template = result.get("recommended_template", {})
        st.info(f"**{template.get('name')} ({template.get('acronym')})**")

        col1, col2 = st.columns(2)
        with col1:
            st.write("**Why:**", template.get('reasoning'))
        with col2:
            st.write("**How:**", template.get('application'))

        # Technique
        st.subheader("🎯 Recommended Technique")
        technique = result.get("recommended_technique", {})
        st.info(f"**{technique.get('name')}**")

        col1, col2 = st.columns(2)
        with col1:
            st.write("**Why:**", technique.get('reasoning'))
        with col2:
            st.write("**How:**", technique.get('application'))

        # Example
        if result.get("example_prompt"):
            st.subheader("📝 Example Prompt")
            st.code(result.get("example_prompt"), language="text")

        # Show the actual prompt used (what was sent to OpenAI)
        st.subheader("🔧 System Prompt Used")
        with st.expander("Click to see the full prompt sent to OpenAI"):
            if st.session_state.advisor:
                system_prompt = st.session_state.advisor._build_system_prompt()
                st.code(system_prompt, language="text")

            st.divider()
            st.write("**User Message Sent:**")
            user_problem = st.session_state.get('cleaned_problem', problem)
            st.code(f"Analyze this business problem:\n\n{user_problem}", language="text")

        # Download
        st.divider()
        col1, col2 = st.columns(2)

        with col1:
            st.download_button(
                "📥 Download JSON",
                json.dumps(result, indent=2),
                "recommendation.json",
                "application/json"
            )

        with col2:
            # Format the result as text
            if st.session_state.advisor:
                text = f"""PROBLEM:
{problem}

{st.session_state.advisor.format_recommendation(result)}
"""
            else:
                text = json.dumps(result, indent=2)

            st.download_button(
                "📥 Download Text",
                text,
                "recommendation.txt",
                "text/plain"
            )

st.divider()
st.caption("Built with OpenAI GPT-4 and Streamlit")