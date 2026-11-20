#!/usr/bin/env bash
# Runs every unit test suite. Needs no cloud, no database server, no Docker and no LLM key.
#   pip install -r agent/requirements-dev.txt
#   ./run_tests.sh
set -euo pipefail
cd "$(dirname "$0")"
status=0
for suite in billing_api mcp_server agent; do
  echo "================ $suite ================"
  (cd "$suite" && python -m pytest -v "$@") || status=1
done
exit $status
