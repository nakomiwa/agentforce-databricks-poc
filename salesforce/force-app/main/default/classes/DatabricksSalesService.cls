/**
 * ① 営業サマリを取得し、Custom Lightning Type (c__salesSummary) として返す。
 * 対応する UC 関数: workspace.sfdc_poc.get_sales_summary_json(p_region, p_period)
 *
 * 【重要】Custom Lightning Type はネストしたカスタムクラスのリストを扱えないため、
 * SalesSummary は文字列項目のみで構成し、明細は rowsJson（JSON 文字列）で渡す。
 * LWC 側で JSON.parse して表を描画する。
 */
public with sharing class DatabricksSalesService {
    /** c__salesSummary のデータ形。lightningTypes/salesSummary/schema.json から参照される */
    public class SalesSummary {
        @InvocableVariable(label='タイトル')
        public String title;
        @InvocableVariable(label='サマリ本文')
        public String summaryText;
        @InvocableVariable(label='明細JSON')
        public String rowsJson;
    }

    public class Request {
        @InvocableVariable(
            label='region'
            description='対象地域。関東/関西/中部/九州/東北/北海道 のいずれか、または 全社'
            required=true
        )
        public String region;
        @InvocableVariable(
            label='period'
            description='対象四半期。2026-Q1〜2026-Q4 のいずれか、または 全期間'
            required=true
        )
        public String period;
    }

    public class Response {
        @InvocableVariable(label='summary' description='営業サマリ（LWC で表示）')
        public SalesSummary summary;
        @InvocableVariable(label='success' description='取得に成功したか')
        public Boolean success;
        @InvocableVariable(label='error_message' description='失敗時のメッセージ')
        public String error_message;
    }

    @InvocableMethod(
        label='Get Sales Summary'
        description='Databricks の Unity Catalog から営業サマリを取得する'
    )
    public static List<Response> getSalesSummary(List<Request> requests) {
        List<Response> responses = new List<Response>();

        for (Request req : requests) {
            Response res = new Response();
            String region = String.isBlank(req.region) ? '全社' : req.region;
            String period = String.isBlank(req.period) ? '全期間' : req.period;

            DatabricksSqlClient.Outcome outcome = DatabricksSqlClient.callFunction(
                'get_sales_summary_json',
                new List<DatabricksSqlClient.Arg>{
                    new DatabricksSqlClient.Arg('p_region', region),
                    new DatabricksSqlClient.Arg('p_period', period)
                }
            );

            if (!outcome.success) {
                res.success = false;
                res.error_message = outcome.errorMessage;
                responses.add(res);
                continue;
            }

            try {
                res.summary = build(outcome.value);
                res.success = true;
            } catch (Exception e) {
                res.success = false;
                res.error_message =
                    'Databricks の応答を解析できませんでした: ' + e.getMessage();
            }
            responses.add(res);
        }

        return responses;
    }

    /** Databricks が返した JSON を SalesSummary（文字列のみ）に詰め替える */
    private static SalesSummary build(String rawJson) {
        Map<String, Object> m = (Map<String, Object>) JSON.deserializeUntyped(rawJson);

        SalesSummary s = new SalesSummary();
        s.title = str(m.get('title'));

        Decimal winRate = dec(m.get('winRate'));
        String winRateText = winRate == null
            ? '-'
            : (winRate * 100).setScale(1) + ' %';
        String totalAmountText = DatabricksSqlClient.formatYen(dec(m.get('totalAmount')));

        // 会話文としてのフォールバック表示
        s.summaryText =
            '件数 ' + str(m.get('dealCount')) + ' 件 ／ 合計金額 ' + totalAmountText +
            ' ／ 受注率 ' + winRateText;

        // 明細行
        List<Object> rows = (List<Object>) m.get('rows');
        List<Map<String, Object>> outRows = new List<Map<String, Object>>();
        if (rows != null) {
            for (Object o : rows) {
                Map<String, Object> r = (Map<String, Object>) o;
                outRows.add(
                    new Map<String, Object>{
                        'opportunityName' => str(r.get('opportunityName')),
                        'accountName' => str(r.get('accountName')),
                        'ownerName' => str(r.get('ownerName')),
                        'amountText' => DatabricksSqlClient.formatYen(dec(r.get('amount'))),
                        'stage' => str(r.get('stage')),
                        'closeDate' => str(r.get('closeDate'))
                    }
                );
            }
        }

        // KPI と明細をまとめて 1 本の JSON 文字列に入れる。
        // Lightning Type の項目構成（文字列3項目）を変えないための措置。
        // 構成を変えるとアクション(GenAiFunction)を作り直す必要が生じる。
        s.rowsJson = JSON.serialize(
            new Map<String, Object>{
                'kpi' => new Map<String, Object>{
                    'region' => str(m.get('region')),
                    'period' => str(m.get('period')),
                    'totalAmountText' => totalAmountText,
                    'dealCountText' => str(m.get('dealCount')) + ' 件',
                    'wonCountText' => str(m.get('wonCount')) + ' 件',
                    'winRateText' => winRateText
                },
                'rows' => outRows
            }
        );

        return s;
    }

    private static String str(Object o) {
        return o == null ? '' : String.valueOf(o);
    }

    private static Decimal dec(Object o) {
        return o == null ? null : Decimal.valueOf(String.valueOf(o));
    }
}
