from pathlib import Path


ROOT_FILES = [
    "Cargo.toml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "README.md",
]


def detect_project_type(
    workspace: str,
) -> str:
    root = Path(workspace)

    if (root / "Cargo.toml").exists():
        return "rust"

    if (root / "package.json").exists():
        return "node"

    if (root / "pyproject.toml").exists():
        return "python"

    if (root / "requirements.txt").exists():
        return "python"

    if (root / "go.mod").exists():
        return "go"

    if (root / "pom.xml").exists():
        return "java"

    if (root / "build.gradle").exists():
        return "java"

    return "unknown"


def important_files(
    workspace: str,
) -> list[str]:
    root = Path(workspace)

    files = []

    for name in ROOT_FILES:
        path = root / name

        if path.exists():
            files.append(name)

    return files


def top_level_directories(
    workspace: str,
) -> list[str]:
    root = Path(workspace)

    directories = []

    for item in root.iterdir():
        if item.is_dir():
            directories.append(item.name)

    directories.sort()

    return directories


def top_level_files(
    workspace: str,
) -> list[str]:
    root = Path(workspace)

    files = []

    for item in root.iterdir():
        if item.is_file():
            files.append(item.name)

    files.sort()

    return files


def repository_summary(
    workspace: str,
) -> dict:
    return {
        "project_type": detect_project_type(
            workspace
        ),
        "important_files": important_files(
            workspace
        ),
        "top_level_directories": (
            top_level_directories(
                workspace
            )
        ),
        "top_level_files": top_level_files(
            workspace
        ),
    }


def repository_summary_text(
    workspace: str,
) -> str:
    summary = repository_summary(
        workspace
    )

    return f"""
Project Type:
{summary["project_type"]}

Important Files:
{", ".join(summary["important_files"])}

Directories:
{", ".join(summary["top_level_directories"])}

Files:
{", ".join(summary["top_level_files"])}
""".strip()
