#!/bin/bash

# export CP_ACCESS_KEY="cp-MUt8N_utF_6l6G0rHnoFEw"
# export CP_SECRET_ACCESS_KEY="ny5KfSDqg128QJMw-3EX0Ml6YZAOIbmVUxshWXTW3dc"


API_URL="http://localhost:8000/api/admin/versions/"

# --- 1. Extract Path and Query from URL ---
# We use 'cut' to separate the protocol/host from the path/query
PATH_AND_QUERY=$(echo "$API_URL" | cut -d'/' -f4-)
# If the path is empty, default to /
[ -z "$PATH_AND_QUERY" ] && PATH_AND_QUERY="/"

# --- 2. Prepare Request Data ---
METHOD="GET"
TIMESTAMP=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
BODY='{"action": "delete", "target": "database_01"}'
BODY=' '

# --- 3. Create the String-to-Sign ---
# Order: Method + PathAndQuery + Timestamp + Body
# Using printf to avoid unexpected newlines from 'echo'
STRING_TO_SIGN=$(printf "%s\n%s\n%s\n%s" "$METHOD" "/$PATH_AND_QUERY" "$TIMESTAMP" "$BODY")

# --- 4. Generate the HMAC-SHA256 Signature ---
# cpkit API keys use an HMAC over the canonical request string. This example
# uses openssl's `dgst -sha256 -hmac` command so clients can reproduce the
# signature without depending on a language-specific SDK.
SIGNATURE=$(printf "%s" "$STRING_TO_SIGN" | openssl dgst -sha256 -hmac "$CP_SECRET_ACCESS_KEY" -hex | sed 's/^.* //')

# echo $STRING_TO_SIGN
# echo $SIGNATURE

# --- 5. Execute the Curl Command ---
curl -sS -X "$METHOD" "$API_URL" \
     -H "Content-Type: application/json" \
     -H "X-CP-Access-Key: $CP_ACCESS_KEY" \
     -H "X-Timestamp: $TIMESTAMP" \
     -H "X-CP-Signature: $SIGNATURE" \
     -d "$BODY"
