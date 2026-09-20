# =============================================================================
# 05_probe_model_serving.py
#
# 【目的】Free Edition で「カスタムモデルのサービングエンドポイント」を
#        作れるかどうかだけを確かめる。③ の Genie 実装の前提条件チェック。
#
# 【実行場所】Databricks のノートブック（サーバーレス）にこのまま貼って実行
#
# 【やること】
#   1. 何もしない超小さなモデル（入力をそのまま返すだけ）を Unity Catalog に登録
#   2. そのモデルのサービングエンドポイントを作成
#   3. READY になるまでポーリング（最大 15 分）
#   4. 実際に叩いて応答を確認
#   5. 後片付け（エンドポイントを削除）
#
# 【判定】
#   ✅ READY になって応答が返る → Model Serving が使える。③ の実装に進める
#   ❌ FAILED / タイムアウト     → Free Edition では使えない。別方式に切り替える
#      いずれの場合もエラー本文をそのまま表示するので、結果を共有してください。
#
# コミュニティでは Free Edition で "Container creation failed"(ビルドログ空)
# となる報告が複数あるため、ここで失敗しても想定内です。
# =============================================================================

import time
import traceback

import mlflow
import pandas as pd
from mlflow.models import infer_signature

# ----- 設定 -------------------------------------------------------------
CATALOG = "workspace"
SCHEMA = "sfdc_poc"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.probe_echo"
ENDPOINT_NAME = "sfdc-probe-echo"
WAIT_MINUTES = 15
CLEANUP = True  # 確認後にエンドポイントを削除する
# ------------------------------------------------------------------------

print("=" * 72)
print("STEP 0  環境の確認")
print("=" * 72)
print("mlflow:", mlflow.__version__)

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
print("host  :", w.config.host)


# -----------------------------------------------------------------------
# STEP 1: 最小のモデルを Unity Catalog に登録
# -----------------------------------------------------------------------
print()
print("=" * 72)
print("STEP 1  最小モデルを Unity Catalog に登録")
print("=" * 72)

mlflow.set_registry_uri("databricks-uc")


class Echo(mlflow.pyfunc.PythonModel):
    """入力をそのまま返すだけ。Model Serving が動くかを見るためだけのモデル。"""

    def predict(self, context, model_input, params=None):
        return ["echo: " + str(v) for v in model_input["text"]]


sample_input = pd.DataFrame({"text": ["hello"]})
sample_output = ["echo: hello"]
signature = infer_signature(sample_input, sample_output)

with mlflow.start_run(run_name="probe_echo"):
    try:
        # mlflow 3.x
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=Echo(),
            signature=signature,
            input_example=sample_input,
            registered_model_name=MODEL_NAME,
        )
    except TypeError:
        # mlflow 2.x
        info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=Echo(),
            signature=signature,
            input_example=sample_input,
            registered_model_name=MODEL_NAME,
        )

print("[OK] 登録しました:", info.model_uri)

versions = list(w.model_versions.list(full_name=MODEL_NAME))
version = str(max(int(v.version) for v in versions))
print("     最新バージョン:", version)


# -----------------------------------------------------------------------
# STEP 2: サービングエンドポイントを作成
# -----------------------------------------------------------------------
print()
print("=" * 72)
print("STEP 2  サービングエンドポイントを作成")
print("=" * 72)

from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ServedEntityInput,
)

served = ServedEntityInput(
    entity_name=MODEL_NAME,
    entity_version=version,
    workload_size="Small",
    scale_to_zero_enabled=True,
)

try:
    existing = w.serving_endpoints.get(ENDPOINT_NAME)
    print("既存のエンドポイントがあるので更新します:", existing.name)
    w.serving_endpoints.update_config(
        name=ENDPOINT_NAME, served_entities=[served]
    )
except Exception:
    print("新規作成します:", ENDPOINT_NAME)
    try:
        w.serving_endpoints.create(
            name=ENDPOINT_NAME,
            config=EndpointCoreConfigInput(served_entities=[served]),
        )
    except Exception as e:
        print()
        print("[NG] エンドポイントの作成そのものが拒否されました。")
        print("     ここで失敗した場合、Free Edition では Model Serving が使えません。")
        print()
        traceback.print_exc()
        raise SystemExit(1)

print("[OK] 作成リクエストを受け付けました。起動を待ちます。")


# -----------------------------------------------------------------------
# STEP 3: READY になるまで待つ
# -----------------------------------------------------------------------
print()
print("=" * 72)
print(f"STEP 3  READY になるまで待機（最大 {WAIT_MINUTES} 分）")
print("=" * 72)

began = time.time()
last = None
state = None

while time.time() - began < WAIT_MINUTES * 60:
    ep = w.serving_endpoints.get(ENDPOINT_NAME)
    # 列挙体の値だけを見る。str() だと NOT_READY に READY が含まれて誤判定する。
    ready = ep.state.ready.value if ep.state.ready else ""
    update = ep.state.config_update.value if ep.state.config_update else ""
    if (ready, update) != last:
        print(f"  [{time.time() - began:6.0f}s] ready={ready}  config_update={update}")
        last = (ready, update)

    if ready == "READY":
        state = "READY"
        break
    if update in ("UPDATE_FAILED", "UPDATE_CANCELED"):
        state = "FAILED"
        break
    time.sleep(15)

if state != "READY":
    print()
    print(f"[NG] READY になりませんでした（state={state}）。")
    print("     エンドポイント詳細:")
    try:
        ep = w.serving_endpoints.get(ENDPOINT_NAME)
        for pe in (ep.pending_config.served_entities if ep.pending_config else []) or []:
            print("      -", pe.name, pe.state)
        print("      config:", ep.config)
        print("      state :", ep.state)
    except Exception:
        traceback.print_exc()
    print()
    print("     ▼ Databricks の画面で「サービング」→ このエンドポイント →")
    print("       「イベント」「ビルドログ」を開いて、エラー本文を共有してください。")
    raise SystemExit(1)

print()
print(f"[OK] READY になりました（{time.time() - began:.0f} 秒）")


# -----------------------------------------------------------------------
# STEP 4: 実際に叩く
# -----------------------------------------------------------------------
print()
print("=" * 72)
print("STEP 4  エンドポイントを叩いて応答を確認")
print("=" * 72)

try:
    res = w.serving_endpoints.query(
        name=ENDPOINT_NAME,
        dataframe_records=[{"text": "こんにちは"}],
    )
    print("[OK] 応答:", res.predictions)
except Exception:
    print("[NG] 呼び出しに失敗しました。")
    traceback.print_exc()


# -----------------------------------------------------------------------
# STEP 5: 後片付け
# -----------------------------------------------------------------------
print()
print("=" * 72)
print("STEP 5  後片付け")
print("=" * 72)

if CLEANUP:
    try:
        w.serving_endpoints.delete(ENDPOINT_NAME)
        print("[OK] エンドポイントを削除しました:", ENDPOINT_NAME)
    except Exception:
        traceback.print_exc()
else:
    print("CLEANUP=False のため残しています:", ENDPOINT_NAME)

print()
print("=" * 72)
print("判定: Model Serving は【使えます】。③ の Genie 実装に進めます。")
print("=" * 72)
