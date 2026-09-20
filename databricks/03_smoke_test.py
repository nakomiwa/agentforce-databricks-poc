# Databricks notebook source
# =============================================================================
# 03_smoke_test.py
# ①②③ の動作確認と、Salesforce 側設定に必要な値（warehouse_id）の取得
# =============================================================================

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "sfdc_poc"
FQ = f"{CATALOG}.{SCHEMA}"

# COMMAND ----------
# ----- ① JSON -----
print(spark.sql(f"SELECT {FQ}.get_sales_summary_json('関東', '2026-Q3') AS v").collect()[0]["v"])

# COMMAND ----------
# ----- ② HTML -----
html = spark.sql(f"SELECT {FQ}.get_sales_report_html('関東', '2026-Q3') AS v").collect()[0]["v"]
print(html[:1500])
displayHTML(html)

# COMMAND ----------
# ----- ③ エージェント -----
print(spark.sql(f"SELECT {FQ}.ask_sales_agent('関東と関西では、どちらが受注率が高いですか。理由も述べてください。') AS v").collect()[0]["v"])

# COMMAND ----------
# ----- 利用可能なサービングエンドポイント一覧 -----
# ③ でモデルエラーが出る場合は、ここに出たエンドポイント名を
# 02_register_uc_functions.py の MODEL_ENDPOINT に設定し直して再実行する。
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
