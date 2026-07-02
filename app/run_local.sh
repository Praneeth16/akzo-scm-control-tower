#!/usr/bin/env bash
# Run the Streamlit app locally against a real Databricks workspace via a CLI profile.
# Requires: databricks CLI configured (`databricks configure`), .env filled from .env.example.
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

export DATABRICKS_CONFIG_PROFILE="${DATABRICKS_CONFIG_PROFILE:-DEFAULT}"

pip install -q -r requirements.txt
streamlit run app.py
