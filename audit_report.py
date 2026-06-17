import json
from datetime import datetime, timezone


AUDIT_FILE = "audit_report.json"


def load_audit_report(
    path: str = AUDIT_FILE,
) -> list:
    try:
        with open(path) as f:
            return json.load(f)

    except FileNotFoundError:
        return []

    except json.JSONDecodeError:
        return []


def save_audit_report(
    findings: list,
    path: str = AUDIT_FILE,
) -> None:
    with open(path, "w") as f:
        json.dump(
            findings,
            f,
            indent=2,
        )


def add_finding(
    title: str,
    description: str,
    severity: str,
    path: str = AUDIT_FILE,
) -> None:
    findings = load_audit_report(path)

    findings.append(
        {
            "id": len(findings) + 1,
            "created_at": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "title": title,
            "description": description,
            "severity": severity,
            "resolved": False,
            "resolved_at": None,
        }
    )

    save_audit_report(
        findings,
        path,
    )


def resolve_finding(
    finding_id: int,
    path: str = AUDIT_FILE,
) -> bool:
    findings = load_audit_report(path)

    for finding in findings:
        if finding["id"] == finding_id:
            finding["resolved"] = True
            finding["resolved_at"] = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )

            save_audit_report(
                findings,
                path,
            )

            return True

    return False


def unresolved_findings(
    path: str = AUDIT_FILE,
) -> list:
    findings = load_audit_report(path)

    return [
        f
        for f in findings
        if not f["resolved"]
    ]


def unresolved_findings_text(
    path: str = AUDIT_FILE,
) -> str:
    findings = unresolved_findings(path)

    if not findings:
        return "No unresolved audit findings."

    output = []

    for finding in findings:
        output.append(
            f"""
ID: {finding["id"]}
Severity: {finding["severity"]}

Title:
{finding["title"]}

Description:
{finding["description"]}
"""
        )

    return "\n".join(output)
