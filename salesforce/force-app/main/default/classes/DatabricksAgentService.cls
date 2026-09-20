/**
 * ③ Databricks 側のカスタムエージェントに質問し、日本語の回答テキストを返す。
 * 対応する UC 関数: workspace.sfdc_poc.ask_sales_agent(p_question)
 */
public with sharing class DatabricksAgentService {
    public class Request {
        @InvocableVariable(
            label='question'
            description='営業データに関する自然文の質問'
            required=true
        )
        public String question;
    }

    public class Response {
        @InvocableVariable(label='answer' description='エージェントからの日本語回答')
        public String answer;
        @InvocableVariable(label='success')
        public Boolean success;
        @InvocableVariable(label='error_message')
        public String error_message;
    }

    @InvocableMethod(
        label='Ask Databricks Sales Agent'
        description='Databricks の営業分析エージェントに質問し、日本語で回答を得る'
    )
    public static List<Response> ask(List<Request> requests) {
        List<Response> responses = new List<Response>();

        for (Request req : requests) {
            Response res = new Response();

            DatabricksSqlClient.Outcome outcome = DatabricksSqlClient.callFunction(
                'ask_sales_agent',
                new List<DatabricksSqlClient.Arg>{
                    new DatabricksSqlClient.Arg('p_question', req.question)
                }
            );

            if (outcome.success) {
                res.answer = outcome.value;
                res.success = true;
            } else {
                res.success = false;
                res.error_message = outcome.errorMessage;
            }
            responses.add(res);
        }

        return responses;
    }
}
