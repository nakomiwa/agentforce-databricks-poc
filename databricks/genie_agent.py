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

import time
import uuid

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse

# 作成済みの Genie Space
GENIE_SPACE_ID = "01f1b4f5cca01e879e5ae04b2823e9c9"

# Genie は質問が日本語なら日本語で返すが、書式を揃えるため明示する
JA_HINT = "（日本語で、金額は3桁区切りで回答してください）"

# クエリ結果を本文に添える行数
MAX_PREVIEW_ROWS = 10

# ポーリング間隔と上限。3 秒 × 120 回 = 最大 6 分。
# Model Serving のサーバー側タイムアウトは 597 秒なので、その内側に収まる。
POLL_SECONDS = 3
MAX_POLLS = 120

# Genie の終了状態
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED")


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

    def _wait(self, conversation_id, message_id):
        """完了までポーリングする。

        SDK の start_conversation_and_wait / create_message_and_wait は使わない。
        失敗時に Genie が返す error を捨てて
        「failed to reach COMPLETED, got MessageStatus.FAILED」としか言わず、
        原因（権限不足なのか SQL エラーなのか）が分からなくなるため。
        """
        msg = None
        for _ in range(MAX_POLLS):
            msg = self._w.genie.get_message(
                space_id=GENIE_SPACE_ID,
                conversation_id=conversation_id,
                message_id=message_id,
            )
            status = msg.status.value if msg.status else ""
            if status in TERMINAL:
                return msg, status
            time.sleep(POLL_SECONDS)
        return msg, "TIMEOUT"

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
                started = self._w.genie.create_message(
                    space_id=GENIE_SPACE_ID,
                    conversation_id=conversation_id,
                    content=prompt,
                )
            else:
                started = self._w.genie.start_conversation(
                    space_id=GENIE_SPACE_ID,
                    content=prompt,
                )
        except Exception as e:
            return self._reply("Genie の呼び出しに失敗しました: " + str(e))

        cid = getattr(started, "conversation_id", None) or conversation_id
        mid = getattr(started, "message_id", None) or getattr(started, "id", None)

        try:
            msg, status = self._wait(cid, mid)
        except Exception as e:
            return self._reply("Genie の状態取得に失敗しました: " + str(e))

        if status != "COMPLETED":
            # ここで error を捨てない。原因の切り分けはこの文字列が頼りになる。
            err = getattr(msg, "error", None)
            return self._reply(
                f"Genie が処理に失敗しました。status={status} / error={err}",
                {"conversation_id": cid},
            )

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
                    parts.append(self._rows_preview(cid, mid, att.attachment_id))
                except Exception as e:
                    # 結果の取得に失敗しても、テキスト回答だけは返す
                    parts.append(f"（クエリ結果の取得に失敗: {e}）")

        answer = "\n\n".join(p for p in parts if p) or "回答を取得できませんでした。"

        return self._reply(
            answer,
            {
                "conversation_id": cid,
                "sql": sql,
                "sql_description": sql_description,
            },
        )


AGENT = GenieChatAgent()
mlflow.models.set_model(AGENT)
