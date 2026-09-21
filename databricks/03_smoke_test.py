# Databricks notebook source
# =============================================================================
# 03_smoke_test.py
# ①② の動作確認と、Salesforce 側設定に必要な値（warehouse_id）の取得
# ③ は Genie ベースなので 04_deploy_genie_agent.py の STEP 5 で確認する。
# =============================================================================

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "sfdc_poc"
FQ = f"{CATALOG}.{SCHEMA}"

# COMMAND ----------
# ----- ① サマリ -----
summary_spec = spark.sql(
    f"SELECT {FQ}.get_sales_summary_spec('関東', '2026-Q3') AS v"
).collect()[0]["v"]
print(summary_spec)

# COMMAND ----------
# ----- ② 明細レポート -----
report_spec = spark.sql(
    f"SELECT {FQ}.get_sales_report_spec('関東', '2026-Q3') AS v"
).collect()[0]["v"]
print(report_spec)

# COMMAND ----------
# ----- 利用可能なサービングエンドポイント一覧 -----
# ③ の sfdc-genie-agent が出ていること。カスタムエンドポイントが
# 増えていると Free Edition の枠を食うので、ここで気づける。
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
for ep in w.serving_endpoints.list():
    print(ep.name)

# COMMAND ----------
# ----- Salesforce 側の設定に必要な値 -----
# ここで出た warehouse_id を Apex の DatabricksSqlClient.WAREHOUSE_ID に設定する。
for wh in w.warehouses.list():
    print(f"warehouse_id = {wh.id}   name = {wh.name}   state = {wh.state}")

print("\nworkspace host =", w.config.host)
print("catalog/schema =", FQ)

# COMMAND ----------

# bundle run の Output に出す要約。
warehouse = next(iter(w.warehouses.list()), None)
dbutils.notebook.exit(
    " / ".join([
        f"① spec {len(summary_spec)}字",
        f"② spec {len(report_spec)}字",
        f"warehouse_id={warehouse.id if warehouse else 'なし'}",
        f"endpoints={[ep.name for ep in w.serving_endpoints.list()]}",
    ])
)
