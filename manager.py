from openai import OpenAI

from prompts import (
    MANAGER_SYSTEM_PROMPT,
    build_manager_prompt,
)

from task_history import (
    recent_tasks_text,
)

from audit_report import (
    unresolved_findings_text,
)

from workspace import summary_text as repository_summary_text


def generate_task(
    api_key: str,
    mission: str,
    state: str,
    tasks_completed: int,
    git_log: str,
    git_status: str,
    mode: str,
    workspace: str,
) -> str:
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    recent_history = recent_tasks_text(
        limit=20,
    )

    findings = (
        unresolved_findings_text()
    )

    repo_summary = repository_summary_text(workspace)

    prompt = build_manager_prompt(
        mission=mission,
        state=state,
        tasks_completed=tasks_completed,
        mode=mode,
        recent_history=recent_history,
        git_log=git_log,
        git_status=git_status,
        unresolved_findings=findings,
    )

    prompt += f"""

Repository Summary:

{repo_summary}

Planning Rules:

- Use repository structure when planning.
- Prefer modifying existing code.
- Avoid creating duplicate systems.
- Respect unresolved audit findings.
- Continue the current architecture.
- Build toward mission completion.
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": MANAGER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    task = (
        response
        .choices[0]
        .message
        .content
        .strip()
    )

    return task
