from openai import OpenAI

from . import store
from .context import load as load_context
from .history import recent_text
from .findings import unresolved_text
from .planning import build_planning_context
from .workspace import profile


# ── prompts ───────────────────────────────────────────────────────────────────

_MANAGER_SYSTEM = """\
You are the project manager of an autonomous software team.

The mission defines the final objective.

Your engineer is Claude Code.

Generate exactly ONE task.

Rules:

- Work in very small steps.
- Continue from repository state.
- Never repeat work.
- Prefer implementation tasks.
- Audit only when requested.
- During audits identify architecture issues, bugs,
  missing tests and technical debt.
- After audits generate repair tasks until issues are resolved.
- Every task must be independently completable.
- Every task must end with a git commit.
- Do not regenerate recently completed work.
- Use recent task history to avoid duplicates.
- Repository state is the source of truth.
- Prefer building over discussing.

Output only the task.
"""

_AUDIT_GUIDANCE = """\
You are performing an audit.

Focus on:
- Architecture problems
- Missing tests
- Bugs
- Technical debt
- Reliability issues
- Security issues
- Performance bottlenecks

Do not propose large rewrites. Produce actionable findings.
"""

_IMPL_GUIDANCE = """\
You are performing implementation work.

Focus on:
- Completing the mission
- Small connected tasks
- Incremental progress
- Shipping working code

Avoid audits unless explicitly requested.
"""

_EVALUATOR_SYSTEM = """\
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


def _client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


# ── task generation ───────────────────────────────────────────────────────────

def generate_task(
    api_key: str,
    mission: str,
    state: str,
    tasks_completed: int,
    git_log: str,
    git_status: str,
    mode: str,
    workspace: str,
    notes: str = "",
    state_dict: dict | None = None,
) -> str:
    guidance = _AUDIT_GUIDANCE if mode == "audit" else _IMPL_GUIDANCE

    notes_section = f"\nSteering Notes (highest priority — follow these before anything else):\n\n{notes.strip()}\n" if notes.strip() else ""

    # Build planning context from repository memory, recent failures, and blocked tasks
    planning_ctx = ""
    if state_dict is not None:
        ctx_text = load_context(workspace)
        planning_ctx = build_planning_context(
            state=state_dict,
            findings_path=store.findings_path(workspace),
            history_path=store.history_path(workspace),
            context_text=ctx_text,
            memory_path=store.memory_path(workspace),
            knowledge_path=store.knowledge_path(workspace),
        )
    planning_section = f"\n{planning_ctx}\n" if planning_ctx else ""

    prompt = f"""Mission:

{mission}
{notes_section}{planning_section}
Current State:

{state}

Tasks Completed: {tasks_completed}

Mode: {mode}

Mode Guidance:
{guidance}

Recent Task History:

{recent_text(limit=20, path=store.history_path(workspace))}

Unresolved Audit Findings:

{unresolved_text(path=store.findings_path(workspace))}

Git History:

{git_log}

Git Status:

{git_status}

Repository Profile:

{profile(workspace)}

Planning Rules:
- Use repository structure when planning.
- Use the detected language, frameworks, and build commands.
- Prefer modifying existing code over creating new files.
- Avoid creating duplicate systems.
- Respect unresolved audit findings.
- Continue the current architecture.
- Use the detected test suite when adding or running tests.
- Build toward mission completion.

Generate exactly ONE next task.
Requirements:
- Continue from current repository state.
- Do not repeat recent tasks.
- Respect unresolved findings.
- Every task must be completable.
- Every task must end with a git commit.

Output only the task.
"""

    response = _client(api_key).chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": _MANAGER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )

    return response.choices[0].message.content.strip()


# ── completion evaluation ─────────────────────────────────────────────────────

def _parse_completion(text: str) -> tuple[bool, str]:
    completed = False
    reason = "No reason provided."

    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("completed:"):
            completed = line.split(":", 1)[1].strip().lower() == "true"
        elif line.lower().startswith("reason:"):
            reason = line.split(":", 1)[1].strip()

    return completed, reason


def evaluate_completion(
    api_key: str,
    mission: str,
    workspace: str,
    git_log: str,
) -> tuple[bool, str]:
    prompt = f"""Mission:

{mission}

Repository Profile:

{profile(workspace)}

Recent Git Log:

{git_log}

Recent Task History:

{recent_text(limit=20, path=store.history_path(workspace))}

Unresolved Audit Findings:

{unresolved_text(path=store.findings_path(workspace))}

Has the mission been completed?
"""

    response = _client(api_key).chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": _EVALUATOR_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    return _parse_completion(response.choices[0].message.content.strip())
