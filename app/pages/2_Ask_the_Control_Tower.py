"""Ask the Control Tower — Genie-grounded NL Q&A chat.

Uses lib.text2sql.ask() (NL -> Spark SQL -> execute), not the Genie
Conversation API. The Genie Space in the workspace is a separate,
human-facing ad hoc exploration surface — see SETUP.md step 7.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import pandas as pd
import streamlit as st

import databricks_client as dbx
import text2sql

st.set_page_config(page_title="Ask the Control Tower — Akzo SCM", layout="wide")

st.title("Ask the Control Tower")
st.caption("Ask supply-chain questions in plain English — grounded in the governed OTIF, inventory, lanes, and service tables.")

EXAMPLE_QUESTIONS = [
    "Why did OTIF for Performance Coatings China drop in March 2026?",
    "Rank all lanes by lead time versus their mode average.",
    "Which SKUs stocked out at Guangzhou-CN in March 2026?",
    "Compare China OTIF to other regions for March 2026.",
    "Show the days-of-supply trend for PFC-2000 and PFC-2004.",
    "Show region-level service percent and backorders for the last 6 months.",
]

st.session_state.setdefault("messages", [])


def _summarize(question: str, rows: list[dict]) -> str:
    if not rows:
        return "No rows returned for this question."
    preview = pd.DataFrame(rows).head(20).to_dict(orient="records")
    raw = dbx.chat(
        messages=[
            {
                "role": "system",
                "content": "Summarize this SQL result in 2 sentences for a supply chain planner. Be concrete with numbers.",
            },
            {"role": "user", "content": f"Question: {question}\nRows: {preview}"},
        ],
        max_tokens=200,
    )
    return raw


def _run_question(question: str) -> None:
    st.session_state["messages"].append({"role": "user", "content": question})
    with st.spinner("Generating SQL and querying the warehouse..."):
        try:
            result = text2sql.ask(question)
            summary = _summarize(question, result["rows"])
            st.session_state["messages"].append(
                {
                    "role": "assistant",
                    "content": summary,
                    "sql": result["sql"],
                    "rows": result["rows"],
                }
            )
        except Exception as e:
            st.session_state["messages"].append(
                {"role": "assistant", "content": f"Could not answer that: {e}", "sql": None, "rows": None}
            )


with st.expander("Example questions"):
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        if st.button(q, key=f"example_{i}"):
            _run_question(q)
            st.rerun()

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("rows"):
            st.dataframe(pd.DataFrame(msg["rows"]), use_container_width=True)
        if msg.get("sql"):
            with st.expander("Show SQL"):
                st.code(msg["sql"], language="sql")

prompt = st.chat_input("Ask about OTIF, inventory, lanes, or service levels...")
if prompt:
    _run_question(prompt)
    st.rerun()
