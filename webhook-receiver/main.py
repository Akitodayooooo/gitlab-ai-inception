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


def trigger_pipeline(event_type: str, variables: dict | None = None) -> None:
    """Pipeline Trigger APIを呼び出してCI Jobを起動する."""
    data: dict = {
        "token": TRIGGER_TOKEN,
        "ref": "main",
        "variables[EVENT_TYPE]": event_type,
    }
    if variables:
        for key, value in variables.items():
            data[f"variables[{key}]"] = str(value)

    response = httpx.post(
        f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/trigger/pipeline",
        data=data,
        timeout=10.0,
    )
    response.raise_for_status()
    logger.info("Pipeline triggered: event=%s vars=%s", event_type, variables)


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

    return {"status": "ignored", "reason": f"unhandled event: {event_type}"}


def _handle_issue_event(payload: dict) -> dict:
    """Issueのラベル変更イベントを処理する."""
    changes = payload.get("changes", {})
    labels_change = changes.get("labels", {})
    current_labels = [l["title"] for l in labels_change.get("current", [])]
    previous_labels = [l["title"] for l in labels_change.get("previous", [])]

    issue_iid = str(payload["object_attributes"]["iid"])

    # ai-inception ラベルが今回新たに付与された → インセプション開始
    if INCEPTION_LABEL in current_labels and INCEPTION_LABEL not in previous_labels:
        if INCEPTION_DONE_LABEL not in current_labels:
            trigger_pipeline("label_added", {"ISSUE_IID": issue_iid})
            return {"status": "ok", "event": "label_added", "issue_iid": issue_iid}

    # ai-inception-done ラベルが今回新たに付与された → コンストラクション開始
    if INCEPTION_DONE_LABEL in current_labels and INCEPTION_DONE_LABEL not in previous_labels:
        trigger_pipeline("construction_start", {"ISSUE_IID": issue_iid})
        return {"status": "ok", "event": "construction_start", "issue_iid": issue_iid}

    return {"status": "ignored", "reason": "no relevant label change"}


def _handle_note_event(payload: dict) -> dict:
    """コメントイベントを処理する. Issue / MR どちらも対応する."""
    note = payload.get("object_attributes", {})
    noteable_type = note.get("noteable_type")

    if noteable_type == "Issue":
        return _handle_issue_note(payload, note)
    if noteable_type == "MergeRequest":
        return _handle_mr_note(payload)

    return {"status": "ignored", "reason": f"unsupported noteable_type: {noteable_type}"}


def _handle_issue_note(payload: dict, note: dict) -> dict:
    """ai-inception ラベル付きIssueへのコメントに反応する."""
    author_id = payload.get("user", {}).get("id")
    if author_id == BOT_USER_ID:
        return {"status": "ignored", "reason": "bot comment"}

    # GitLabのコメントWebhookではIIDはtop-levelの issue.iid に入っている
    issue_iid = str(payload.get("issue", {}).get("iid"))

    labels = get_issue_labels(issue_iid)
    if INCEPTION_LABEL not in labels:
        return {"status": "ignored", "reason": "no inception label"}
    if INCEPTION_DONE_LABEL in labels:
        return {"status": "ignored", "reason": "already done"}

    trigger_pipeline("comment", {"ISSUE_IID": issue_iid})
    return {"status": "ok", "event": "comment", "issue_iid": issue_iid}


def _handle_mr_note(payload: dict) -> dict:
    """MRへのレビューコメントに反応する."""
    author_id = payload.get("user", {}).get("id")
    if author_id == BOT_USER_ID:
        return {"status": "ignored", "reason": "bot comment"}

    mr_iid = str(payload.get("merge_request", {}).get("iid", ""))
    if not mr_iid:
        return {"status": "ignored", "reason": "no mr_iid"}

    trigger_pipeline("mr_review", {"MR_IID": mr_iid})
    return {"status": "ok", "event": "mr_review", "mr_iid": mr_iid}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
