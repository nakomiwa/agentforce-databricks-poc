/**
 * ② 営業レポートを HTML で取得し、Custom Lightning Type (c__salesReportHtml) として返す。
 * 対応する UC 関数: workspace.sfdc_poc.get_sales_report_html(p_region, p_period)
 */
public with sharing class DatabricksReportService {
    /** c__salesReportHtml のデータ形 */
    public class SalesReport {
        @InvocableVariable(label='タイトル')
        public String title;
        @InvocableVariable(label='HTML')
        public String html;
        @InvocableVariable(label='取得日時')
        public String generatedAt;
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
        @InvocableVariable(label='report' description='HTML レポート（LWC で表示）')
        public SalesReport report;
        @InvocableVariable(label='success')
        public Boolean success;
        @InvocableVariable(label='error_message')
        public String error_message;
    }

    @InvocableMethod(
        label='Get Sales Report HTML'
        description='Databricks から営業レポートを HTML 形式で取得する'
    )
    public static List<Response> getSalesReportHtml(List<Request> requests) {
        List<Response> responses = new List<Response>();

        for (Request req : requests) {
            Response res = new Response();
            String region = String.isBlank(req.region) ? '全社' : req.region;
            String period = String.isBlank(req.period) ? '全期間' : req.period;

            DatabricksSqlClient.Outcome outcome = DatabricksSqlClient.callFunction(
                'get_sales_report_html',
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

            SalesReport report = new SalesReport();
            report.title = region + ' / ' + period + ' 営業レポート';
            report.html = outcome.value;
            report.generatedAt = Datetime.now().format('yyyy/MM/dd HH:mm');

            res.report = report;
            res.success = true;
            responses.add(res);
        }

        return responses;
    }
}
