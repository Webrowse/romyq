import datetime
from pathlib import Path


def append(path: str, message: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(path, "a") as f:
        f.write(f"- [{ts}] {message}\n")


def load(path: str) -> str:
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return ""


def count(path: str) -> int:
    return sum(
        1 for line in load(path).splitlines() if line.strip().startswith("-")
    )
