from pathlib import Path


MISSION_FILE = "mission.md"

MISSION_TEMPLATE = """\
Write your mission here.

Describe what you want to build in plain language.

Example:
  Build a SaaS for invoicing.
  Build a Reddit competitor.
  Build a personal finance tracker.

No template, schema, or structure required.
"""


def load() -> str:
    path = Path(MISSION_FILE)

    if not path.exists():
        raise FileNotFoundError(
            f"{MISSION_FILE} not found — run 'romiq init' first"
        )

    return path.read_text()


def exists() -> bool:
    return Path(MISSION_FILE).exists()


def create_template() -> bool:
    path = Path(MISSION_FILE)

    if path.exists():
        return False

    path.write_text(MISSION_TEMPLATE)
    return True
