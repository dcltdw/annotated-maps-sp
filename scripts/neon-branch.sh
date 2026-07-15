#!/usr/bin/env bash
# Create/delete a Neon database branch for an ephemeral pipeline run
# (M4 spec §4). The API key travels only in the Authorization header; the
# connection string is written to a FILE (for --set-file), never echoed.
#   neon-branch.sh create <branch-name> <out-file>
#   neon-branch.sh delete <branch-name>
set -euo pipefail

API=https://console.neon.tech/api/v2
for tool in curl jq; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done
: "${NEON_API_KEY:?NEON_API_KEY is required}"
: "${NEON_PROJECT_ID:?NEON_PROJECT_ID is required}"
DB_NAME=${NEON_DB_NAME:-neondb}
ROLE_NAME=${NEON_ROLE_NAME:-neondb_owner}

req() { # method path [json-body]
  local method=$1 path=$2 body=${3:-}
  curl -fsS -X "$method" "$API$path" \
    -H "Authorization: Bearer $NEON_API_KEY" \
    -H "Content-Type: application/json" \
    ${body:+-d "$body"}
}

branch_id_by_name() {
  req GET "/projects/$NEON_PROJECT_ID/branches" \
    | jq -r --arg n "$1" '.branches[] | select(.name == $n) | .id'
}

case "${1:-}" in
  create)
    NAME=${2:?branch name required}
    OUT=${3:?output file path required}
    echo "==> creating Neon branch $NAME"
    req POST "/projects/$NEON_PROJECT_ID/branches" \
      "{\"branch\": {\"name\": \"$NAME\"}, \"endpoints\": [{\"type\": \"read_write\"}]}" \
      > /dev/null
    BRANCH_ID=$(branch_id_by_name "$NAME")
    [ -n "$BRANCH_ID" ] || { echo "FAIL: branch $NAME not found after create" >&2; exit 1; }
    # The connection URI for the new branch's endpoint.
    URI=$(req GET "/projects/$NEON_PROJECT_ID/connection_uri?branch_id=$BRANCH_ID&database_name=$DB_NAME&role_name=$ROLE_NAME&pooled=false" \
      | jq -r '.uri')
    [ -n "$URI" ] && [ "$URI" != "null" ] || { echo "FAIL: no connection URI returned" >&2; exit 1; }
    # Django needs the PostGIS scheme.
    printf '%s' "${URI/postgresql:\/\//postgis://}" > "$OUT"
    echo "==> connection string written to $OUT (postgis://, not logged)"
    ;;
  delete)
    NAME=${2:?branch name required}
    BRANCH_ID=$(branch_id_by_name "$NAME" || true)
    if [ -z "$BRANCH_ID" ]; then
      echo "==> Neon branch $NAME not found (already gone) — nothing to delete"
      exit 0
    fi
    echo "==> deleting Neon branch $NAME ($BRANCH_ID)"
    req DELETE "/projects/$NEON_PROJECT_ID/branches/$BRANCH_ID" > /dev/null
    ;;
  *)
    echo "usage: $0 create <name> <out-file> | delete <name>" >&2
    exit 2
    ;;
esac
