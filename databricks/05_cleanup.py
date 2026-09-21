# Databricks notebook source
# =============================================================================
# 05_cleanup.py
#
# 検証中に作った不要な資材を片付ける保守ジョブ。
#
# 【なぜ必要か】
#   Free Edition は Model Serving の provisioned concurrency の枠が非常に小さい。
#   検証用エンドポイントや古いモデルバージョンが配信されたまま残っていると、
#   次のデプロイが Quota Exceeded で落ちる。実際に一度落ちている。
#
# 【やること】
#   1. 検証用エンドポイント（PROBE_ENDPOINTS）を削除
#   2. 検証用 UC モデル（PROBE_MODELS）を削除
#   3. 本番エンドポイントの配信エンティティを最新 1 本に絞る
#
# 【安全装置】DRY_RUN = True なら何も消さず、消す対象を表示するだけ。
#            まず DRY_RUN で中身を確認してから False にすること。
# =============================================================================

import time
import traceback

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    Route,
    ServedEntityInput,
    TrafficConfig,
)

# ----- 設定 -------------------------------------------------------------
DRY_RUN = False

CATALOG = "workspace"
SCHEMA = "sfdc_poc"

# 検証のためだけに作ったもの。残す理由がない
PROBE_ENDPOINTS = ["sfdc-probe-echo"]
PROBE_MODELS = [f"{CATALOG}.{SCHEMA}.probe_echo"]

# 本番で使うエンドポイント。最新バージョン 1 本だけを残す
KEEP_LATEST_ONLY = ["sfdc-genie-agent"]
# ------------------------------------------------------------------------

w = WorkspaceClient()
tag = "[DRY RUN] " if DRY_RUN else ""

# 何をしたかを記録する。bundle run の Output に出すのはこちら。
# 「片付け後の状態」だけでは、更新が非同期なので直後は古い値が見える。
actions = []

print("=" * 72)
print(f"{tag}STEP 1  現状の棚卸し")
print("=" * 72)

endpoints = list(w.serving_endpoints.list())
for ep in endpoints:
    ready = ep.state.ready.value if ep.state and ep.state.ready else "?"
    print(f"  エンドポイント {ep.name}  ready={ready}")
    for se in ((ep.config.served_entities if ep.config else None) or []):
        print(f"      - {se.name}  entity={se.entity_name} v{se.entity_version}")
print()


# -----------------------------------------------------------------------
# STEP 2: 検証用エンドポイントの削除
# -----------------------------------------------------------------------
print("=" * 72)
print(f"{tag}STEP 2  検証用エンドポイントの削除")
print("=" * 72)

existing = {ep.name for ep in endpoints}
for name in PROBE_ENDPOINTS:
    if name not in existing:
        print(f"  {name}: 既にありません")
        continue
    if DRY_RUN:
        print(f"  {name}: 削除対象")
        continue
    try:
        w.serving_endpoints.delete(name)
        actions.append(f"エンドポイント削除 {name}")
        print(f"  {name}: 削除しました")
    except Exception:
        traceback.print_exc()
print()


# -----------------------------------------------------------------------
# STEP 3: 検証用 UC モデルの削除
# -----------------------------------------------------------------------
print("=" * 72)
print(f"{tag}STEP 3  検証用 UC モデルの削除")
print("=" * 72)

for full_name in PROBE_MODELS:
    try:
        w.registered_models.get(full_name)
    except Exception:
        print(f"  {full_name}: 既にありません")
        continue
    if DRY_RUN:
        print(f"  {full_name}: 削除対象")
        continue
    try:
        w.registered_models.delete(full_name)
        actions.append(f"モデル削除 {full_name}")
        print(f"  {full_name}: 削除しました")
    except Exception:
        traceback.print_exc()
print()


# -----------------------------------------------------------------------
# STEP 4: 本番エンドポイントを最新 1 本に絞る
#   agents.deploy は新バージョンを足すだけで古い配信を消さない。
#   古い served entity が枠を食い続けるので、ここで落とす。
# -----------------------------------------------------------------------
print("=" * 72)
print(f"{tag}STEP 4  配信エンティティを最新 1 本に絞る")
print("=" * 72)

for name in KEEP_LATEST_ONLY:
    try:
        ep = w.serving_endpoints.get(name)
    except Exception:
        print(f"  {name}: エンドポイントがありません")
        continue

    served = (ep.config.served_entities if ep.config else None) or []
    if len(served) <= 1:
        print(f"  {name}: 配信は {len(served)} 本。絞る必要はありません")
        continue

    def _ver(se):
        try:
            return int(se.entity_version)
        except (TypeError, ValueError):
            return -1

    latest = max(served, key=_ver)
    drop = [se.name for se in served if se.name != latest.name]
    print(f"  {name}: 残す={latest.name}  外す={drop}")

    if DRY_RUN:
        continue

    # agents.deploy が付けた環境変数などを落とさないよう、既存の値を写し取る
    keep = ServedEntityInput(
        name=latest.name,
        entity_name=latest.entity_name,
        entity_version=latest.entity_version,
        workload_size=latest.workload_size,
        scale_to_zero_enabled=latest.scale_to_zero_enabled,
        environment_vars=latest.environment_vars,
    )
    try:
        w.serving_endpoints.update_config(
            name=name,
            served_entities=[keep],
            traffic_config=TrafficConfig(
                routes=[Route(served_model_name=latest.name, traffic_percentage=100)]
            ),
        )
        actions.append(f"{name} を {latest.name} 1本に（外した: {', '.join(drop)}）")
        print(f"  {name}: 更新を受理しました。反映を待ちます")

        # 受理直後は config がまだ古い値を返す。反映を待たないと
        # 後続の agents.deploy とぶつかる。
        for i in range(60):
            st = w.serving_endpoints.get(name).state
            upd = st.config_update.value if st and st.config_update else "NOT_UPDATING"
            if upd == "NOT_UPDATING":
                print(f"  {name}: 反映完了（{i * 10} 秒）")
                break
            time.sleep(10)
        else:
            actions.append(f"{name} の反映が 10 分で終わらず")
            print(f"  {name}: 10 分待っても反映が終わりませんでした")
    except Exception:
        traceback.print_exc()
        actions.append(f"{name} の更新に失敗")

print()
print("=" * 72)
print("完了")
print("=" * 72)

# COMMAND ----------

# bundle run の Output に出す要約。片付けた結果の実際の状態を出す。
after = []
for ep in w.serving_endpoints.list():
    n = len((ep.config.served_entities if ep.config else None) or [])
    after.append(f"{ep.name}(配信{n}本)")

dbutils.notebook.exit(
    tag
    + "実施: " + ("; ".join(actions) or "なし（片付け対象なし）")
    + " || カスタムエンドポイント: "
    + (", ".join(a for a in after if not a.startswith("databricks-")) or "なし")
)
