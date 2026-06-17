import re
from audit_report import add_finding


SEVERITY_KEYWORDS = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "warning": "medium",
    "warn": "medium",
    "error": "high",
    "bug": "high",
    "issue": "medium",
    "problem": "medium",
    "todo": "low",
    "fixme": "low",
    "hack": "low",
    "debt": "low",
    "technical debt": "low",
}

FINDING_PATTERN = re.compile(
    r"(?:^|\n)"
    r"(?:finding|issue|bug|problem|audit finding|finding \d+)[:\-\s]+"
    r"(.+?)(?=\n\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)

SEVERITY_PATTERN = re.compile(
    r"\b(critical|high|medium|low)\b",
    re.IGNORECASE,
)


def _detect_severity(text: str) -> str:
    match = SEVERITY_PATTERN.search(text)

    if match:
        return match.group(1).lower()

    text_lower = text.lower()

    for keyword, severity in SEVERITY_KEYWORDS.items():
        if keyword in text_lower:
            return severity

    return "medium"


def extract_and_save_findings(
    claude_output: str,
    mode: str,
) -> int:
    if mode != "audit":
        return 0

    matches = FINDING_PATTERN.findall(claude_output)

    saved = 0

    for match in matches:
        text = match.strip()

        if len(text) < 20:
            continue

        lines = text.splitlines()
        title = lines[0][:120].strip()
        description = text

        severity = _detect_severity(text)

        add_finding(
            title=title,
            description=description,
            severity=severity,
        )

        saved += 1

    return saved
