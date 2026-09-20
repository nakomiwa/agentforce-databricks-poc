#!/usr/bin/env bash
# =============================================================================
# Salesforce が実際に叩くのと同じ HTTP リクエストを curl で再現して疎通確認する。
# Apex を書く前にこれが通ることを必ず確認すること。
# =============================================================================
set -euo pipefail

: "${DATABRICKS_HOST:?例: https://dbc-xxxxxxxx-xxxx.cloud.databricks.com}"
: "${DATABRICKS_TOKEN:?Databricks の個人用アクセストークン (PAT)}"
: "${WAREHOUSE_ID:?03_smoke_test.py で確認した SQL ウェアハウス ID}"

CATALOG=workspace
SCHEMA=sfdc_poc

call() {
  local fn="$1"; shift
  local stmt="$1"; shift
  local params="$1"; shift
  echo "===== ${fn} ====="
  curl -sS -X POST "${DATABRICKS_HOST}/api/2.0/sql/statements" \
    -H "Authorization: Bearer ${DATABRICKS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
          \"warehouse_id\": \"${WAREHOUSE_ID}\",
          \"statement\": \"${stmt}\",
          \"parameters\": ${params},
          \"wait_timeout\": \"50s\",
          \"on_wait_timeout\": \"CANCEL\",
          \"format\": \"JSON_ARRAY\",
          \"disposition\": \"INLINE\"
        }"
  echo; echo
}

call "① get_sales_summary_json" \
  "SELECT ${CATALOG}.${SCHEMA}.get_sales_summary_json(:p_region, :p_period) AS v" \
  '[{"name":"p_region","value":"関東","type":"STRING"},{"name":"p_period","value":"2026-Q3","type":"STRING"}]'

call "② get_sales_report_html" \
  "SELECT ${CATALOG}.${SCHEMA}.get_sales_report_html(:p_region, :p_period) AS v" \
  '[{"name":"p_region","value":"関東","type":"STRING"},{"name":"p_period","value":"2026-Q3","type":"STRING"}]'

call "③ ask_sales_agent" \
  "SELECT ${CATALOG}.${SCHEMA}.ask_sales_agent(:p_question) AS v" \
  '[{"name":"p_question","value":"最も受注率が高い地域はどこですか","type":"STRING"}]'
