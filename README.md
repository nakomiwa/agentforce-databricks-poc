# Agentforce × Databricks 連携 PoC

Salesforce の **Agentforce エージェント**から **Databricks** の営業データを呼び出し、
3つの形式で返すサンプル実装です。Databricks Free Edition と Salesforce Developer Edition で動作確認済み。

| # | 利用者の発話例 | 返るもの | 実装 |
|---|---|---|---|
| ① | 「関東の2026-Q3の営業サマリをLWCで見せて」 | 自作 LWC（KPI 4枚＋明細リスト） | UC Function → Apex → Custom Lightning Type |
| ② | 「同じ条件でHTMLレポートを出して」 | HTML の表（リッチテキスト描画） | UC Function → Apex → Custom Lightning Type |
| ③ | 「受注率がいちばん高い地域は？」 | 日本語のテキスト回答 | UC Function 内の `ai_query()` → Apex |

---

## アーキテクチャ

```
利用者 ──チャット──> Agentforce エージェント（Agent Script）
                          │  アクション ①②③
                          ▼
                   Apex（Named Credential 経由）
                          │  POST /api/2.0/sql/statements
                          ▼
                  Databricks SQL ウェアハウス
                          │  SELECT workspace.sfdc_poc.<function>(:args)
                          ▼
                Unity Catalog  workspace.sfdc_poc
                  ├ opportunities / accounts   ダミー営業データ
                  ├ get_sales_summary_json()   ①
                  ├ get_sales_report_html()    ②
                  ├ sales_context()
                  └ ask_sales_agent()          ③（ai_query で基盤モデルを呼ぶ）
```

### 設計判断

**Databricks Apps と Model Serving は使わない。** Free Edition ではアプリ数が 1〜3 に制限され
24時間で自動停止し、カスタムモデルのサービングエンドポイント作成も事実上できません。
代わりに ①②③ をすべて **Unity Catalog の FUNCTION** として登録し、
Salesforce からは **SQL Statement Execution API** を直接呼びます。Databricks 側のデプロイ作業はゼロです。

**External Service ではなく Apex を使う。** 自作 LWC での表示（Custom Lightning Type）は
**Apex クラスを入出力に使うアクションでしか効きません**。①②が「LWC で表示」「HTML で表示」
という要件だったため、Apex 一択になりました。

**認証は PAT。** Free Edition はアカウントコンソール・アカウントレベル API・SCIM が使えず、
サービスプリンシパルの OAuth シークレット発行が確実に通らないためです。

---

## ファイル構成

```
databricks/
├── 01_setup_unity_catalog.py    UC にダミー営業データを作る（日本語・円・国内地域）
├── 02_register_uc_functions.py  ①②③ を UC FUNCTION として登録
├── 03_smoke_test.py             動作確認＋ warehouse_id / モデル一覧の取得
├── api_check.py                 疎通確認（Python・OS 問わず）
├── curl_check.ps1               疎通確認（Windows PowerShell）
└── curl_check.sh                疎通確認（macOS / Linux bash）

salesforce/force-app/main/default/
├── aiAuthoringBundles/DatabricksSalesAgent/   エージェント定義（Agent Script）
├── classes/
│   ├── DatabricksSqlClient.cls       共通 HTTP クライアント（★環境依存の値あり）
│   ├── DatabricksSalesService.cls    ①
│   ├── DatabricksReportService.cls   ②
│   └── DatabricksAgentService.cls    ③
├── genAiFunctions/                   ①②③ のアクション定義
├── lightningTypes/                   c__salesSummaryV2 / c__salesReportHtml
└── lwc/                              2つのレンダラ

deploy.bat      ダブルクリックでデプロイ（結果は deploy.json）
retrieve.bat    組織側の実体を取得（結果は retrieve.json）
```

---

## セットアップ

### A. Databricks 側

1. `databricks/01_setup_unity_catalog.py` をワークスペースにインポートし、サーバーレスノートブックとして実行
   → `workspace.sfdc_poc` に `accounts` 41件 / `opportunities` 180件
2. `databricks/02_register_uc_functions.py` を実行 → FUNCTION 4つを登録
3. `databricks/03_smoke_test.py` を実行 → ①②③の動作確認、**warehouse_id** を控える
4. Settings → Developer → Access tokens で **PAT** を発行
5. **手元の PC から** 疎通確認（Salesforce と同じ「外部クライアント」の立場で確認するため）

```powershell
$env:DATABRICKS_HOST  = "https://dbc-xxxxxxxx-xxxx.cloud.databricks.com"
$env:DATABRICKS_TOKEN = "dapi..."
$env:WAREHOUSE_ID     = "手順3で控えたID"
python databricks/api_check.py
```

「3 / 3 成功」になるまで Salesforce 側に進まないでください。

### B. Salesforce 側

**B-1. 認証設定（設定画面で手作業）**

PAT はシークレットなのでメタデータでデプロイできません。

*外部ログイン情報*（設定 → 指定ログイン情報 → 外部ログイン情報タブ）

| 項目 | 値 |
|---|---|
| 名前 | `Databricks_PAT` |
| 認証プロトコル | カスタム |
| プリンシパル | パラメーター名 `DatabricksPrincipal` / ID種別 指定ユーザー |
| 認証パラメーター | 名前 **`Token`** / 値 = PAT |

> **名前は必ず `Token`。** Databricks 側でトークンに付けたコメント名を入れると、
> 差し込み項目が空文字に解決され HTTP 403 になります。

*指定ログイン情報*

| 項目 | 値 |
|---|---|
| 名前 | `Databricks_Sales` |
| URL | `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com` |
| コールアウトに対応 | ON |
| 外部ログイン情報 | `Databricks_PAT` |
| **HTTP ヘッダーの数式を許可** | **ON**（必須） |

*権限セット* `Databricks Access` を作り、「外部ログイン情報プリンシパルのアクセス」に
`Databricks_PAT - DatabricksPrincipal` を追加して自分に割り当てます。

**B-2. Apex の環境依存値を書き換える**

`classes/DatabricksSqlClient.cls` の冒頭:

```apex
public static final String WAREHOUSE_ID = 'xxxxxxxxxxxxxxxx';  // 手順A-3の値
public static final String CATALOG_NAME = 'workspace';
public static final String SCHEMA_NAME  = 'sfdc_poc';
```

**B-3. デプロイ**

```bash
cd salesforce
sf org login web -a agentforce-poc
sf project deploy start -o agentforce-poc -d force-app/main/default
```

Windows なら `deploy.bat` をダブルクリックでも同じことができます。

**B-4. Apex 単体での疎通確認**（Agentforce を触る前に必ず実施）

開発者コンソール → Debug → Open Execute Anonymous Window:

```apex
DatabricksSalesService.Request r = new DatabricksSalesService.Request();
r.region = '関東';
r.period = '2026-Q3';
DatabricksSalesService.Response res =
    DatabricksSalesService.getSalesSummary(new List<DatabricksSalesService.Request>{ r })[0];
System.debug('success=' + res.success + ' err=' + res.error_message);
```

**B-5. 会話テスト**

設定 → Agentforce スタジオ → Agentforce エージェント → `Databricks 営業エージェント` → Preview

---

## ハマりどころ（実際に踏んだもの）

### 1. GenAiFunction の出力型は再デプロイで更新されない

**アクション（GenAiFunction）は一度組織に作成されると、出力の型定義が再デプロイでは変わりません。**

最初のデプロイ時に Apex の CLT クラスが不正な形（ネストしたカスタムクラスのリストを含む）だと、
その時点でアクションが不正なスキーマのまま固定され、以降 Apex や Lightning Type をいくら直しても
描画時に「表示中に問題が発生しました」が出続けます。

→ **CLT クラスの構造を変えたら、アクションを別名で作り直す。**

### 2. Custom Lightning Type に渡すクラスは文字列のスカラー項目のみ

`List<CustomClass>` のようなネストした構造は扱えません。
本実装では KPI と明細を **JSON 文字列**（`rowsJson`）に詰めて渡し、LWC 側で `JSON.parse` しています。
この形なら、見た目を変えたくなっても LWC の差し替えだけで済みます。

### 3. 内部エラーは「シミュレーターをリセット」で見える

「表示中に問題が発生しました」は定型文で、ブラウザのコンソールにも詳細は出ません。
Agent Builder のプレビューで **「シミュレーターをリセット」** を押すと、
`complex_data_type_name の無効な値が原因で、アクションの検証に失敗しました` のような
本当のエラーが表示されます。

### 4. externalCredentials をリポジトリに置かない

`sf project retrieve` で取得した ExternalCredential のメタデータには**シークレットが含まれません**。
それをデプロイし返すと、設定済みの認証パラメータが壊れます。

### 5. SQL のエイリアスに日本語を使うならバッククォート

`count(*) AS 件数` は `[INVALID_IDENTIFIER]` になります。`` AS `件数` `` と囲みます。

### 6. Apex のガバナ制限

外部呼び出しは1トランザクション合計 120 秒まで。本実装では `wait_timeout` を 50 秒にし、
ウェアハウスのコールドスタート時のみ1回だけ再試行する設計にしています。

---

## 注意

- `DatabricksSqlClient.cls` の `WAREHOUSE_ID` と、指定ログイン情報の URL は環境依存です。
  秘密情報ではありませんが、自分の環境の値に置き換えてください。
- PAT はコードにもメタデータにも含まれません。設定画面から入力します。
- ダミーデータは自動生成で、実在の企業・人物とは関係ありません。
