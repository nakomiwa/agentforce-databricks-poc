/**
 * ③-B Genie 版。Agentforce のアクションから呼ばれる Invocable。
 *
 * 従来の ③（DatabricksAgentService / ai_query 方式）は、事前集計したテキストを
 * LLM に要約させるだけで、集計の外側には答えられなかった。
 * こちらは Genie が実テーブルに対して NL→SQL を実行するので、任意の切り口に答えられ、
 * 生成した SQL も返せる。
 */
public with sharing class DatabricksGenieService {
    public class Request {
        @InvocableVariable(
            label='question'
            description='営業データに関する自然文の質問。日本語でそのまま渡す。'
            required=true
        )
        public String question;

        @InvocableVariable(
            label='conversation_id'
            description='直前の回答に含まれる会話ID。追質問のときだけ渡す。新規の質問なら空。'
        )
        public String conversation_id;
    }

    public class Response {
        @InvocableVariable(label='answer' description='Genie からの日本語回答')
        public String answer;

        @InvocableVariable(label='generated_sql' description='Genie が生成して実行した SQL')
        public String generated_sql;

        @InvocableVariable(
            label='conversation_id'
            description='次の追質問でそのまま渡すと文脈が維持される会話ID'
        )
        public String conversation_id;

        @InvocableVariable(label='success' description='取得に成功したか')
        public Boolean success;

        @InvocableVariable(label='error_message' description='失敗時のメッセージ')
        public String error_message;
    }

    @InvocableMethod(
        label='Ask Sales Genie'
        description='Databricks の Genie に営業データを質問し、日本語の回答と生成SQLを得る'
    )
    public static List<Response> ask(List<Request> requests) {
        List<Response> responses = new List<Response>();

        for (Request req : requests) {
            Response res = new Response();

            DatabricksGenieClient.Outcome outcome =
                DatabricksGenieClient.ask(req.question, req.conversation_id);

            if (outcome.success) {
                res.answer = outcome.answer;
                res.generated_sql = outcome.sqlText;
                res.conversation_id = outcome.conversationId;
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
