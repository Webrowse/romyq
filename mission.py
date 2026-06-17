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
    return Path(MISSION_FILE).exists()
