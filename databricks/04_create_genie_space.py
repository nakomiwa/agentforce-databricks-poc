# =============================================================================
# 04_create_genie_space.py
#
# ③-B 用の Genie Space を API で作成し、そのまま疎通テストまで行う。
#
# 【実行場所】手元の PC（Databricks ノートブックではない）
#     pip install requests
#     python 04_create_genie_space.py
#
# 【トークンの扱い】
#     環境変数 DATABRICKS_TOKEN があればそれを使う。
#     無ければ実行時に入力を求める（画面に表示されず、ファイルにも残らない）。
#     チャットに貼らないこと。
#
# 【このスクリプトがやること】
#     0. 既存 Genie Space を一覧し、あれば serialized_space を取得して
#        「正解の JSON 構造」をテンプレートとして学習する
#     1. workspace.sfdc_poc.accounts / opportunities を対象にした Space を作成
#     2. space_id を genie_space_id.txt に保存
#     3. 日本語で質問を投げ、ポーリングして回答と生成SQLを表示
#
#     作成に失敗しても、エラー本文をそのまま表示するので原因が分かる。
#     作成した Space は Databricks の UI からいつでも削除できる。
# =============================================================================

import json
import os
import sys
import time
from getpass import getpass

import requests

# ----- 設定 -------------------------------------------------------------
HOST = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "e97a8ff7fddc4165")

CATALOG = "workspace"
SCHEMA = "sfdc_poc"
TABLES = [f"{CATALOG}.{SCHEMA}.accounts", f"{CATALOG}.{SCHEMA}.opportunities"]

SPACE_TITLE = "営業データ アシスタント (Agentforce 連携用)"
SPACE_DESCRIPTION = "Agentforce の ③ カスタムエージェントから呼び出す Genie Space。SFDC PoC 用のダミー営業データを対象とする。"

# Genie に与える指示。日本語で答えさせるのが目的。
SPACE_PROMPT = """あなたは日本の法人営業チームを支援するアシスタントです。

必ず日本語で回答してください。

データについて:
- accounts は顧客企業のマスタです。region 列には 関東 / 関西 / 中部 / 九州 / 東北 / 北海道 が入ります。
- opportunities は商談（案件）です。amount は日本円、stage には 受注 / 失注 / 最終交渉 などが入り、
  fiscal_quarter には 2026-Q1 〜 2026-Q4 が入ります。
- accounts と opportunities は account_id で結合します。

回答の作法:
- 金額は「1,234,567 円」のように3桁区切りで表記してください。
- 「受注率」を聞かれた場合は、stage = '受注' の件数 ÷ 全件数 で計算してください。
- 件数や金額を答えるときは、対象期間と地域を明示してください。
- 推測で数値を作らないでください。データから計算できない場合はその旨を述べてください。
"""

SMOKE_TEST_QUESTION = "関東エリアの2026-Q1の受注金額の合計と受注率を教えてください。"

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(HERE, "genie_space_template.json")
SPACE_ID_PATH = os.path.join(HERE, "genie_space_id.txt")
# ------------------------------------------------------------------------


def die(msg):
    print(f"\n[NG] {msg}")
    sys.exit(1)


def resolve_config():
    global HOST, TOKEN, WAREHOUSE_ID
    if not HOST:
        HOST = input("Databricks のワークスペース URL (https://dbc-xxxx.cloud.databricks.com): ").strip().rstrip("/")
    if not TOKEN:
        TOKEN = getpass("Databricks の個人アクセストークン (入力は表示されません): ").strip()
    if not WAREHOUSE_ID:
        WAREHOUSE_ID = input("SQL ウェアハウス ID: ").strip()
    if not (HOST and TOKEN and WAREHOUSE_ID):
        die("HOST / TOKEN / WAREHOUSE_ID が揃っていません。")


def api(method, path, **kwargs):
    url = f"{HOST}{path}"
    res = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        timeout=90,
        **kwargs,
    )
    return res


def show_error(label, res):
    print(f"  -> HTTP {res.status_code}")
    body = res.text
    print("  -> " + (body if len(body) <= 1500 else body[:1500] + " ...(略)"))


# -----------------------------------------------------------------------
# STEP 0: 既存 Space から正解の JSON 構造を学習する
# -----------------------------------------------------------------------
def learn_template():
    print("=" * 72)
    print("STEP 0  既存の Genie Space を確認（JSON 構造の学習）")
    print("=" * 72)

    res = api("GET", "/api/2.0/genie/spaces", params={"page_size": 20})
    if res.status_code != 200:
        print("  既存 Space の一覧を取得できませんでした（作成は続行します）")
        show_error("list", res)
        return None

    spaces = res.json().get("spaces", []) or []
    print(f"  既存 Space: {len(spaces)} 件")
    for s in spaces:
        print(f"    - {s.get('space_id')}  {s.get('title')}")

    if not spaces:
        print("  既存 Space なし。想定構造で作成を試みます。")
        return None

    sid = spaces[0]["space_id"]
    res = api("GET", f"/api/2.0/genie/spaces/{sid}", params={"include_serialized_space": "true"})
    if res.status_code != 200:
        print("  serialized_space を取得できませんでした（作成は続行します）")
        show_error("get_space", res)
        return None

    serialized = res.json().get("serialized_space")
    if not serialized:
        print("  serialized_space が空でした。")
        return None

    with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
        f.write(serialized)
    print(f"  [OK] 既存 Space の構造を {TEMPLATE_PATH} に保存しました。")

    try:
        parsed = json.loads(serialized)
        print(f"  トップレベルのキー: {list(parsed.keys())}")
        return parsed
    except Exception:
        print("  serialized_space を JSON として解釈できませんでした。")
        return None


# -----------------------------------------------------------------------
# STEP 1: Space を作成する
# -----------------------------------------------------------------------
def candidate_payloads(template):
    """serialized_space の候補をいくつか用意する。上から順に試す。"""
    cands = []

    # 候補 A: 既存 Space の構造を流用し、テーブルと指示だけ差し替える
    if isinstance(template, dict):
        import copy

        t = copy.deepcopy(template)
        t.pop("space_id", None)
        t.pop("etag", None)
        ds = t.get("data_sources")
        if isinstance(ds, dict) and isinstance(ds.get("tables"), list) and ds["tables"]:
            sample = ds["tables"][0]
            if isinstance(sample, dict):
                key = "identifier" if "identifier" in sample else list(sample.keys())[0]
                ds["tables"] = [{key: name} for name in TABLES]
            else:
                ds["tables"] = list(TABLES)
        else:
            t["data_sources"] = {"tables": [{"identifier": n} for n in TABLES]}
        instr = t.get("instructions")
        if isinstance(instr, dict):
            instr["prompt"] = SPACE_PROMPT
            instr.pop("example_question_sqls", None)
        else:
            t["instructions"] = {"prompt": SPACE_PROMPT}
        t["title"] = SPACE_TITLE
        t["description"] = SPACE_DESCRIPTION
        cands.append(("A: 既存Spaceの構造を流用", t))

    # 候補 B: コミュニティで報告されている構造（tables は dict）
    cands.append(
        (
            "B: data_sources.tables = [{identifier: ...}]",
            {
                "version": 1,
                "title": SPACE_TITLE,
                "description": SPACE_DESCRIPTION,
                "data_sources": {"tables": [{"identifier": n} for n in TABLES]},
                "instructions": {"prompt": SPACE_PROMPT},
            },
        )
    )

    # 候補 C: tables を文字列配列で
    cands.append(
        (
            "C: data_sources.tables = [文字列]",
            {
                "version": 1,
                "title": SPACE_TITLE,
                "description": SPACE_DESCRIPTION,
                "data_sources": {"tables": list(TABLES)},
                "instructions": {"prompt": SPACE_PROMPT},
            },
        )
    )

    # 候補 D: 最小構成（テーブルだけ）
    cands.append(
        (
            "D: 最小構成",
            {
                "version": 1,
                "data_sources": {"tables": [{"identifier": n} for n in TABLES]},
            },
        )
    )

    return cands


def create_space(template):
    print()
    print("=" * 72)
    print("STEP 1  Genie Space を作成")
    print("=" * 72)
    print(f"  対象テーブル: {', '.join(TABLES)}")
    print(f"  ウェアハウス: {WAREHOUSE_ID}")
    print()

    for label, serialized in candidate_payloads(template):
        print(f"  試行 [{label}]")
        body = {
            "warehouse_id": WAREHOUSE_ID,
            "serialized_space": json.dumps(serialized, ensure_ascii=False),
            "title": SPACE_TITLE,
            "description": SPACE_DESCRIPTION,
        }
        res = api("POST", "/api/2.0/genie/spaces", json=body)
        if res.status_code == 200:
            space_id = res.json().get("space_id")
            print(f"  [OK] 作成できました。space_id = {space_id}")
            with open(SPACE_ID_PATH, "w", encoding="utf-8") as f:
                f.write(space_id + "\n")
            print(f"       {SPACE_ID_PATH} に保存しました。")
            return space_id
        show_error(label, res)
        print()

    print("  [NG] すべての候補で作成に失敗しました。")
    print("       上のエラー本文をそのまま共有してください。構造を直します。")
    print("       （UI から手動で作る場合は、Databricks 左メニューの Genie → 新規作成）")
    return None


# -----------------------------------------------------------------------
# STEP 2: 疎通テスト（start-conversation → ポーリング → 回答表示）
# -----------------------------------------------------------------------
def smoke_test(space_id):
    print()
    print("=" * 72)
    print("STEP 2  疎通テスト")
    print("=" * 72)
    print(f"  質問: {SMOKE_TEST_QUESTION}")
    print()

    res = api(
        "POST",
        f"/api/2.0/genie/spaces/{space_id}/start-conversation",
        json={"content": SMOKE_TEST_QUESTION},
    )
    if res.status_code != 200:
        show_error("start-conversation", res)
        return

    started = res.json()
    conv_id = started.get("conversation_id")
    msg_id = started.get("message_id") or (started.get("message") or {}).get("id")
    print(f"  conversation_id = {conv_id}")
    print(f"  message_id      = {msg_id}")
    print()

    began = time.time()
    last_status = None
    message = None
    for _ in range(120):
        time.sleep(2)
        res = api(
            "GET",
            f"/api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages/{msg_id}",
        )
        if res.status_code != 200:
            show_error("get message", res)
            return
        message = res.json()
        status = message.get("status")
        if status != last_status:
            print(f"  [{time.time() - began:6.1f}s] {status}")
            last_status = status
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            break

    elapsed = time.time() - began
    print()
    print(f"  応答時間: {elapsed:.1f} 秒  ← Apex のポーリング設計で重要な実測値")
    print()

    if not message or message.get("status") != "COMPLETED":
        print("  [NG] 正常終了しませんでした。")
        print(json.dumps(message, ensure_ascii=False, indent=2)[:2000])
        return

    attachments = message.get("attachments") or []
    print(f"  attachments: {len(attachments)} 件")
    for att in attachments:
        aid = att.get("attachment_id")
        if att.get("text"):
            print()
            print("  --- Genie の回答 (text) ---")
            print("  " + (att["text"].get("content") or "").replace("\n", "\n  "))
        if att.get("query"):
            q = att["query"]
            print()
            print("  --- 生成された SQL ---")
            print("  説明: " + str(q.get("description")))
            print("  " + (q.get("query") or "").replace("\n", "\n  "))

            res = api(
                "GET",
                f"/api/2.0/genie/spaces/{space_id}/conversations/{conv_id}"
                f"/messages/{msg_id}/attachments/{aid}/query-result",
            )
            if res.status_code == 200:
                sr = (res.json() or {}).get("statement_response") or {}
                cols = (((sr.get("manifest") or {}).get("schema") or {}).get("columns")) or []
                rows = ((sr.get("result") or {}).get("data_array")) or []
                print()
                print("  --- クエリ結果 ---")
                print("  " + " | ".join(c.get("name", "") for c in cols))
                for r in rows[:10]:
                    print("  " + " | ".join(str(v) for v in r))
            else:
                show_error("query-result", res)

    print()
    print("=" * 72)
    print(f"完了。SPACE_ID = {space_id}")
    print("この space_id を共有してください。Apex 側を実装します。")
    print("=" * 72)


def main():
    resolve_config()
    print(f"\nHOST = {HOST}")
    print(f"WAREHOUSE_ID = {WAREHOUSE_ID}\n")

    template = learn_template()
    space_id = create_space(template)
    if space_id:
        smoke_test(space_id)


if __name__ == "__main__":
    main()
