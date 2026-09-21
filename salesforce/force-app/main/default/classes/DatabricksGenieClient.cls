/**
 * ③ Databricks の Genie エージェント（Model Serving エンドポイント）を呼ぶクライアント。
 *
 * エンドポイント:
 *   POST callout:Databricks_Sales/serving-endpoints/sfdc-genie-agent/invocations
 *   body : {"messages":[{"role":"user","content":"..."}],
 *           "custom_inputs":{"conversation_id":"..."}}   ← 継続時のみ
 *   resp : {"messages":[{"role":"assistant","content":"..."}],
 *           "custom_outputs":{"conversation_id":"...","sql":"...","sql_description":"..."}}
 *
 * 【設計メモ】
 * Genie Conversation API は非同期（ポーリング必須）で、Apex には sleep が無く
 * callout も 100 回 / 合計 120 秒という制限がある。そのため Databricks 側の
 * Model Serving に同期ラッパーを置き、Apex は callout 1 回で待つ構成にした。
 * 実測: ウォーム 19.5 秒 / コールド 47.8 秒。Apex の上限 120 秒に収まる。
 *
 * 認証は指定ログイン情報 Databricks_Sales（OAuth 2.0 M2M）が自動付与する。
 * ①②③ でホストが同じなので、追加の認証設定は不要。
 */
public with sharing class DatabricksGenieClient {
    private static final String NAMED_CREDENTIAL = 'callout:Databricks_Sales';
    /** Databricks 側のサービングエンドポイント名 */
    public static final String ENDPOINT_NAME = 'sfdc-genie-agent';
    /** Apex の callout タイムアウト上限（これ以上は設定できない） */
    private static final Integer TIMEOUT_MS = 120000;

    public class Outcome {
        public Boolean success = false;
        public String answer;
        public String sqlText;
        public String sqlDescription;
        public String conversationId;
        public String errorMessage;
    }

    /**
     * @param question       自然文の質問
     * @param conversationId 直前の会話を継続する場合に指定（無ければ新規会話）
     */
    public static Outcome ask(String question, String conversationId) {
        Outcome outcome = new Outcome();

        if (String.isBlank(question)) {
            outcome.errorMessage = '質問が空です。';
            return outcome;
        }

        Map<String, Object> body = new Map<String, Object>{
            'messages' => new List<Object>{
                new Map<String, Object>{ 'role' => 'user', 'content' => question }
            }
        };
        if (String.isNotBlank(conversationId)) {
            body.put(
                'custom_inputs',
                new Map<String, Object>{ 'conversation_id' => conversationId }
            );
        }

        HttpRequest req = new HttpRequest();
        req.setEndpoint(
            NAMED_CREDENTIAL + '/serving-endpoints/' + ENDPOINT_NAME + '/invocations'
        );
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(TIMEOUT_MS);
        req.setBody(JSON.serialize(body));

        HttpResponse res;
        try {
            res = new Http().send(req);
        } catch (Exception e) {
            outcome.errorMessage =
                'Databricks への接続に失敗しました: ' + e.getMessage() +
                '（エンドポイントが停止していると起動に時間がかかります。もう一度お試しください）';
            return outcome;
        }

        if (res.getStatusCode() != 200) {
            outcome.errorMessage =
                'Databricks API エラー (HTTP ' + res.getStatusCode() + '): ' +
                truncate(res.getBody(), 500);
            return outcome;
        }

        return parse(res.getBody(), outcome);
    }

    private static Outcome parse(String responseBody, Outcome outcome) {
        Map<String, Object> parsed;
        try {
            parsed = (Map<String, Object>) JSON.deserializeUntyped(responseBody);
        } catch (Exception e) {
            outcome.errorMessage = 'Databricks の応答を解析できませんでした。';
            return outcome;
        }

        List<Object> messages = (List<Object>) parsed.get('messages');
        if (messages == null || messages.isEmpty()) {
            outcome.errorMessage = '回答が空でした。';
            return outcome;
        }

        // assistant の最後の発話を採用する
        String answer;
        for (Object o : messages) {
            Map<String, Object> m = (Map<String, Object>) o;
            if (m.get('content') != null) {
                answer = String.valueOf(m.get('content'));
            }
        }
        if (String.isBlank(answer)) {
            outcome.errorMessage = '回答が空でした。';
            return outcome;
        }

        outcome.answer = answer;
        outcome.success = true;

        Map<String, Object> custom = (Map<String, Object>) parsed.get('custom_outputs');
        if (custom != null) {
            outcome.sqlText = str(custom.get('sql'));
            outcome.sqlDescription = str(custom.get('sql_description'));
            outcome.conversationId = str(custom.get('conversation_id'));
        }

        return outcome;
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private static String truncate(String s, Integer len) {
        if (s == null) {
            return '';
        }
        return s.length() <= len ? s : s.substring(0, len);
    }
}
