/**
 * ① 営業サマリを描画スペック JSON で取得する（specJson 方式）。
 * 対応する UC 関数: workspace.sfdc_poc.get_sales_summary_spec(p_region, p_period)
 */
public with sharing class DatabricksSummarySpecService {
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
        @InvocableVariable(label='card' description='描画スペック（LWC で表示）')
        public DatabricksRender.RenderPayload card;
        @InvocableVariable(label='success')
        public Boolean success;
        @InvocableVariable(label='error_message')
        public String error_message;
    }

    @InvocableMethod(
        label='Get Sales Summary Spec'
        description='Databricks から営業サマリを描画スペックで取得する'
    )
    public static List<Response> getSalesSummarySpec(List<Request> requests) {
        List<Response> responses = new List<Response>();
        for (Request req : requests) {
            Response res = new Response();
            String region = String.isBlank(req.region) ? '全社' : req.region;
            String period = String.isBlank(req.period) ? '全期間' : req.period;
            try {
                res.card = DatabricksRender.fetch('get_sales_summary_spec', region, period);
                res.success = true;
            } catch (Exception e) {
                res.success = false;
                res.error_message = e.getMessage();
            }
            responses.add(res);
        }
        return responses;
    }
}
