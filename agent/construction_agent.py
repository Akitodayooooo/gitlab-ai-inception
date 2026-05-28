"""GitLab AI Construction Agent.

ai-inception-done ラベルをトリガーにブランチを作成し、コードを実装してMRを作成する.
MRへのレビューコメントへの対応も行う.
"""

import base64
import logging
import os
import re
import sys

import anthropic
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GITLAB_URL = os.environ["GITLAB_URL"].rstrip("/")
GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
GITLAB_PROJECT_ID = os.environ["GITLAB_PROJECT_ID"]
ISSUE_IID = os.environ.get("ISSUE_IID", "")
MR_IID = os.environ.get("MR_IID", "")
EVENT_TYPE = os.environ.get("EVENT_TYPE", "construction_start")
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

BOT_MARKER = "<!-- ai-construction-bot -->"
INCEPTION_BOT_MARKER = "<!-- ai-inception-bot -->"
MAX_ITERATIONS = 30

CONSTRUCTION_SYSTEM_PROMPT = """You are an AI construction agent for a software development team.
Your role is to implement code based on requirements from the inception phase.

## Workflow
1. Explore the existing codebase to understand the project structure
2. Implement the required features by creating or modifying files on the feature branch
3. Call `create_merge_request` when the implementation is complete

## Guidelines
- Always explore the codebase BEFORE writing any code
- Follow existing patterns and conventions in the project
- Write clean, production-ready code
- Make small, focused commits with clear messages
- Respond in the same language as the requirements (Japanese is fine)"""

REVIEW_SYSTEM_PROMPT = """You are an AI code review responder.
Your role is to address review comments on a Merge Request.

## Workflow
1. Read the MR changes and review comments
2. Update code where the feedback is valid
3. Call `post_review_response` with a summary of what you did

## Guidelines
- Address all review comments
- Be professional and constructive"""


# ---------- GitLab API helpers ----------


def _h() -> dict:
    return {"PRIVATE-TOKEN": GITLAB_TOKEN}


def get_issue(issue_iid: str) -> dict:
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}",
                  headers=_h(), timeout=15)
    r.raise_for_status()
    return r.json()


def get_issue_notes(issue_iid: str) -> list[dict]:
    notes: list[dict] = []
    page = 1
    while True:
        r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}/notes",
                      headers=_h(), params={"page": page, "per_page": 100, "sort": "asc"}, timeout=15)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        notes.extend(batch)
        page += 1
    return notes


def post_issue_comment(issue_iid: str, body: str) -> None:
    r = httpx.post(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}/notes",
                   headers=_h(), json={"body": f"{BOT_MARKER}\n\n{body}"}, timeout=15)
    r.raise_for_status()


def create_branch(branch_name: str, ref: str = "main") -> None:
    r = httpx.post(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/repository/branches",
                   headers=_h(), json={"branch": branch_name, "ref": ref}, timeout=15)
    if r.status_code == 400:
        logger.info("Branch already exists: %s", branch_name)
        return
    r.raise_for_status()


def list_files(path: str, ref: str) -> list[dict]:
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/repository/tree",
                  headers=_h(), params={"path": path, "ref": ref, "per_page": 100}, timeout=15)
    r.raise_for_status()
    return r.json()


def read_file(file_path: str, ref: str) -> str:
    encoded = file_path.replace("/", "%2F")
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{encoded}",
                  headers=_h(), params={"ref": ref}, timeout=15)
    r.raise_for_status()
    return base64.b64decode(r.json()["content"]).decode("utf-8", errors="replace")


def file_exists(file_path: str, ref: str) -> bool:
    encoded = file_path.replace("/", "%2F")
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{encoded}",
                  headers=_h(), params={"ref": ref}, timeout=15)
    return r.status_code == 200


def write_file(file_path: str, content: str, branch: str, commit_message: str) -> None:
    encoded = file_path.replace("/", "%2F")
    payload = {"branch": branch, "content": content, "commit_message": commit_message}
    if file_exists(file_path, branch):
        r = httpx.put(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{encoded}",
                      headers=_h(), json=payload, timeout=15)
    else:
        r = httpx.post(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{encoded}",
                       headers=_h(), json=payload, timeout=15)
    r.raise_for_status()


def create_mr(title: str, description: str, source_branch: str) -> dict:
    r = httpx.post(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/merge_requests",
                   headers=_h(), json={
                       "title": title,
                       "description": description,
                       "source_branch": source_branch,
                       "target_branch": "main",
                       "remove_source_branch": True,
                   }, timeout=15)
    r.raise_for_status()
    return r.json()


def get_mr(mr_iid: str) -> dict:
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/merge_requests/{mr_iid}",
                  headers=_h(), timeout=15)
    r.raise_for_status()
    return r.json()


def get_mr_changes(mr_iid: str) -> dict:
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/merge_requests/{mr_iid}/changes",
                  headers=_h(), timeout=15)
    r.raise_for_status()
    return r.json()


def get_mr_notes(mr_iid: str) -> list[dict]:
    r = httpx.get(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/merge_requests/{mr_iid}/notes",
                  headers=_h(), params={"sort": "asc", "per_page": 100}, timeout=15)
    r.raise_for_status()
    return r.json()


def post_mr_comment(mr_iid: str, body: str) -> None:
    r = httpx.post(f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/merge_requests/{mr_iid}/notes",
                   headers=_h(), json={"body": f"{BOT_MARKER}\n\n{body}"}, timeout=15)
    r.raise_for_status()


# ---------- Tools ----------


CONSTRUCTION_TOOLS: list[dict] = [
    {
        "name": "list_files",
        "description": "List files and directories in the repository at a given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (empty string for root)"}
            },
            "required": []
        }
    },
    {
        "name": "read_file",
        "description": "Read the content of a file from the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write_file",
        "description": "Create or update a file on the feature branch with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Full file content"},
                "commit_message": {"type": "string", "description": "Commit message"}
            },
            "required": ["file_path", "content", "commit_message"]
        }
    },
    {
        "name": "create_merge_request",
        "description": "Create a Merge Request. Call this when all implementation is complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "MR title"},
                "description": {"type": "string", "description": "MR description in Markdown"}
            },
            "required": ["title", "description"]
        }
    }
]

REVIEW_TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read a file from the feature branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write_file",
        "description": "Update a file on the feature branch to address review feedback.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Updated file content"},
                "commit_message": {"type": "string", "description": "Commit message"}
            },
            "required": ["file_path", "content", "commit_message"]
        }
    },
    {
        "name": "post_review_response",
        "description": "Post a summary comment on the MR. Call this when done addressing all review comments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Summary of what was done"}
            },
            "required": ["message"]
        }
    }
]


def execute_tool(name: str, inputs: dict, ctx: dict) -> tuple[str, bool]:
    """Execute a tool and return (result_text, should_stop_loop)."""
    branch = ctx["branch"]
    try:
        if name == "list_files":
            files = list_files(inputs.get("path", ""), branch)
            lines = [f"{f['type']}: {f['path']}" for f in files]
            return "\n".join(lines) or "(empty)", False

        if name == "read_file":
            content = read_file(inputs["file_path"], branch)
            return content, False

        if name == "write_file":
            write_file(inputs["file_path"], inputs["content"], branch, inputs["commit_message"])
            logger.info("Wrote: %s", inputs["file_path"])
            return f"Written: {inputs['file_path']}", False

        if name == "create_merge_request":
            mr = create_mr(inputs["title"], inputs["description"], branch)
            url = mr.get("web_url", "")
            logger.info("MR created: %s", url)
            if ctx.get("issue_iid"):
                post_issue_comment(ctx["issue_iid"],
                    f"コンストラクションフェーズが完了しました。\n\nMRを作成しました: {url}")
            return f"MR created: {url}", True  # ループ終了

        if name == "post_review_response":
            post_mr_comment(ctx["mr_iid"], inputs["message"])
            return "Comment posted", True  # ループ終了

        return f"Unknown tool: {name}", False

    except Exception as e:
        logger.error("Tool [%s] error: %s", name, e)
        return f"Error: {e}", False


# ---------- Agentic loop ----------


def run_agentic_loop(
    client: anthropic.Anthropic,
    system_prompt: str,
    initial_messages: list[dict],
    tools: list[dict],
    ctx: dict,
) -> None:
    messages = list(initial_messages)

    for i in range(MAX_ITERATIONS):
        logger.info("Iteration %d / %d", i + 1, MAX_ITERATIONS)

        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
        )
        logger.info("stop_reason: %s", response.stop_reason)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            should_stop = False
            for block in response.content:
                if block.type == "tool_use":
                    result, stop = execute_tool(block.name, block.input, ctx)  # type: ignore[arg-type]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                    if stop:
                        should_stop = True
            messages.append({"role": "user", "content": tool_results})
            if should_stop:
                break


# ---------- Phase runners ----------


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:40].strip("-")


def _get_requirements(issue_iid: str) -> str:
    """インセプションフェーズのサマリーコメントを取得する."""
    for note in reversed(get_issue_notes(issue_iid)):
        body = note.get("body", "")
        if INCEPTION_BOT_MARKER in body and "要件定義サマリー" in body:
            return body.replace(INCEPTION_BOT_MARKER, "").strip()
    return ""


def run_construction() -> None:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    issue = get_issue(ISSUE_IID)
    requirements = _get_requirements(ISSUE_IID) or (
        f"Issue: {issue['title']}\n{issue.get('description', '')}"
    )

    branch = f"feature/issue-{ISSUE_IID}-{_slugify(issue['title'])}"
    create_branch(branch)
    logger.info("Branch: %s", branch)

    post_issue_comment(ISSUE_IID,
        f"コンストラクションフェーズを開始します。\n\nブランチ: `{branch}`")

    initial_message = f"""以下の要件に基づいて実装してください。

## Issue #{ISSUE_IID}: {issue['title']}

{requirements}

## 作業ブランチ
`{branch}`

まず既存のコードベースを調査してから実装を開始し、完了後に `create_merge_request` を呼び出してください。"""

    run_agentic_loop(
        client,
        CONSTRUCTION_SYSTEM_PROMPT,
        [{"role": "user", "content": initial_message}],
        CONSTRUCTION_TOOLS,
        {"branch": branch, "issue_iid": ISSUE_IID},
    )
    logger.info("Construction complete for issue #%s", ISSUE_IID)


def run_review() -> None:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    mr = get_mr(MR_IID)
    branch = mr["source_branch"]
    changes = get_mr_changes(MR_IID)
    notes = get_mr_notes(MR_IID)

    # Botコメントとシステムノートを除外
    review_comments = [
        n for n in notes
        if not n.get("system") and BOT_MARKER not in n.get("body", "")
    ]
    if not review_comments:
        logger.info("No review comments to respond to")
        return

    changed_files = "\n".join(
        f"- {c['new_path']}" for c in changes.get("changes", [])[:15]
    )
    review_text = "\n\n".join(
        f"**{n['author']['username']}**: {n['body']}"
        for n in review_comments[-10:]
    )

    initial_message = f"""MR #{MR_IID}「{mr['title']}」へのレビューコメントに対応してください。

## 変更ファイル
{changed_files}

## レビューコメント
{review_text}

ブランチ: `{branch}`"""

    run_agentic_loop(
        client,
        REVIEW_SYSTEM_PROMPT,
        [{"role": "user", "content": initial_message}],
        REVIEW_TOOLS,
        {"branch": branch, "mr_iid": MR_IID},
    )
    logger.info("Review response complete for MR #%s", MR_IID)


# ---------- Entry point ----------


def main() -> None:
    if EVENT_TYPE == "construction_start":
        if not ISSUE_IID:
            logger.error("ISSUE_IID is required for construction_start")
            sys.exit(1)
        run_construction()
    elif EVENT_TYPE == "mr_review":
        if not MR_IID:
            logger.error("MR_IID is required for mr_review")
            sys.exit(1)
        run_review()
    else:
        logger.error("Unknown EVENT_TYPE: %s", EVENT_TYPE)
        sys.exit(1)


if __name__ == "__main__":
    main()
