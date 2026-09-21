# Agentforce × Databricks 連携 PoC

Salesforce の **Agentforce エージェント**から **Databricks** の営業データを呼び出し、
3つの形式で返すサンプル実装です。Databricks Free Edition と Salesforce Developer Edition で動作確認済み。

| # | 利用者の発話例 | 返るもの | 実装 |
|---|---|---|---|
| ① | 「関東の2026-Q3の営業サマリをLWCで見せて」 | 自作 LWC（KPI 4枚＋明細リスト） | UC Function → Apex → Custom Lightning Type |
| ② | 「同じ条件でHTMLレポートを出して」 | HTML の表（リッチテキスト描画） | UC Function → Apex → Custom Lightning Type |
| ③ | 「受注率がいちばん高い地域は？」 | 日本語のテキスト回答＋生成された SQL | Genie スペース → Model Serving → Apex |

---

## アーキテクチャ

```
利用者 ──チャット──> Agentforce エージェント（Agent Script）
                          │  アクション ①②③
                          ▼
                   Apex（指定ログイン情報 Databricks_Sales / OAuth M2M）
                          │
        ┌─────────────────┴──────────────────┐
        │ ①②                                │ ③
        ▼                                     ▼
POST /api/2.0/sql/statements        POST /serving-endpoints/
        │                              sfdc-genie-agent/invocations
        ▼                                     │
Databricks SQL ウェアハウス                    ▼
        │  SELECT workspace.sfdc_poc.<fn>()   Genie スペース（NL→SQL）
        ▼                                     │
Unity Catalog  workspace.sfdc_poc  <──────────┘
  ├ opportunities / accounts   ダミー営業データ
  ├ get_sales_summary_json()   ①
  ├ get_sales_report_html()    ②
  └ genie_sales_agent          ③（UC 登録された ChatAgent モデル）
```

### 設計判断

**Databricks Apps は使わない。Model Serving は使う。** Apps は Free Edition で数が制限され
24時間で自動停止するため採用していません。一方 **カスタムモデルの Model Serving は Free Edition でも動きます**
（当初「使えない」と判断していましたが、実測で覆りました）。

③ に Model Serving を挟んでいるのは、**Genie Conversation API が非同期**だからです。
Apex には `sleep` が無く、callout は 1 トランザクション合計 120 秒・100 回まで。
Apex から直接ポーリングすると制限ギリギリになります。Model Serving はサーバー側タイムアウトが
597 秒あり、**1 回の POST が完了まで待ってくれる**ので、Apex は callout 1 回で済みます。

> Free Edition は provisioned concurrency の枠が非常に小さく、検証用エンドポイントを
> 残したままにすると次のデプロイが `Quota Exceeded` で落ちます。`cleanup` ジョブで片付けます。

**External Service ではなく Apex を使う。** 自作 LWC での表示（Custom Lightning Type）は
**Apex クラスを入出力に使うアクションでしか効きません**。①②が「LWC で表示」「HTML で表示」
という要件だったため、Apex 一択になりました。

**認証は OAuth M2M（クライアントログイン情報フロー）。** v1 は PAT でしたが、v2 で
サービスプリンシパル `sfdc-agentforce-poc` による OAuth M2M に切り替えました。
Salesforce 側は外部ログイン情報の認証プロトコルを「OAuth 2.0」にするだけで、**Apex の変更は不要**です
（指定ログイン情報が `Authorization` ヘッダーを自動生成するため）。

> Salesforce の認証状況「設定済み」は **値が正しいことを保証しません**。
> クライアントログイン情報フローでは保存時に実認証を行わないためです。

---

## ファイル構成

```
databricks/                      ← すべて Asset Bundle のジョブとしてデプロイ／実行する
├── databricks.yml               バンドル定義（ジョブはここに集約）
├── 01_setup_unity_catalog.py    UC にダミー営業データを作る（破壊的。初回のみ）
├── 02_register_uc_functions.py  ①② が使う UC FUNCTION を登録
├── 03_smoke_test.py             疎通確認＋ warehouse_id の取得
├── 04_deploy_genie_agent.py     ③ を UC 登録 → Model Serving へデプロイ
├── 05_cleanup.py                検証用の残骸を削除し、配信を最新 1 本に絞る
└── genie_agent.py               ③ の本体（ChatAgent 実装。★ノートブックではなくモジュール）

salesforce/force-app/main/default/
├── aiAuthoringBundles/DatabricksSalesAgent/   エージェント定義（Agent Script）
├── classes/
│   ├── DatabricksSqlClient.cls       ①② の共通 HTTP クライアント（★環境依存の値あり）
│   ├── DatabricksSalesService.cls    ①
│   ├── DatabricksReportService.cls   ②
│   ├── DatabricksGenieClient.cls     ③ Model Serving 呼び出し
│   └── DatabricksGenieService.cls    ③ Invocable
├── genAiFunctions/                   ①②③ のアクション定義
├── lightningTypes/                   c__salesSummaryV2 / c__salesReportHtml
└── lwc/                              2つのレンダラ

バッチは、それぞれが操作する側のフォルダに置いてある。

```
databricks/databricks_deploy.bat  ジョブを実行（結果は databricks/databricks_deploy.log）
salesforce/deploy.bat             デプロイ（結果は salesforce/deploy.json）
salesforce/retrieve.bat           組織側の実体を取得（salesforce/retrieve.json）
salesforce/destroy.bat            組織から資材を削除（salesforce/destroy.json）
                                  消す対象は salesforce/destructive/ に書く
```
```

---

## セットアップ

### A. Databricks 側

**ノートブックへの貼り付けは不要です。** すべて Asset Bundle のジョブとして流します
（詳細は末尾「Databricks 側のデプロイ」）。

```powershell
:: 初回のみ。ダミーデータを作る（破壊的）
.\databricks_deploy.bat setup_unity_catalog

:: 以降はこれだけ。02 → 04 → 03 が順に流れる
.\databricks_deploy.bat
```

`databricks_deploy.log` の末尾が `TERMINATED SUCCESS` なら成功です。
`smoke_test` の出力に **warehouse_id** が出るので控えてください（B-2 で使います）。

事前に Genie スペースを 1 つ作っておく必要があります。**カタログエクスプローラの
「次で開く: Genie」ではなく、Genie → 新規 から作ること。** 前者で作ったスペースは
ワークスペースのツリーに属さず、`04_deploy_genie_agent.py` が
`Unable to retrieve permissions metadata for dependent genie space ... (tree node ID: )`
で落ちます。作成したスペース ID を `databricks.yml` と `04_deploy_genie_agent.py`、
`genie_agent.py` の `GENIE_SPACE_ID` に設定します。

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

Windows なら `salesforce\deploy.bat` をダブルクリックでも同じことができます。

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

## Databricks 側のデプロイ（Databricks CLI / Asset Bundles）

Salesforce 側の `deploy.bat` と同じ運用で、Databricks 側も 1 操作でデプロイできる。
ノートブックにコードを貼り付ける必要はない。

### 事前準備（1 回だけ）

```powershell
winget install Databricks.DatabricksCLI
databricks auth login --host https://dbc-c4f38c73-28bc.cloud.databricks.com --profile sfdc
```

2 行目でブラウザが開くのでサインインする。以降トークンは自動更新される。

### 使い方

`databricks/databricks_deploy.bat` をダブルクリックする。既定で `deploy_all` が走り、
一連の資材がまとめてデプロイされて、結果が `databricks_deploy.log` に出る。

ジョブを指定する場合:

```powershell
.\databricks_deploy.bat cleanup
```

### 用意してあるジョブ

| ジョブ名 | 内容 |
|---|---|
| `deploy_all` | **既定。** `02 UC 関数 → 04 Genie デプロイ → 03 疎通確認` を順に流す |
| `deploy_genie_agent` | ③ Genie ラッパーを UC に登録して Model Serving へデプロイ |
| `register_uc_functions` | ①② が使う UC 関数を登録し直す |
| `smoke_test` | 疎通確認のみ |
| `cleanup` | 検証用エンドポイント／モデル／旧関数を削除し、配信を最新 1 本に絞る |
| `setup_unity_catalog` | ダミーデータを作り直す（**破壊的。** 初回のみ） |

`deploy_all` に `setup_unity_catalog` を入れていないのは、ダミーデータの作り直しが破壊的だからです。

### 仕組み

`databricks/databricks.yml` がバンドル定義。`bundle deploy` が `databricks/` 配下を
ワークスペースへ同期し、`bundle run` がジョブを実行して出力を返す。

スクリプト先頭の `# Databricks notebook source` は、`.py` をノートブックとして
扱わせるためのマジックヘッダー。ただの行コメントなので、ローカルでの
`python xxx.py` 実行には影響しない。`genie_agent.py` はモジュールとして
import されるため、このヘッダーを付けていない。
