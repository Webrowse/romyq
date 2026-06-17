from pathlib import Path


MISSION_FILE = "mission.md"


def load_mission() -> str:
    path = Path(MISSION_FILE)

    if not path.exists():
        raise FileNotFoundError(
            f"{MISSION_FILE} not found"
        )

    return path.read_text()


def mission_exists() -> bool:
    return Path(
        MISSION_FILE
    ).exists()


def objective(mission: str) -> str:
    lines = []

    capture = False

    for line in mission.splitlines():
        stripped = line.strip()

        if stripped.lower() == "# objective":
            capture = True
            continue

        if capture and stripped.startswith("#"):
            break

        if capture:
            lines.append(line)

    return "\n".join(lines).strip()


def constraints(mission: str) -> str:
    lines = []

    capture = False

    for line in mission.splitlines():
        stripped = line.strip()

        if stripped.lower() == "# constraints":
            capture = True
            continue

        if capture and stripped.startswith("#"):
            break

        if capture:
            lines.append(line)

    return "\n".join(lines).strip()


def success_criteria(
    mission: str,
) -> str:
    lines = []

    capture = False

    for line in mission.splitlines():
        stripped = line.strip()

        if (
            stripped.lower()
            == "# success criteria"
        ):
            capture = True
            continue

        if capture and stripped.startswith("#"):
            break

        if capture:
            lines.append(line)

    return "\n".join(lines).strip()


def human_overrides(
    mission: str,
) -> str:
    lines = []

    capture = False

    for line in mission.splitlines():
        stripped = line.strip()

        if (
            stripped.lower()
            == "# human overrides"
        ):
            capture = True
            continue

        if capture and stripped.startswith("#"):
            break

        if capture:
            lines.append(line)

    return "\n".join(lines).strip()
