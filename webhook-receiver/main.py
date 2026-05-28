"""FastAPI Webhook receiver: GitLabのWebhookを受けてCI Pipelineをトリガーする."""

import logging
import os

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GitLab Webhook Receiver")

GITLAB_URL = os.environ["GITLAB_URL"]
GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
TRIGGER_TOKEN = os.environ["TRIGGER_TOKEN"]
GITLAB_PROJECT_ID = os.environ["GITLAB_PROJECT_ID"]
BOT_USER_ID = int(os.environ["BOT_USER_ID"])

INCEPTION_LABEL = "ai-inception"
INCEPTION_DONE_LABEL = "ai-inception-done"


def trigger_pipeline(issue_iid: str, event_type: str) -> None:
    """Pipeline Trigger APIを呼び出してCI Jobを起動する."""
    response = httpx.post(
        f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/trigger/pipeline",
        data={
            "token": TRIGGER_TOKEN,
            "ref": "main",
            "variables[ISSUE_IID]": issue_iid,
            "variables[EVENT_TYPE]": event_type,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    logger.info("Pipeline triggered for issue #%s (event: %s)", issue_iid, event_type)


def get_issue_labels(issue_iid: str) -> list[str]:
    """対象IssueのラベルリストをGitLab APIから取得する."""
    response = httpx.get(
        f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}",
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("labels", [])


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    x_gitlab_token: str | None = Header(None),
) -> dict:
    if x_gitlab_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()
    event_type = payload.get("object_kind")
    logger.info("Received webhook event: %s", event_type)

    if event_type == "issue":
        return _handle_issue_event(payload)

    if event_type == "note":
        return _handle_note_event(payload)

    return {"status": "ignored", "reason": f"unhandled event type: {event_type}"}


def _handle_issue_event(payload: dict) -> dict:
    """IssueイベントからのWebhookを処理する.

    ai-inception ラベルが新たに付与された場合のみPipelineをトリガーする.
    """
    changes = payload.get("changes", {})
    labels_change = changes.get("labels", {})

    current_labels = [label["title"] for label in labels_change.get("current", [])]
    previous_labels = [label["title"] for label in labels_change.get("previous", [])]

    # ai-inception ラベルが今回初めて付与されたか判定
    newly_added = INCEPTION_LABEL in current_labels and INCEPTION_LABEL not in previous_labels

    if not newly_added:
        return {"status": "ignored", "reason": "inception label not newly added"}

    # すでに完了済みの場合はスキップ
    if INCEPTION_DONE_LABEL in current_labels:
        return {"status": "ignored", "reason": "already done"}

    issue_iid = str(payload["object_attributes"]["iid"])
    trigger_pipeline(issue_iid, "label_added")
    return {"status": "ok", "issue_iid": issue_iid}


def _handle_note_event(payload: dict) -> dict:
    """NoteイベントからのWebhookを処理する.

    ai-inception ラベルが付いたIssueへのユーザーコメントのみPipelineをトリガーする.
    """
    note = payload.get("object_attributes", {})

    # Issue以外のコメント (MR, Snippet等) は無視
    if note.get("noteable_type") != "Issue":
        return {"status": "ignored", "reason": "not an issue note"}

    # Bot自身のコメントによる無限ループを防止
    author_id = payload.get("user", {}).get("id")
    if author_id == BOT_USER_ID:
        return {"status": "ignored", "reason": "bot comment"}

    # GitLabのコメントWebhookではIIDはtop-levelの issue.iid に入っている
    issue_iid = str(payload.get("issue", {}).get("iid"))

    # ai-inception ラベルが付いており、かつ未完了の場合のみトリガー
    labels = get_issue_labels(issue_iid)
    if INCEPTION_LABEL not in labels:
        return {"status": "ignored", "reason": "no inception label"}
    if INCEPTION_DONE_LABEL in labels:
        return {"status": "ignored", "reason": "already done"}

    trigger_pipeline(issue_iid, "comment")
    return {"status": "ok", "issue_iid": issue_iid}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
