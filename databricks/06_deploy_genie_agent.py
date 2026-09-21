# =============================================================================
# 06_deploy_genie_agent.py
#
# ③ の Genie ラッパーを Unity Catalog に登録し、Model Serving にデプロイする。
#
# 【前提】同じディレクトリに genie_agent.py があること
# 【実行】Databricks のノートブック（サーバーレス）でこのファイルをそのまま実行
#         または Git フォルダに置いてノートブックから実行
#
# 【事前に一度だけ】別セルで下記を実行してカーネルを再起動すること
#     %pip install -U -qqq mlflow databricks-agents databricks-sdk
#     dbutils.library.restartPython()
# =============================================================================

import os
import time
import traceback

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.models.resources import DatabricksGenieSpace, DatabricksSQLWarehouse
from mlflow.types.agent import ChatAgentMessage

# ----- 設定 -------------------------------------------------------------
CATALOG = "workspace"
SCHEMA = "sfdc_poc"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.genie_sales_agent"
ENDPOINT_NAME = "sfdc-genie-agent"
GENIE_SPACE_ID = "01f1b4f5cca01e879e5ae04b2823e9c9"
WAREHOUSE_ID = "e97a8ff7fddc4165"

AGENT_FILE = "genie_agent.py"
TEST_QUESTION = "関東エリアの2026-Q1の案件は何件ありますか？"
SMOKE_QUESTION = "関東エリアの2026-Q1の受注金額の合計を教えてください。"
WAIT_MINUTES = 25
# ------------------------------------------------------------------------

w = WorkspaceClient()
mlflow.set_registry_uri("databricks-uc")

INPUT_EXAMPLE = {"messages": [{"role": "user", "content": TEST_QUESTION}]}

if not os.path.exists(AGENT_FILE):
    raise SystemExit(
        f"{AGENT_FILE} が見つかりません。"
        "同じディレクトリに置くか、%%writefile で作成してください。"
    )


# -----------------------------------------------------------------------
# STEP 1: デプロイ前にその場で動かす
#   ここで失敗するものはデプロイしても必ず失敗する。
#   同時に Genie のウォーム状態での応答時間を実測する。
# -----------------------------------------------------------------------
print("=" * 72)
print("STEP 1  ローカル確認（デプロイ前の動作確認と応答時間の実測）")
print("=" * 72)

from genie_agent import AGENT  # noqa: E402

began = time.time()
res = AGENT.predict([ChatAgentMessage(role="user", content=TEST_QUESTION)])
elapsed = time.time() - began

print(f"応答時間: {elapsed:.1f} 秒   ← Apex 設計に使う実測値")
print("-" * 60)
print(res.messages[0].content[:1000])
print("-" * 60)
print("SQL:", (res.custom_outputs or {}).get("sql"))
print()


# -----------------------------------------------------------------------
# STEP 2: Unity Catalog に登録
# -----------------------------------------------------------------------
print("=" * 72)
print("STEP 2  Unity Catalog に登録")
print("=" * 72)

with mlflow.start_run(run_name="genie_sales_agent"):
    info = mlflow.pyfunc.log_model(
        name="agent",
        python_model=AGENT_FILE,
        input_example=INPUT_EXAMPLE,
        registered_model_name=MODEL_NAME,
        resources=[
            DatabricksGenieSpace(genie_space_id=GENIE_SPACE_ID),
            DatabricksSQLWarehouse(warehouse_id=WAREHOUSE_ID),
        ],
        pip_requirements=["mlflow", "databricks-sdk"],
    )

print("[OK]", info.model_uri)

version = str(max(int(v.version) for v in w.model_versions.list(full_name=MODEL_NAME)))
print("     最新バージョン:", version)
print()


# -----------------------------------------------------------------------
# STEP 3: デプロイ（Genie への認証は resources 宣言により自動パススルー）
# -----------------------------------------------------------------------
print("=" * 72)
print("STEP 3  デプロイ")
print("=" * 72)

try:
    from databricks import agents

    agents.deploy(
        MODEL_NAME,
        version,
        endpoint_name=ENDPOINT_NAME,
        scale_to_zero=True,
    )
    print("[OK] agents.deploy を受理しました")
except Exception:
    print("[NG] agents.deploy が失敗しました:")
    traceback.print_exc()
    raise SystemExit(1)

print()


# -----------------------------------------------------------------------
# STEP 4: READY 待ち
# -----------------------------------------------------------------------
print("=" * 72)
print(f"STEP 4  READY 待ち（最大 {WAIT_MINUTES} 分）")
print("=" * 72)

def endpoint_state(ep):
    """列挙体の値だけを取り出す。str() だと NOT_READY に READY が含まれて誤判定する。"""
    ready = ep.state.ready.value if ep.state.ready else ""
    update = ep.state.config_update.value if ep.state.config_update else ""
    return ready, update


began = time.time()
last = None
ep = None
ready = ""

while time.time() - began < WAIT_MINUTES * 60:
    ep = w.serving_endpoints.get(ENDPOINT_NAME)
    ready, update = endpoint_state(ep)
    if (ready, update) != last:
        print(f"  [{time.time() - began:6.0f}s] ready={ready}  config_update={update}")
        last = (ready, update)
    # ready だけ見ると、旧バージョンが配信中でも抜けてしまう。
    # 新バージョンに切り替わったかは config_update == NOT_UPDATING で判定する。
    if ready == "READY" and update == "NOT_UPDATING":
        break
    if update in ("UPDATE_FAILED", "UPDATE_CANCELED"):
        break
    time.sleep(15)

print()
print(f"最終状態: ready={ready}  config_update={last[1] if last else ''}")

if ready != "READY":
    for cfg in (ep.pending_config, ep.config) if ep else []:
        if cfg:
            for se in (cfg.served_entities or []):
                print("---", se.name, se.state)
    raise SystemExit(1)

print()


# -----------------------------------------------------------------------
# STEP 5: 疎通確認（Salesforce と同じ呼び方）
# -----------------------------------------------------------------------
print("=" * 72)
print("STEP 5  疎通確認")
print("=" * 72)

# Salesforce がやるのと同じ生の HTTP で叩く。
# w.serving_endpoints.query() は dict を受け付けない（as_dict を呼ぶため）。
path = f"/serving-endpoints/{ENDPOINT_NAME}/invocations"
body = {"messages": [{"role": "user", "content": SMOKE_QUESTION}]}

out = None
for i in (1, 2):
    began = time.time()
    try:
        out = w.api_client.do("POST", path, body=body)
        print(f"{i}回目: {time.time() - began:.1f} 秒")
    except Exception as e:
        print(f"{i}回目: {time.time() - began:.1f} 秒 で失敗 -> {e}")

print("※ 2回目がウォーム状態の実測値。Apex の callout 上限は 120 秒。")
print(out)

print()
print("=" * 72)
print("完了。Apex に設定する値:")
print("  エンドポイント名:", ENDPOINT_NAME)
print("  URL            :", f"{w.config.host}/serving-endpoints/{ENDPOINT_NAME}/invocations")
print("=" * 72)
