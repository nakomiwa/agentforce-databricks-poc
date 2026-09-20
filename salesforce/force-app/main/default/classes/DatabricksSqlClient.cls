/**
 * Databricks SQL Statement Execution API の共通クライアント。
 *
 * Unity Catalog に登録した FUNCTION を
 *   SELECT <catalog>.<schema>.<function>(:arg1, :arg2) AS v
 * の形で呼び出し、1 行 1 列の文字列結果を返す。
 * 引数は名前付きパラメータとして送るため、SQL インジェクションの懸念はない。
 */
public with sharing class DatabricksSqlClient {
    // ===== 設定（環境に合わせて書き換える） ============================
    /** 03_smoke_test.py が出力した SQL ウェアハウス ID */
    public static final String WAREHOUSE_ID = 'e97a8ff7fddc4165';
    public static final String CATALOG_NAME = 'workspace';
    public static final String SCHEMA_NAME = 'sfdc_poc';
    /** 指定した名前の Named Credential を事前に作成しておくこと */
    private static final String NAMED_CREDENTIAL = 'callout:Databricks_Sales';
    // ==================================================================

    private static final Integer TIMEOUT_MS = 60000;

    /** 関数の引数（順序を保持するため List で渡す） */
    public class Arg {
        public String name;
        public String value;
        public Arg(String name, String value) {
            this.name = name;
            this.value = value;
        }
    }

    /** 呼び出し結果 */
    public class Outcome {
        public Boolean success = false;
        public String value;
        public String errorMessage;
    }

    /**
     * UC 関数を呼び出す。ウェアハウスのコールドスタートでタイムアウトした場合のみ 1 回再試行する。
     */
    public static Outcome callFunction(String functionName, List<Arg> args) {
        Outcome result = invoke(functionName, args);
        if (!result.success && result.errorMessage == 'WAREHOUSE_TIMEOUT') {
            result = invoke(functionName, args);
            if (!result.success && result.errorMessage == 'WAREHOUSE_TIMEOUT') {
                result.errorMessage = 'Databricks のウェアハウス起動に時間がかかっています。少し待ってからもう一度お試しください。';
            }
        }
        return result;
    }

    private static Outcome invoke(String functionName, List<Arg> args) {
        Outcome outcome = new Outcome();

        List<String> argRefs = new List<String>();
        List<Map<String, Object>> params = new List<Map<String, Object>>();
        if (args != null) {
            for (Arg a : args) {
                argRefs.add(':' + a.name);
                params.add(
                    new Map<String, Object>{
                        'name' => a.name,
                        'value' => a.value,
                        'type' => 'STRING'
                    }
                );
            }
        }

        String statement =
            'SELECT ' + CATALOG_NAME + '.' + SCHEMA_NAME + '.' + functionName +
            '(' + String.join(argRefs, ', ') + ') AS v';

        Map<String, Object> body = new Map<String, Object>{
            'warehouse_id' => WAREHOUSE_ID,
            'statement' => statement,
            'parameters' => params,
            'wait_timeout' => '50s',
            'on_wait_timeout' => 'CANCEL',
            'format' => 'JSON_ARRAY',
            'disposition' => 'INLINE'
        };

        HttpRequest req = new HttpRequest();
        req.setEndpoint(NAMED_CREDENTIAL + '/api/2.0/sql/statements');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(TIMEOUT_MS);
        req.setBody(JSON.serialize(body));

        HttpResponse res;
        try {
            res = new Http().send(req);
        } catch (Exception e) {
            outcome.errorMessage = 'Databricks への接続に失敗しました: ' + e.getMessage();
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

        Map<String, Object> status = (Map<String, Object>) parsed.get('status');
        String state = status == null ? null : (String) status.get('state');

        if (state == 'PENDING' || state == 'RUNNING' || state == 'CANCELED') {
            outcome.errorMessage = 'WAREHOUSE_TIMEOUT';
            return outcome;
        }

        if (state != 'SUCCEEDED') {
            String message = 'SQL の実行に失敗しました (' + state + ')';
            if (status != null && status.get('error') != null) {
                Map<String, Object> err = (Map<String, Object>) status.get('error');
                message += ': ' + String.valueOf(err.get('message'));
            }
            outcome.errorMessage = truncate(message, 500);
            return outcome;
        }

        Map<String, Object> result = (Map<String, Object>) parsed.get('result');
        if (result == null) {
            outcome.errorMessage = '該当するデータがありませんでした。';
            return outcome;
        }
        List<Object> dataArray = (List<Object>) result.get('data_array');
        if (dataArray == null || dataArray.isEmpty()) {
            outcome.errorMessage = '該当するデータがありませんでした。';
            return outcome;
        }

        List<Object> firstRow = (List<Object>) dataArray[0];
        if (firstRow == null || firstRow.isEmpty() || firstRow[0] == null) {
            outcome.errorMessage = '該当するデータがありませんでした。';
            return outcome;
        }

        outcome.success = true;
        outcome.value = String.valueOf(firstRow[0]);
        return outcome;
    }

    private static String truncate(String s, Integer len) {
        if (s == null) {
            return '';
        }
        return s.length() <= len ? s : s.substring(0, len);
    }

    /** 金額を "1,234,567 円" 形式にする */
    public static String formatYen(Decimal value) {
        if (value == null) {
            return '-';
        }
        return value.setScale(0).format() + ' 円';
    }
}
