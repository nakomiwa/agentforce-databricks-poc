# Databricks notebook source
# =============================================================================
# 02_register_uc_functions.py
# ①②③ の API 本体を Unity Catalog の FUNCTION として登録する
#
#   ① get_sales_summary_json(region, period) -> JSON 文字列   … LWC 表示用
#   ② get_sales_report_html(region, period)  -> HTML 文字列   … HTML 表示用
#   ③ ask_sales_agent(question)              -> 日本語回答     … カスタムエージェント
#
# Salesforce からは SQL Statement Execution API 経由で
#   SELECT workspace.sfdc_poc.get_sales_summary_json(:p_region, :p_period)
# のように呼び出される。
# =============================================================================

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "sfdc_poc"

# ③ が使う基盤モデルのサービングエンドポイント名。
# Free Edition では使えるモデルが限られる。03_smoke_test.py で
# 利用可能なエンドポイント一覧を出力できるので、通らない場合はここを差し替える。
MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

FQ = f"{CATALOG}.{SCHEMA}"
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# -----------------------------------------------------------------------------
# ① 営業サマリ（JSON）
#   - 引数名は p_ 接頭辞。列名と同名にすると WHERE 句が常に真になるため必須。
#   - region に "全社"、period に "全期間" を渡すと絞り込みなし。
# -----------------------------------------------------------------------------
sql_summary = f"""
CREATE OR REPLACE FUNCTION {FQ}.get_sales_summary_json(
  p_region STRING COMMENT '対象地域。関東/関西/中部/九州/東北/北海道 のいずれか、または 全社',
  p_period STRING COMMENT '対象四半期。2026-Q1〜2026-Q4 のいずれか、または 全期間'
)
RETURNS STRING
COMMENT '指定した地域・四半期の営業サマリ（合計金額・件数・受注率）と上位10件の案件明細を JSON 文字列で返す'
RETURN (
  SELECT to_json(named_struct(
    'title',       concat(p_region, ' / ', p_period, ' 営業サマリ'),
    'region',      p_region,
    'period',      p_period,
    'totalAmount', coalesce(sum(o.amount), 0),
    'dealCount',   count(*),
    'wonCount',    coalesce(sum(CASE WHEN o.is_won THEN 1 ELSE 0 END), 0),
    'winRate',     round(coalesce(avg(CASE WHEN o.is_won THEN 1.0 ELSE 0.0 END), 0.0), 3),
    'rows',        slice(
                     array_sort(
                       collect_list(named_struct(
                         'opportunityName', o.opportunity_name,
                         'accountName',     o.account_name,
                         'ownerName',       o.owner_name,
                         'amount',          o.amount,
                         'stage',           o.stage,
                         'closeDate',       cast(o.close_date AS STRING)
                       )),
                       (l, r) -> CASE WHEN l.amount > r.amount THEN -1
                                      WHEN l.amount < r.amount THEN 1
                                      ELSE 0 END
                     ), 1, 10)
  ))
  FROM {FQ}.opportunities o
  WHERE (p_region = '全社'   OR o.region = p_region)
    AND (p_period = '全期間' OR o.fiscal_quarter = p_period)
)
"""
spark.sql(sql_summary)
print("① get_sales_summary_json 登録完了")

# COMMAND ----------

# -----------------------------------------------------------------------------
# ② 営業レポート（HTML）
#   Salesforce の lightning-formatted-rich-text が許可するタグのみを使う。
#   許可: div/h1-h6/p/table/thead/tbody/tr/th/td/strong/em/span/ul/ol/li/a/img など
#   禁止: script / style タグ / form （style "属性" は使用可）
# -----------------------------------------------------------------------------
sql_html = f"""
CREATE OR REPLACE FUNCTION {FQ}.get_sales_report_html(
  p_region STRING COMMENT '対象地域。関東/関西/中部/九州/東北/北海道 のいずれか、または 全社',
  p_period STRING COMMENT '対象四半期。2026-Q1〜2026-Q4 のいずれか、または 全期間'
)
RETURNS STRING
COMMENT '指定した地域・四半期の営業レポートを HTML フラグメントで返す（Salesforce の rich text で描画可能なタグのみ使用）'
RETURN (
  SELECT concat(
    '<div>',
      '<h3>', p_region, ' / ', p_period, ' 営業レポート</h3>',
      '<p>件数 <strong>', cast(count(*) AS STRING), '</strong> 件',
      ' ／ 合計金額 <strong>', format_number(coalesce(sum(o.amount), 0), 0), ' 円</strong>',
      ' ／ 受注率 <strong>', cast(round(coalesce(avg(CASE WHEN o.is_won THEN 1.0 ELSE 0.0 END), 0.0) * 100, 1) AS STRING), ' %</strong></p>',
      '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px">',
        '<thead style="background-color:#f3f3f3">',
          '<tr><th>案件名</th><th>顧客</th><th>担当</th><th style="text-align:right">金額(円)</th><th>フェーズ</th><th>完了予定</th></tr>',
        '</thead>',
        '<tbody>',
          concat_ws('', transform(
            slice(
              array_sort(
                collect_list(named_struct(
                  'amount', o.amount,
                  'html', concat(
                    '<tr>',
                      '<td>', o.opportunity_name, '</td>',
                      '<td>', o.account_name, '</td>',
                      '<td>', o.owner_name, '</td>',
                      '<td style="text-align:right">', format_number(o.amount, 0), '</td>',
                      '<td>', o.stage, '</td>',
                      '<td>', cast(o.close_date AS STRING), '</td>',
                    '</tr>')
                )),
                (l, r) -> CASE WHEN l.amount > r.amount THEN -1
                               WHEN l.amount < r.amount THEN 1
                               ELSE 0 END
              ), 1, 10),
            x -> x.html)),
        '</tbody>',
      '</table>',
      '<p><em>上位10件を金額降順で表示しています。</em></p>',
    '</div>')
  FROM {FQ}.opportunities o
  WHERE (p_region = '全社'   OR o.region = p_region)
    AND (p_period = '全期間' OR o.fiscal_quarter = p_period)
)
"""
spark.sql(sql_html)
print("② get_sales_report_html 登録完了")

# COMMAND ----------

# -----------------------------------------------------------------------------
# ③-1 エージェントに渡すコンテキスト（地域×四半期の集計テキスト）
# -----------------------------------------------------------------------------
sql_ctx = f"""
CREATE OR REPLACE FUNCTION {FQ}.sales_context()
RETURNS STRING
COMMENT '地域×四半期の営業集計をテキスト化して返す（ask_sales_agent が内部で使用）'
RETURN (
  SELECT concat_ws('\\n', collect_list(line))
  FROM (
    SELECT concat(
             region, ' | ', fiscal_quarter,
             ' | 件数 ', cast(count(*) AS STRING),
             ' | 合計 ', format_number(sum(amount), 0), '円',
             ' | 受注 ', cast(sum(CASE WHEN is_won THEN 1 ELSE 0 END) AS STRING), '件',
             ' | 受注率 ', cast(round(avg(CASE WHEN is_won THEN 1.0 ELSE 0.0 END) * 100, 1) AS STRING), '%'
           ) AS line
    FROM {FQ}.opportunities
    GROUP BY region, fiscal_quarter
    ORDER BY region, fiscal_quarter
  )
)
"""
spark.sql(sql_ctx)
print("③-1 sales_context 登録完了")

# COMMAND ----------

# -----------------------------------------------------------------------------
# ③-2 カスタムエージェント本体
#   ai_query() で基盤モデルを呼ぶ。failOnError => false なので
#   モデル側エラー時も STRUCT(result, errorMessage) が返り、SQL は落ちない。
# -----------------------------------------------------------------------------
sql_agent = f"""
CREATE OR REPLACE FUNCTION {FQ}.ask_sales_agent(
  p_question STRING COMMENT '営業データに関する自然文の質問'
)
RETURNS STRING
COMMENT '営業データを踏まえて質問に日本語で回答するカスタムエージェント'
RETURN (
  SELECT coalesce(
    ai_query(
      '{MODEL_ENDPOINT}',
      concat(
        'あなたは日本企業の営業データ分析アシスタントです。',
        '以下の集計データだけを根拠にして、必ず日本語で、300文字以内で簡潔に回答してください。',
        'データから読み取れないことは「データからは判断できません」と答えてください。\\n\\n',
        '# 営業データ（地域 | 四半期 | 件数 | 合計金額 | 受注件数 | 受注率）\\n',
        {FQ}.sales_context(), '\\n\\n',
        '# 質問\\n', p_question, '\\n\\n',
        '# 回答（日本語）\\n'
      ),
      modelParameters => named_struct('max_tokens', 700, 'temperature', 0.2),
      failOnError => false
    ).result,
    'モデルの呼び出しに失敗しました。エンドポイント名を確認してください。'
  )
)
"""
spark.sql(sql_agent)
print("③-2 ask_sales_agent 登録完了")

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

