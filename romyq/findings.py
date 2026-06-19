import json
import os
import re
import tempfile
from datetime import datetime, timezone


_SEVERITY_PATTERN = re.compile(r"\b(critical|high|medium|low)\b", re.IGNORECASE)

_FINDING_PATTERN = re.compile(
    r"(?:^|\n)(?:finding|issue|bug|problem|audit finding|finding \d+)[:\-\s]+(.+?)(?=\n\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)

_SEVERITY_KEYWORDS = {
    "critical": "critical",
    "high": "high",
    "error": "high",
    "bug": "high",
    "medium": "medium",
    "warning": "medium",
    "issue": "medium",
    "problem": "medium",
    "low": "low",
    "todo": "low",
    "fixme": "low",
    "hack": "low",
    "debt": "low",
}


def _load(path: str) -> list:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(findings: list, path: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
        json.dump(findings, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, path)


def _detect_severity(text: str) -> str:
    m = _SEVERITY_PATTERN.search(text)
    if m:
        return m.group(1).lower()

    text_lower = text.lower()
    for keyword, severity in _SEVERITY_KEYWORDS.items():
        if keyword in text_lower:
            return severity

    return "medium"


def add_finding(title: str, description: str, severity: str, path: str) -> None:
    findings = _load(path)
    findings.append(
        {
            "id": len(findings) + 1,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "title": title,
            "description": description,
            "severity": severity,
            "resolved": False,
            "resolved_at": None,
        }
    )
    _save(findings, path)


def unresolved(path: str) -> list:
    return [f for f in _load(path) if not f["resolved"]]


def unresolved_text(path: str) -> str:
    items = unresolved(path)

    if not items:
        return "No unresolved audit findings."

    lines = []
    for f in items:
        lines.append(
            f"ID: {f['id']}  Severity: {f['severity']}\n"
            f"Title: {f['title']}\n"
            f"{f['description']}"
        )

    return "\n\n---\n\n".join(lines)


def extract_from_output(claude_output: str, mode: str, path: str) -> int:
    if mode != "audit":
        return 0

    saved = 0
    for match in _FINDING_PATTERN.findall(claude_output):
        text = match.strip()
        if len(text) < 20:
            continue

        title = text.splitlines()[0][:120].strip()
        add_finding(title=title, description=text, severity=_detect_severity(text), path=path)
        saved += 1

    return saved
