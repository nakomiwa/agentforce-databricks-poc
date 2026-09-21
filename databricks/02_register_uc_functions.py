# Databricks notebook source
# =============================================================================
# 02_register_uc_functions.py
# ①② の API 本体を Unity Catalog の FUNCTION として登録する
#
#   ① get_sales_summary_spec(region, period) -> 描画スペック JSON
#   ② get_sales_report_spec(region, period)  -> 描画スペック JSON
#
# ③ は UC 関数ではなく Genie ベース（04_deploy_genie_agent.py）。
#
# 旧実装（① の素の JSON、② の HTML、③ の ai_query）はすべて削除済み。
# UC 上の実体を消すのは 05_cleanup.py。
#
# Salesforce からは SQL Statement Execution API 経由で
#   SELECT workspace.sfdc_poc.get_sales_summary_spec(:p_region, :p_period)
# のように呼び出される。
# =============================================================================

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "sfdc_poc"


FQ = f"{CATALOG}.{SCHEMA}"
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")



# COMMAND ----------

# -----------------------------------------------------------------------------
# specJson 方式（claude/if_render_spec.md v1）
#
#   Databricks が「どの部品に・何を・どの順で並べるか」を JSON で指示し、
#   Salesforce は汎用レンダラ LWC でそれを描くだけにする。
#   これにより、表示を変えても Salesforce のリリースが不要になる。
#
#   守る規約は 2 つ。
#     1. 値はすべて「そのまま表示できる文字列」で渡す（整形はここで済ませる）
#     2. Salesforce 側は未知の type を読み飛ばす（前方互換）
#
#   実装メモ：blocks は要素ごとに形が違うので array() では作れない
#   （Spark の配列は同型しか持てない）。ブロック単位で to_json した文字列を
#   連結して組み立てる。ヘッダも to_json で作って末尾の } を差し替えることで、
#   引数由来の文字列のエスケープを to_json に任せている。
# -----------------------------------------------------------------------------

# 共通の絞り込み条件
WHERE_CLAUSE = """
  WHERE (p_region = '全社'   OR o.region = p_region)
    AND (p_period = '全期間' OR o.fiscal_quarter = p_period)
"""

# 状態の意味づけはここ（Databricks 側）で決める。Salesforce は色に変換するだけ。
TONE_EXPR = """
  CASE WHEN o.stage = '受注'     THEN 'success'
       WHEN o.stage = '失注'     THEN 'error'
       WHEN o.stage = '最終交渉' THEN 'warning'
       ELSE 'default' END
"""

# KPI タイル（①②で共用）
KPI_BLOCK = """
  to_json(named_struct(
    'type',    'kpiGrid',
    'columns', 2,
    'items',   array(
      named_struct('label', '合計金額',
                   'value', concat(format_number(coalesce(sum(o.amount), 0), 0), ' 円'),
                   'tone',  'default'),
      named_struct('label', '案件数',
                   'value', concat(cast(count(*) AS STRING), ' 件'),
                   'tone',  'default'),
      named_struct('label', '受注件数',
                   'value', concat(cast(coalesce(sum(CASE WHEN o.is_won THEN 1 ELSE 0 END), 0) AS STRING), ' 件'),
                   'tone',  'default'),
      named_struct('label', '受注率',
                   'value', concat(cast(round(coalesce(avg(CASE WHEN o.is_won THEN 1.0 ELSE 0.0 END), 0.0) * 100, 1) AS STRING), ' %'),
                   'tone',  CASE WHEN coalesce(avg(CASE WHEN o.is_won THEN 1.0 ELSE 0.0 END), 0.0) >= 0.3
                                 THEN 'success' ELSE 'default' END)
    )))
"""


def header_expr(kind):
    """{"version":1,"title":...,"subtitle":...} を作る式。末尾の } は後で差し替える。"""
    return f"""
  to_json(named_struct(
    'version',  1,
    'title',    concat(p_region, ' / ', p_period, ' {kind}'),
    'subtitle', concat('件数 ', cast(count(*) AS STRING), ' 件',
                       ' ／ 生成 ', date_format(current_timestamp(), 'yyyy/MM/dd HH:mm'))))
"""


# ---- ① サマリ：KPI ＋ 明細リスト -------------------------------------------
sql_summary_spec = f"""
CREATE OR REPLACE FUNCTION {FQ}.get_sales_summary_spec(
  p_region STRING COMMENT '対象地域。関東/関西/中部/九州/東北/北海道 のいずれか、または 全社',
  p_period STRING COMMENT '対象四半期。2026-Q1〜2026-Q4 のいずれか、または 全期間'
)
RETURNS STRING
COMMENT '指定した地域・四半期の営業サマリを描画スペック JSON（if_render_spec v1）で返す'
RETURN (
  SELECT concat(
    substring(hdr, 1, length(hdr) - 1),
    ',"blocks":[', kpi, ',', lst, ',', note, ']}}')
  FROM (
    SELECT
      {header_expr('営業サマリ')} AS hdr,
      {KPI_BLOCK}                 AS kpi,
      to_json(named_struct(
        'type',  'list',
        'title', '金額上位10件',
        'items', transform(
          slice(
            array_sort(
              collect_list(named_struct(
                'amount', o.amount,
                'item',   named_struct(
                  'primary',   o.opportunity_name,
                  'secondary', concat(o.account_name, ' / 担当 ', o.owner_name),
                  'value',     concat(format_number(o.amount, 0), ' 円'),
                  'badge',     named_struct('label', o.stage, 'tone', {TONE_EXPR})
                ))),
              (l, r) -> CASE WHEN l.amount > r.amount THEN -1
                             WHEN l.amount < r.amount THEN 1
                             ELSE 0 END
            ), 1, 10),
          x -> x.item))) AS lst,
      to_json(named_struct(
        'type',  'text',
        'value', '金額の降順で上位10件を表示しています。',
        'tone',  'muted')) AS note
    FROM {FQ}.opportunities o
    {WHERE_CLAUSE}
  )
)
"""
spark.sql(sql_summary_spec)
print("① get_sales_summary_spec 登録完了")


# ---- ② レポート：KPI ＋ 3 列テーブル ---------------------------------------
#   チャットパネルの幅では 3 列が限界。案件名・金額・フェーズに絞る。
sql_report_spec = f"""
CREATE OR REPLACE FUNCTION {FQ}.get_sales_report_spec(
  p_region STRING COMMENT '対象地域。関東/関西/中部/九州/東北/北海道 のいずれか、または 全社',
  p_period STRING COMMENT '対象四半期。2026-Q1〜2026-Q4 のいずれか、または 全期間'
)
RETURNS STRING
COMMENT '指定した地域・四半期の営業レポートを描画スペック JSON（if_render_spec v1）で返す'
RETURN (
  SELECT concat(
    substring(hdr, 1, length(hdr) - 1),
    ',"blocks":[', kpi, ',', tbl, ',', note, ']}}')
  FROM (
    SELECT
      {header_expr('営業レポート')} AS hdr,
      {KPI_BLOCK}                   AS kpi,
      to_json(named_struct(
        'type',    'table',
        'title',   '金額上位10件',
        'columns', array(
          named_struct('key', 'name',   'label', '案件名',   'align', 'left'),
          named_struct('key', 'amount', 'label', '金額',     'align', 'right'),
          named_struct('key', 'stage',  'label', 'フェーズ', 'align', 'left')),
        'rows',    transform(
          slice(
            array_sort(
              collect_list(named_struct(
                'amount', o.amount,
                'row',    named_struct(
                  'name',   o.opportunity_name,
                  'amount', concat(format_number(o.amount, 0), ' 円'),
                  'stage',  o.stage,
                  '_tone',  {TONE_EXPR}
                ))),
              (l, r) -> CASE WHEN l.amount > r.amount THEN -1
                             WHEN l.amount < r.amount THEN 1
                             ELSE 0 END
            ), 1, 10),
          x -> x.row))) AS tbl,
      to_json(named_struct(
        'type',  'text',
        'value', '金額の降順で上位10件を表示しています。',
        'tone',  'muted')) AS note
    FROM {FQ}.opportunities o
    {WHERE_CLAUSE}
  )
)
"""
spark.sql(sql_report_spec)
print("② get_sales_report_spec 登録完了")


# COMMAND ----------

# -----------------------------------------------------------------------------
# 登録結果の確認
#   SHOW FUNCTIONS は使わない。サーバーレス（Spark Connect）だと結果スキーマに
#   マップできない列型が含まれ、[UNSUPPORTED_DATATYPE] で落ちる。
#   information_schema なら普通のテーブルなので問題ない。
# -----------------------------------------------------------------------------
rows = spark.sql(f"""
    SELECT routine_name, data_type
    FROM {CATALOG}.information_schema.routines
    WHERE routine_schema = '{SCHEMA}'
    ORDER BY routine_name
""").collect()

print(f"{FQ} に登録されている FUNCTION: {len(rows)} 個")
for r in rows:
    print("  -", r["routine_name"], "->", r["data_type"])

# COMMAND ----------

# bundle run の Output に出す要約。ノートブックの画面を開かずに結果を判断するため。
dbutils.notebook.exit(
    f"FUNCTION {len(rows)} 個: " + ", ".join(r["routine_name"] for r in rows)
)

