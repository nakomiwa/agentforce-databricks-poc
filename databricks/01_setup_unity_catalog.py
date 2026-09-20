# Databricks notebook source
# =============================================================================
# 01_setup_unity_catalog.py
# Unity Catalog にダミー営業データを登録する
#
# 実行方法: Databricks ワークスペースにこのファイルをインポートし、
#           サーバーレスノートブックとして実行する
# =============================================================================

# COMMAND ----------

# ----- 設定 -------------------------------------------------------------
# Free Edition では新規カタログ作成が制限される場合があるため、
# 既定のカタログ "workspace" 配下にスキーマを作る構成にしている。
CATALOG = "workspace"
SCHEMA = "sfdc_poc"
N_ROWS = 180
SEED = 20260920
# ------------------------------------------------------------------------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'Agentforce 連携 PoC 用ダミー営業データ'")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")
print(f"target = {CATALOG}.{SCHEMA}")

# COMMAND ----------

import random
from datetime import date, timedelta

random.seed(SEED)

REGIONS = ["関東", "関西", "中部", "九州", "東北", "北海道"]
REGION_W = [38, 22, 16, 12, 8, 4]
INDUSTRIES = ["製造", "金融", "流通・小売", "公共", "情報通信", "運輸・物流"]
STAGES = ["見込", "提案", "見積提示", "最終交渉", "受注", "失注"]
STAGE_W = [18, 20, 16, 12, 22, 12]
QUARTERS = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]

SURNAMES = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤",
            "吉田", "山田", "松本", "井上", "木村", "林", "清水", "山口", "森", "池田"]
GIVEN = ["大輔", "健一", "彩", "美咲", "翔太", "直樹", "遥", "陽子", "拓也", "真由美",
         "隆", "香織", "悠斗", "千尋", "亮", "沙織"]

COMPANY_HEAD = ["朝日", "みらい", "大和", "東海", "北斗", "青葉", "瀬戸", "富士", "雅", "鶴見",
                "新光", "泉", "明和", "常磐", "白樺", "光洋", "五洋", "南海", "旭", "近畿"]
COMPANY_TAIL = ["商事", "製作所", "工業", "システムズ", "ホールディングス", "物流", "銀行", "運輸", "food", "電機"]

DEAL_THEME = ["基幹システム刷新", "データ基盤構築", "営業支援システム導入", "BI ダッシュボード整備",
              "生成AI活用 PoC", "在庫最適化", "顧客分析基盤", "コンタクトセンター高度化",
              "需要予測モデル開発", "帳票電子化", "MDM 導入", "ERP リプレース"]

def jp_name():
    return random.choice(SURNAMES) + " " + random.choice(GIVEN)

def company():
    return random.choice(COMPANY_HEAD) + random.choice(COMPANY_TAIL)

# 顧客マスタ
account_names = sorted({company() for _ in range(45)})
accounts = []
for i, name in enumerate(account_names, start=1):
    accounts.append({
        "account_id": f"ACC-{i:04d}",
        "account_name": name,
        "region": random.choices(REGIONS, weights=REGION_W)[0],
        "industry": random.choice(INDUSTRIES),
        "employee_count": random.choice([80, 150, 420, 900, 1800, 3500, 7200]),
    })

acc_by_name = {a["account_name"]: a for a in accounts}

# 案件
opportunities = []
for i in range(1, N_ROWS + 1):
    acc = random.choice(accounts)
    stage = random.choices(STAGES, weights=STAGE_W)[0]
    quarter = random.choice(QUARTERS)
    q_start = date(2026, 1 + (QUARTERS.index(quarter) * 3), 1)
    close_dt = q_start + timedelta(days=random.randint(0, 88))
    # 金額は 300万〜2.5億円（円）
    amount = random.choice([1, 1, 1, 2, 3, 5, 10]) * random.randint(3, 25) * 1_000_000
    opportunities.append({
        "opportunity_id": f"OPP-{i:05d}",
        "opportunity_name": f"{acc['account_name']} {random.choice(DEAL_THEME)}",
        "account_id": acc["account_id"],
        "account_name": acc["account_name"],
        "region": acc["region"],
        "industry": acc["industry"],
        "owner_name": jp_name(),
        "amount": int(amount),
        "stage": stage,
        "fiscal_quarter": quarter,
        "close_date": close_dt,
        "is_won": stage == "受注",
        "probability": {"見込": 10, "提案": 30, "見積提示": 50, "最終交渉": 75, "受注": 100, "失注": 0}[stage],
    })

print(f"accounts={len(accounts)}  opportunities={len(opportunities)}")

# COMMAND ----------

acc_df = spark.createDataFrame(accounts)
opp_df = spark.createDataFrame(opportunities)

acc_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.accounts")
opp_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.opportunities")

# 列コメント（UC のメタデータとして残す／エージェントのツール説明にも効く）
comments = {
    "opportunity_id": "案件ID",
    "opportunity_name": "案件名",
    "account_id": "顧客ID",
    "account_name": "顧客名",
    "region": "地域（関東/関西/中部/九州/東北/北海道）",
    "industry": "業種",
    "owner_name": "営業担当者名",
    "amount": "案件金額（円）",
    "stage": "商談フェーズ（見込/提案/見積提示/最終交渉/受注/失注）",
    "fiscal_quarter": "会計四半期（例: 2026-Q3）",
    "close_date": "完了予定日",
    "is_won": "受注済みかどうか",
    "probability": "受注確度（％）",
}
for col, cmt in comments.items():
    spark.sql(f"ALTER TABLE {CATALOG}.{SCHEMA}.opportunities ALTER COLUMN {col} COMMENT '{cmt}'")

spark.sql(f"COMMENT ON TABLE {CATALOG}.{SCHEMA}.opportunities IS 'Agentforce 連携 PoC 用のダミー営業案件データ'")

# 注: Databricks では日本語のエイリアスはバッククォートで囲む必要がある
display(spark.sql(f"""
  SELECT region, fiscal_quarter, count(*) AS `件数`, sum(amount) AS `合計金額`
  FROM {CATALOG}.{SCHEMA}.opportunities
  GROUP BY region, fiscal_quarter ORDER BY region, fiscal_quarter
"""))
