#!/usr/bin/env bash
# Canvas API smoke test.
# Usage: API_KEY=xxx ./smoke_canvas.sh [host]

set -euo pipefail

HOST="${1:-http://localhost:8000}"
KEY="${API_KEY:-$(cat server/.api_key 2>/dev/null || echo dev)}"

echo "== GET /api/v1/canvas =="
curl -fs -H "Authorization: Bearer $KEY" "$HOST/api/v1/canvas?entity_limit=5" \
  | python -m json.tool

echo
echo "== PATCH layout =="
curl -fs -X PATCH "$HOST/api/v1/canvas/layout" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"updates":[{"node_type":"entity","node_id":"smoke-test","x":1.0,"y":2.0}]}' \
  | python -m json.tool

echo
echo "== Cleanup =="
docker compose exec -T postgres psql -U m3 -d m3 -c \
  "DELETE FROM canvas_layout WHERE node_id = 'smoke-test';" > /dev/null

echo
echo "== Entity create/patch/delete =="
KEY="${API_KEY:-dev-key}"
EID=$(curl -fs -X POST "$HOST/api/v1/entities" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"canonical_name":"Smoke Entity","entity_type":"project"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "  created $EID"
curl -fs -X PATCH "$HOST/api/v1/entities/$EID" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"page_content":"# Smoke"}' > /dev/null
echo "  patched"
docker compose exec -T postgres psql -U m3 -d m3 -c \
  "DELETE FROM entities WHERE id = '$EID';" > /dev/null
echo "  cleaned"

echo "ok"
