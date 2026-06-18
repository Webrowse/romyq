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


def load(base: str = ".") -> str:
    path = Path(base) / MISSION_FILE

    if not path.exists():
        raise FileNotFoundError(
            f"{MISSION_FILE} not found — run 'romyq init' first"
        )

    return path.read_text()


def exists(base: str = ".") -> bool:
    return (Path(base) / MISSION_FILE).exists()


def create_template(base: str = ".") -> bool:
    path = Path(base) / MISSION_FILE

    if path.exists():
        return False

    path.write_text(MISSION_TEMPLATE)
    return True
