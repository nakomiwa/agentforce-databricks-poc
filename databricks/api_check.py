# =============================================================================
# api_check.py
# Salesforce が叩くのと同じ HTTP リクエストを再現して ①②③ の疎通を確認する。
#
# 【推奨】手元の PC で実行する（Salesforce と同じ「外部からの呼び出し」を再現できる）
#     pip install requests
#     python api_check.py
#
# 【代替】Databricks のノートブックに貼り付けて実行する
#     ワークスペース内からの呼び出しになるため「外部から届くか」の確認にはならないが、
#     SQL と関数が正しく動くかの確認はできる。
#     Free Edition は外向き通信が許可ドメインに限定されるため、失敗する場合は PC で実行すること。
# =============================================================================

import json
import os

import requests

# ----- 設定：環境変数が無ければ、この 3 行を直接書き換える --------------------
HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-xxxxxxxx-xxxx.cloud.databricks.com")
TOKEN = os.environ.get("DATABRICKS_TOKEN", "dapi...")
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "REPLACE_ME_WAREHOUSE_ID")
CATALOG = "workspace"
SCHEMA = "sfdc_poc"
# ---------------------------------------------------------------------------

HOST = HOST.rstrip("/")


def call(label, function_name, args):
    """UC 関数を SQL Statement Execution API 経由で呼ぶ"""
    arg_refs = ", ".join(f":{name}" for name, _ in args)
    statement = f"SELECT {CATALOG}.{SCHEMA}.{function_name}({arg_refs}) AS v"

    payload = {
        "warehouse_id": WAREHOUSE_ID,
        "statement": statement,
        "parameters": [
            {"name": name, "value": value, "type": "STRING"} for name, value in args
        ],
        "wait_timeout": "50s",
        "on_wait_timeout": "CANCEL",
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
    }

    print("=" * 70)
    print(f"{label}   {function_name}")
    print("=" * 70)

    res = requests.post(
        f"{HOST}/api/2.0/sql/statements",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=70,
    )

    if res.status_code != 200:
        print(f"NG  HTTP {res.status_code}")
        print(res.text[:800])
        return False

    body = res.json()
    state = body.get("status", {}).get("state")

    if state != "SUCCEEDED":
        print(f"NG  state = {state}")
        print(json.dumps(body.get("status", {}), ensure_ascii=False, indent=2)[:800])
        if state == "CANCELED":
            print("→ ウェアハウスの起動待ちでタイムアウトした可能性があります。"
                  "もう一度実行してください。")
        return False

    data_array = (body.get("result") or {}).get("data_array") or []
    if not data_array or not data_array[0] or data_array[0][0] is None:
        print("NG  結果が空でした（該当データなし、または関数が NULL を返した）")
        return False

    value = data_array[0][0]
    print(f"OK  state = SUCCEEDED / 応答長 = {len(value)} 文字")
    print("-" * 70)
    print(value[:1200] + (" ..." if len(value) > 1200 else ""))
    print()
    return True


def main():
    if "xxxxxxxx" in HOST or TOKEN.startswith("dapi...") or "REPLACE_ME" in WAREHOUSE_ID:
        print("先に HOST / TOKEN / WAREHOUSE_ID を設定してください。")
        print("  Windows PowerShell:")
        print('    $env:DATABRICKS_HOST="https://dbc-xxxx.cloud.databricks.com"')
        print('    $env:DATABRICKS_TOKEN="dapi..."')
        print('    $env:WAREHOUSE_ID="xxxxxxxxxxxx"')
        print("  macOS / Linux:")
        print('    export DATABRICKS_HOST="https://dbc-xxxx.cloud.databricks.com"')
        print('    export DATABRICKS_TOKEN="dapi..."')
        print('    export WAREHOUSE_ID="xxxxxxxxxxxx"')
        return

    results = [
        call("① 営業サマリ (JSON)", "get_sales_summary_json",
             [("p_region", "関東"), ("p_period", "2026-Q3")]),
        call("② 営業レポート (HTML)", "get_sales_report_html",
             [("p_region", "関東"), ("p_period", "2026-Q3")]),
        call("③ カスタムエージェント", "ask_sales_agent",
             [("p_question", "最も受注率が高い地域はどこですか")]),
    ]

    print("=" * 70)
    print(f"結果: {sum(results)} / {len(results)} 成功")
    print("=" * 70)
    if all(results):
        print("Databricks 側は完了です。Salesforce の設定（手順 B）に進んでください。")
    else:
        print("失敗したものがあります。README.md の「5. つまずいたときは」を確認してください。")


main()
