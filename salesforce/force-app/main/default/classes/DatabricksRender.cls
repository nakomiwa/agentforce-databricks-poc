/**
 * 描画スペック（if_render_spec v1）の受け口。
 *
 * この 2 項目から恒久的に変えないこと。
 * GenAiFunction の出力型は組織に作成された時点で固定され、再デプロイでは更新されない。
 * 構造を {title, specJson} に固定しておけば、以後どれだけ表示を変えても
 * アクションを作り直す必要がなくなる。表示の中身はすべて specJson の中で表現する。
 */
public with sharing class DatabricksRender {
    public class RenderPayload {
        @InvocableVariable(label='タイトル')
        public String title;

        @InvocableVariable(label='描画スペック JSON')
        public String specJson;
    }

    /** UC 関数を呼んで RenderPayload を組み立てる。①② で共用。 */
    public static RenderPayload fetch(String functionName, String region, String period) {
        DatabricksSqlClient.Outcome outcome = DatabricksSqlClient.callFunction(
            functionName,
            new List<DatabricksSqlClient.Arg>{
                new DatabricksSqlClient.Arg('p_region', region),
                new DatabricksSqlClient.Arg('p_period', period)
            }
        );
        if (!outcome.success) {
            throw new RenderException(outcome.errorMessage);
        }
        RenderPayload payload = new RenderPayload();
        payload.title = region + ' / ' + period;
        payload.specJson = outcome.value;
        return payload;
    }

    public class RenderException extends Exception {}
}
