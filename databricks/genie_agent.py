"""Genie Space を ChatAgent インターフェースでラップするエージェント。

MLflow の "models from code" 方式で読み込まれる想定。
Model Serving エンドポイントとしてデプロイされ、Salesforce の Apex から
callout 1 回・同期で呼ばれる。

Salesforce から見たインターフェース:
    POST {host}/serving-endpoints/sfdc-genie-agent/invocations
    body : {"messages":[{"role":"user","content":"関東の受注状況は？"}]}
    resp : {"messages":[{"role":"assistant","content":"..."}],
            "custom_outputs":{"conversation_id":"...","sql":"SELECT ..."}}
"""

import uuid

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse

# 作成済みの Genie Space
GENIE_SPACE_ID = "01f1b4cc0d861bdcb5b66159bad6c4f5"

# Genie は質問が日本語なら日本語で返すが、書式を揃えるため明示する
JA_HINT = "（日本語で、金額は3桁区切りで回答してください）"

# クエリ結果を本文に添える行数
MAX_PREVIEW_ROWS = 10


class GenieChatAgent(ChatAgent):
    def __init__(self):
        self._w = WorkspaceClient()

    @staticmethod
    def _latest_user_text(messages):
        for m in reversed(messages):
            if m.role == "user":
                return m.content or ""
        return ""

    @staticmethod
    def _reply(text, custom_outputs=None):
        return ChatAgentResponse(
            messages=[
                ChatAgentMessage(role="assistant", content=text, id=str(uuid.uuid4()))
            ],
            custom_outputs=custom_outputs or {},
        )

    def _rows_preview(self, conversation_id, message_id, attachment_id):
        """生成された SQL の実行結果を先頭数行だけテキスト化する。"""
        qr = self._w.genie.get_message_attachment_query_result(
            space_id=GENIE_SPACE_ID,
            conversation_id=conversation_id,
            message_id=message_id,
            attachment_id=attachment_id,
        )
        sr = qr.statement_response
        cols = [c.name for c in sr.manifest.schema.columns]
        rows = (sr.result.data_array or [])[:MAX_PREVIEW_ROWS]
        lines = [" | ".join(cols)]
        lines += [" | ".join("" if v is None else str(v) for v in r) for r in rows]
        return "\n".join(lines)

    @mlflow.trace(name="genie_predict")
    def predict(self, messages, context=None, custom_inputs=None) -> ChatAgentResponse:
        question = self._latest_user_text(messages).strip()
        if not question:
            return self._reply("質問が空でした。聞きたい内容を入力してください。")

        prompt = question + "\n" + JA_HINT
        conversation_id = (custom_inputs or {}).get("conversation_id")

        try:
            if conversation_id:
                msg = self._w.genie.create_message_and_wait(
                    space_id=GENIE_SPACE_ID,
                    conversation_id=conversation_id,
                    content=prompt,
                )
            else:
                msg = self._w.genie.start_conversation_and_wait(
                    space_id=GENIE_SPACE_ID,
                    content=prompt,
                )
        except Exception as e:
            return self._reply("Genie の呼び出しに失敗しました: " + str(e))

        parts = []
        sql = None
        sql_description = None

        for att in (msg.attachments or []):
            text = getattr(att, "text", None)
            if text is not None and getattr(text, "content", None):
                parts.append(text.content)

            query = getattr(att, "query", None)
            if query is not None:
                sql = getattr(query, "query", None)
                sql_description = getattr(query, "description", None)
                if sql_description:
                    parts.append(sql_description)
                try:
                    parts.append(
                        self._rows_preview(
                            msg.conversation_id, msg.id, att.attachment_id
                        )
                    )
                except Exception:
                    # 結果の取得に失敗しても、テキスト回答だけは返す
                    pass

        answer = "\n\n".join(p for p in parts if p) or "回答を取得できませんでした。"

        return self._reply(
            answer,
            {
                "conversation_id": msg.conversation_id,
                "sql": sql,
                "sql_description": sql_description,
            },
        )


AGENT = GenieChatAgent()
mlflow.models.set_model(AGENT)
