"""GitLab AI Inception Agent.

GitLab IssueのコメントをClaude APIに渡して要件定義を自動進行するエージェント.
DBレス設計: 会話履歴はGitLab APIで毎回取得する.
"""

import logging
import os
import sys

import anthropic
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

GITLAB_URL = os.environ["GITLAB_URL"].rstrip("/")
GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
GITLAB_PROJECT_ID = os.environ["GITLAB_PROJECT_ID"]
ISSUE_IID = os.environ["ISSUE_IID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# BotコメントをHuman/Assistantコメントと区別するためのマーカー
BOT_MARKER = "<!-- ai-inception-bot -->"

INCEPTION_DONE_LABEL = "ai-inception-done"

SYSTEM_PROMPT = """You are an AI inception agent for a software development team. Your role is to facilitate requirements gathering for a new feature or project through a structured conversation.

## Your goal
Guide the user through defining clear, actionable requirements by asking focused questions to understand:
1. **Problem**: What problem is being solved and why does it matter?
2. **Users**: Who are the target users and what are their needs?
3. **Features**: What are the core features required (MVP scope)?
4. **Technical**: Any technical constraints, preferences, or integrations?
5. **Success criteria**: How will we know when this is done?
6. **Timeline**: What is the priority and expected timeline?

## Guidelines
- Ask ONE focused question at a time
- Follow up to clarify vague answers before moving on
- After gathering sufficient information (typically 5-10 exchanges), call `complete_requirements`
- Be professional and concise
- Respond in the same language as the user's messages (Japanese is fine)"""

TOOLS: list[dict] = [
    {
        "name": "complete_requirements",
        "description": "Call this tool when you have gathered sufficient requirements and are ready to conclude the inception phase. This will post the requirements summary to the GitLab issue and mark it as done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "Comprehensive requirements summary in Markdown format. "
                        "Include these sections: "
                        "## 概要, ## 課題・背景, ## 対象ユーザー, ## 主要機能 (MVP), "
                        "## 技術要件, ## 完了条件 (Definition of Done), ## 優先度・スケジュール"
                    ),
                }
            },
            "required": ["summary"],
        },
    }
]


# ---------- GitLab API helpers ----------


def _gitlab_headers() -> dict:
    return {"PRIVATE-TOKEN": GITLAB_TOKEN}


def get_issue(project_id: str, issue_iid: str) -> dict:
    """Fetch issue details from GitLab API."""
    response = httpx.get(
        f"{GITLAB_URL}/api/v4/projects/{project_id}/issues/{issue_iid}",
        headers=_gitlab_headers(),
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


def get_comments(project_id: str, issue_iid: str) -> list[dict]:
    """Fetch all comments for an issue in chronological order."""
    notes: list[dict] = []
    page = 1
    while True:
        response = httpx.get(
            f"{GITLAB_URL}/api/v4/projects/{project_id}/issues/{issue_iid}/notes",
            headers=_gitlab_headers(),
            params={"page": page, "per_page": 100, "sort": "asc", "order_by": "created_at"},
            timeout=15.0,
        )
        response.raise_for_status()
        batch: list[dict] = response.json()
        if not batch:
            break
        notes.extend(batch)
        page += 1
    return notes


def post_comment(project_id: str, issue_iid: str, body: str) -> None:
    """Post a bot comment to a GitLab issue."""
    response = httpx.post(
        f"{GITLAB_URL}/api/v4/projects/{project_id}/issues/{issue_iid}/notes",
        headers=_gitlab_headers(),
        json={"body": f"{BOT_MARKER}\n\n{body}"},
        timeout=15.0,
    )
    response.raise_for_status()
    logger.info("Posted comment to issue #%s", issue_iid)


def add_label(project_id: str, issue_iid: str, label: str) -> None:
    """Add a label to a GitLab issue (preserving existing labels)."""
    issue = get_issue(project_id, issue_iid)
    current_labels: list[str] = issue.get("labels", [])
    if label in current_labels:
        return
    response = httpx.put(
        f"{GITLAB_URL}/api/v4/projects/{project_id}/issues/{issue_iid}",
        headers=_gitlab_headers(),
        json={"labels": ",".join([*current_labels, label])},
        timeout=15.0,
    )
    response.raise_for_status()
    logger.info("Added label '%s' to issue #%s", label, issue_iid)


# ---------- Message building ----------


def build_messages(issue: dict, comments: list[dict]) -> list[dict]:
    """Convert GitLab issue + comments into Claude messages format.

    IssueタイトルとDescriptionを最初のuserメッセージとし、
    その後のコメントをBOT_MARKERで assistant/user に振り分ける.
    """
    messages: list[dict] = []

    # Issue本文を最初のユーザーメッセージとして扱う
    title = issue.get("title", "")
    description = (issue.get("description") or "").strip()
    first_content = f"Issue: {title}"
    if description:
        first_content += f"\n\n{description}"
    messages.append({"role": "user", "content": first_content})

    for note in comments:
        # システムノート (ラベル変更など) はスキップ
        if note.get("system"):
            continue
        body: str = note.get("body", "")
        if BOT_MARKER in body:
            clean = body.replace(BOT_MARKER, "").strip()
            messages.append({"role": "assistant", "content": clean})
        else:
            messages.append({"role": "user", "content": body})

    return _normalize_messages(messages)


def _normalize_messages(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages from the same role to satisfy Claude's alternation requirement."""
    if not messages:
        return messages
    normalized = [messages[0].copy()]
    for msg in messages[1:]:
        if msg["role"] == normalized[-1]["role"]:
            normalized[-1]["content"] += f"\n\n{msg['content']}"
        else:
            normalized.append(msg.copy())
    return normalized


# ---------- Main ----------


def main() -> None:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    issue = get_issue(GITLAB_PROJECT_ID, ISSUE_IID)
    comments = get_comments(GITLAB_PROJECT_ID, ISSUE_IID)
    messages = build_messages(issue, comments)

    logger.info("Issue #%s: %d messages in history", ISSUE_IID, len(messages))

    # 最後のメッセージがassistantなら新しいユーザー入力がないためスキップ
    if messages[-1]["role"] == "assistant":
        logger.info("No new user message to respond to. Skipping.")
        sys.exit(0)

    # システムプロンプトをキャッシュして毎回のAPI呼び出しコストを削減
    system_with_cache: list[dict] = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=system_with_cache,
        messages=messages,
        tools=TOOLS,
    )

    logger.info("Claude response: stop_reason=%s", response.stop_reason)

    if response.stop_reason == "tool_use":
        _handle_tool_use(response)
    else:
        _handle_text_response(response)


def _handle_tool_use(response: anthropic.types.Message) -> None:
    """complete_requirementsツール呼び出しを処理する."""
    for block in response.content:
        if block.type != "tool_use":
            continue
        if block.name != "complete_requirements":
            logger.warning("Unknown tool call: %s", block.name)
            continue

        summary: str = block.input["summary"]  # type: ignore[index]
        completion_body = (
            "## 要件定義サマリー\n\n"
            + summary
            + "\n\n---\n*インセプションフェーズが完了しました。次のステップはコンストラクションフェーズです。*"
        )
        post_comment(GITLAB_PROJECT_ID, ISSUE_IID, completion_body)
        add_label(GITLAB_PROJECT_ID, ISSUE_IID, INCEPTION_DONE_LABEL)
        logger.info("Inception phase complete for issue #%s", ISSUE_IID)
        return

    logger.error("tool_use stop_reason but no complete_requirements call found")
    sys.exit(1)


def _handle_text_response(response: anthropic.types.Message) -> None:
    """通常のテキスト応答をIssueにコメントとして投稿する."""
    text_parts: list[str] = []
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)

    if not text_parts:
        logger.warning("Empty text response from Claude")
        return

    post_comment(GITLAB_PROJECT_ID, ISSUE_IID, "\n\n".join(text_parts))


if __name__ == "__main__":
    main()
