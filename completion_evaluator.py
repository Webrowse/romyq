from openai import OpenAI

from audit_report import unresolved_findings_text
from repository_state import repository_summary_text
from task_history import recent_tasks_text


EVALUATOR_SYSTEM_PROMPT = """
You are a mission completion evaluator for an autonomous software development system.

Your only job is to decide whether the mission has been fully completed based on
the current state of the repository.

Rules:

- Be conservative. Only return completed: true when the mission is substantially
  and verifiably implemented in the repository, not merely started or partially done.
- Unresolved audit findings are a signal the mission is not complete.
- An empty or near-empty repository is never complete.
- A mission is complete when the core requirements described are working and committed.
- Ignore aspirational stretch goals that go beyond the stated mission.

Respond with exactly two lines and nothing else:

completed: true
reason: <one sentence>

or:

completed: false
reason: <one sentence>
"""


def _build_prompt(
    mission: str,
    findings: str,
    repo_summary: str,
    recent_history: str,
    git_log: str,
) -> str:
    return f"""Mission:

{mission}

Repository Summary:

{repo_summary}

Recent Git Log:

{git_log}

Recent Task History:

{recent_history}

Unresolved Audit Findings:

{findings}

Has the mission been completed?
"""


def _parse_response(text: str) -> tuple[bool, str]:
    completed = False
    reason = "No reason provided."

    for line in text.splitlines():
        line = line.strip()

        if line.lower().startswith("completed:"):
            value = line.split(":", 1)[1].strip().lower()
            completed = value == "true"

        elif line.lower().startswith("reason:"):
            reason = line.split(":", 1)[1].strip()

    return completed, reason


def evaluate_completion(
    api_key: str,
    mission: str,
    workspace: str,
    git_log: str,
) -> tuple[bool, str]:
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    findings = unresolved_findings_text()
    repo_summary = repository_summary_text(workspace)
    recent_history = recent_tasks_text(limit=20)

    prompt = _build_prompt(
        mission=mission,
        findings=findings,
        repo_summary=repo_summary,
        recent_history=recent_history,
        git_log=git_log,
    )

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": EVALUATOR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    return _parse_response(raw)
