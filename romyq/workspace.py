import json
import re
import subprocess
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
    "Makefile",
    "README.md",
    "tsconfig.json",
    ".env.example",
]


# ── bootstrap ─────────────────────────────────────────────────────────────────

def is_git_repo(path: str) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path, capture_output=True,
    )
    return r.returncode == 0


def has_commits(path: str) -> bool:
    r = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=path, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def _ensure_gitignore_entry(path: str, entry: str) -> bool:
    """Add entry to {path}/.gitignore if not already present. Returns True if changed."""
    gitignore = Path(path) / ".gitignore"
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if entry in content.splitlines():
        return False
    if content and not content.endswith("\n"):
        content += "\n"
    content += entry + "\n"
    gitignore.write_text(content, encoding="utf-8")
    return True


def bootstrap(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)

    if not is_git_repo(path):
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        print(f"Initialized git repository in {path}/")

    if not has_commits(path):
        gitignore = Path(path) / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Romyq workspace\n.romyq/\n")
        else:
            _ensure_gitignore_entry(path, ".romyq/")

        subprocess.run(["git", "add", ".gitignore"], cwd=path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=path, capture_output=True,
        )
        print(f"Created initial commit in {path}/")
    else:
        # Existing repo: ensure .romyq/ is gitignored and commit the change
        # immediately so the working tree stays clean for the first run.
        if _ensure_gitignore_entry(path, ".romyq/"):
            subprocess.run(["git", "add", ".gitignore"], cwd=path, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: add .romyq/ to .gitignore"],
                cwd=path,
                capture_output=True,
            )


# ── git inspection ────────────────────────────────────────────────────────────

def git_log(path: str) -> str:
    r = subprocess.run(
        ["git", "log", "--oneline", "-20"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def git_status(path: str) -> str:
    r = subprocess.run(
        ["git", "status", "--short"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def latest_commit(path: str) -> str:
    r = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def diff_stat(path: str) -> str:
    r = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def dirty_files(path: str) -> frozenset:
    """Return the set of dirty (modified, staged, or untracked) file paths.

    Paths are relative to the repository root, matching git status --porcelain
    output.  Used to distinguish pre-existing dirty files from changes Claude
    made so the validator can restore only Claude's additions on failure.
    """
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path, capture_output=True, text=True,
    )
    files = set()
    for line in r.stdout.splitlines():
        if len(line) < 3:
            continue
        fname = line[3:].strip()
        if " -> " in fname:
            fname = fname.split(" -> ", 1)[1].strip()
        files.add(fname)
    return frozenset(files)


def inspect(path: str) -> dict:
    if not Path(path).is_dir():
        return {"git_log": "", "git_status": "", "latest_commit": "", "diff_stat": ""}
    return {
        "git_log": git_log(path),
        "git_status": git_status(path),
        "latest_commit": latest_commit(path),
        "diff_stat": diff_stat(path),
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_json(path: Path) -> dict:
    try:
        return json.loads(_read_text(path))
    except Exception:
        return {}


# ── language detection ────────────────────────────────────────────────────────

def _project_type(path: str) -> str:
    root = Path(path)
    markers = [
        ("Cargo.toml", "rust"),
        ("package.json", "node"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("go.mod", "go"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
    ]
    for filename, lang in markers:
        if (root / filename).exists():
            return lang
    return "unknown"


# ── technology detection ──────────────────────────────────────────────────────

_NODE_FRAMEWORKS: dict[str, str] = {
    # meta-frameworks first (more specific)
    "next": "Next.js",
    "nuxt": "Nuxt",
    "remix": "@remix-run/react",
    "@sveltejs/kit": "SvelteKit",
    "astro": "Astro",
    # UI frameworks
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "solid-js": "Solid",
    # backend
    "express": "Express",
    "fastify": "Fastify",
    "koa": "Koa",
    "@nestjs/core": "NestJS",
    "hono": "Hono",
    # ORM / DB
    "prisma": "Prisma",
    "drizzle-orm": "Drizzle",
    "sequelize": "Sequelize",
    "typeorm": "TypeORM",
    "mongoose": "Mongoose",
    "knex": "Knex",
}

_NODE_TEST: dict[str, str] = {
    "jest": "Jest",
    "vitest": "Vitest",
    "mocha": "Mocha",
    "ava": "Ava",
    "@playwright/test": "Playwright",
    "cypress": "Cypress",
}

_PY_FRAMEWORKS: dict[str, str] = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "starlette": "Starlette",
    "litestar": "Litestar",
    "aiohttp": "aiohttp",
    "tornado": "Tornado",
    "bottle": "Bottle",
    "sqlalchemy": "SQLAlchemy",
    "sqlmodel": "SQLModel",
    "alembic": "Alembic",
    "pydantic": "Pydantic",
    "celery": "Celery",
    "arq": "arq",
    "typer": "Typer",
    "click": "Click",
    "rich": "Rich",
    "httpx": "HTTPX",
}

_PY_TEST: dict[str, str] = {
    "pytest": "pytest",
    "hypothesis": "Hypothesis",
    "behave": "behave",
}

_RUST_FRAMEWORKS: dict[str, str] = {
    "actix-web": "Actix Web",
    "axum": "Axum",
    "warp": "Warp",
    "rocket": "Rocket",
    "tokio": "Tokio",
    "serde": "Serde",
    "sqlx": "SQLx",
    "diesel": "Diesel",
    "sea-orm": "SeaORM",
}

_GO_FRAMEWORKS: dict[str, str] = {
    "github.com/gin-gonic/gin": "Gin",
    "github.com/labstack/echo": "Echo",
    "github.com/gofiber/fiber": "Fiber",
    "github.com/go-chi/chi": "Chi",
    "github.com/gorilla/mux": "Gorilla Mux",
    "gorm.io/gorm": "GORM",
    "github.com/uptrace/bun": "Bun",
}


def _scan_text_for(text: str, mapping: dict[str, str]) -> list[str]:
    """Find which keys from mapping appear in text (word-boundary match)."""
    found = []
    text_lower = text.lower()
    for key, label in mapping.items():
        pattern = r'\b' + re.escape(key.lower()) + r'\b'
        if re.search(pattern, text_lower):
            found.append(label)
    return found


def _node_info(root: Path) -> tuple[list[str], str | None, list[str]]:
    """Returns (frameworks, test_framework, tools)."""
    pkg = _read_json(root / "package.json")
    if not pkg:
        return [], None, []

    all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    dep_text = " ".join(all_deps.keys())

    frameworks: list[str] = []
    seen: set[str] = set()
    for key, label in _NODE_FRAMEWORKS.items():
        if key in all_deps and label not in seen:
            frameworks.append(label)
            seen.add(label)

    if "typescript" in all_deps or (root / "tsconfig.json").exists():
        frameworks.insert(0, "TypeScript")

    test_fw = None
    for key, label in _NODE_TEST.items():
        if key in all_deps:
            test_fw = label
            break

    tools = []
    for tool in ("eslint", "prettier", "vite", "webpack", "esbuild", "rollup"):
        if tool in all_deps:
            tools.append(tool)

    return frameworks, test_fw, tools


def _python_info(root: Path) -> tuple[list[str], str | None, list[str]]:
    """Returns (frameworks, test_framework, tools)."""
    dep_text = ""
    for fname in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.cfg", "setup.py"):
        dep_text += _read_text(root / fname) + "\n"

    frameworks = _scan_text_for(dep_text, _PY_FRAMEWORKS)

    test_fw = None
    for key, label in _PY_TEST.items():
        if re.search(r'\b' + re.escape(key) + r'\b', dep_text, re.IGNORECASE):
            test_fw = label
            break
    if test_fw is None and any((root / d).is_dir() for d in ("tests", "test")):
        # pytest is the de-facto default even without explicit dep listing
        test_fw = "pytest"

    tools = []
    for tool in ("black", "ruff", "mypy", "flake8", "isort", "bandit", "pylint"):
        if re.search(r'\b' + re.escape(tool) + r'\b', dep_text, re.IGNORECASE):
            tools.append(tool)

    return frameworks, test_fw, tools


def _rust_info(root: Path) -> tuple[list[str], str | None, list[str]]:
    cargo_text = _read_text(root / "Cargo.toml")
    frameworks = _scan_text_for(cargo_text, _RUST_FRAMEWORKS)
    return frameworks, None, []


def _go_info(root: Path) -> tuple[list[str], str | None, list[str]]:
    mod_text = _read_text(root / "go.mod")
    frameworks = []
    for path, label in _GO_FRAMEWORKS.items():
        if path in mod_text:
            frameworks.append(label)
    return frameworks, None, []


# ── test suite detection ──────────────────────────────────────────────────────

def _detect_test_suite(root: Path) -> str:
    dirs = [d + "/" for d in ("tests", "test", "__tests__", "spec") if (root / d).is_dir()]
    configs = [f for f in (
        "pytest.ini", "jest.config.js", "jest.config.ts", "vitest.config.ts",
        "vitest.config.js", ".mocharc.js", ".mocharc.yml", "cypress.config.ts",
    ) if (root / f).exists()]
    parts = []
    if dirs:
        parts.append(f"dirs: {', '.join(dirs)}")
    if configs:
        parts.append(f"config: {', '.join(configs)}")
    return "  |  ".join(parts) if parts else ""


# ── build command detection ───────────────────────────────────────────────────

def _makefile_targets(root: Path) -> list[str]:
    text = _read_text(root / "Makefile")
    if not text:
        return []
    targets = []
    for line in text.splitlines():
        m = re.match(r'^([a-zA-Z][a-zA-Z0-9_-]*):', line)
        if m and not m.group(1).startswith("."):
            targets.append(f"make {m.group(1)}")
    return targets[:12]


def _npm_scripts(root: Path) -> list[str]:
    pkg = _read_json(root / "package.json")
    scripts = pkg.get("scripts", {})
    mgr = "pnpm" if (root / "pnpm-lock.yaml").exists() else (
        "yarn" if (root / "yarn.lock").exists() else "npm run"
    )
    return [f"{mgr} {name}" for name in list(scripts.keys())[:12]]


def _detect_build_commands(root: Path, lang: str) -> list[str]:
    cmds: list[str] = []
    cmds += _makefile_targets(root)
    cmds += _npm_scripts(root)
    if lang == "rust":
        cmds += ["cargo build", "cargo test", "cargo clippy", "cargo run"]
    if lang == "go":
        cmds += ["go build ./...", "go test ./...", "go vet ./..."]
    if lang == "python":
        cmds += ["pytest"]
        if (root / "pyproject.toml").exists():
            text = _read_text(root / "pyproject.toml")
            # pick up any defined scripts
            for m in re.finditer(r'\[project\.scripts\].*?\n(.*?)(?=\[|\Z)', text, re.DOTALL):
                for line in m.group(1).splitlines():
                    if "=" in line:
                        script = line.split("=")[0].strip()
                        if script:
                            cmds.append(script)
    return cmds


# ── branch detection ──────────────────────────────────────────────────────────

def _detect_branches(path: str) -> list[str]:
    r = subprocess.run(
        ["git", "branch", "--list"],
        cwd=path, capture_output=True, text=True,
    )
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


# ── entry point detection ─────────────────────────────────────────────────────

_ENTRY_CANDIDATES = [
    "main.py", "app.py", "server.py", "run.py", "manage.py",
    "src/main.py", "src/app.py", "src/server.py",
    "index.js", "index.ts", "server.js", "server.ts",
    "src/index.js", "src/index.ts", "src/main.ts", "src/app.ts",
    "main.go", "cmd/main.go",
    "src/main.rs", "src/lib.rs",
]


def _detect_entry_points(root: Path) -> list[str]:
    return [c for c in _ENTRY_CANDIDATES if (root / c).exists()]


# ── source structure ──────────────────────────────────────────────────────────

_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build",
    ".venv", "venv", "target", ".next", ".nuxt", "coverage",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

_DIR_LABELS: dict[str, str] = {
    "tests": "tests", "test": "tests", "__tests__": "tests", "spec": "tests",
    "docs": "docs", "doc": "docs", "documentation": "docs",
    "migrations": "migrations", "alembic": "migrations",
    "scripts": "scripts", "bin": "scripts", "tools": "scripts",
    "config": "config", "configs": "config", "conf": "config",
    "src": "source", "lib": "source", "app": "source",
    "pkg": "source", "cmd": "source", "internal": "source",
    "api": "api", "routes": "routes", "handlers": "handlers",
    "models": "models", "schemas": "schemas", "db": "database",
    "static": "static", "public": "static", "assets": "static",
    "templates": "templates", "views": "views",
}


def _annotated_dirs(root: Path) -> list[str]:
    result = []
    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith(".") or item.name in _SKIP_DIRS:
            continue
        if (item / "__init__.py").exists():
            result.append(f"{item.name}/  [python package]")
        elif item.name.lower() in _DIR_LABELS:
            result.append(f"{item.name}/  [{_DIR_LABELS[item.name.lower()]}]")
        else:
            result.append(f"{item.name}/")
    return result


# ── main profile ──────────────────────────────────────────────────────────────

def detect(path: str) -> dict:
    """Return structured detection results for a workspace.

    Keys: language, frameworks, test_framework, test_detail, dev_tools,
          build_commands, branches, entry_points, structure, root_files.
    Returns an empty dict if the path does not exist.
    """
    root = Path(path)
    if not root.is_dir():
        return {}

    lang = _project_type(path)

    if lang == "node":
        frameworks, test_fw, tools = _node_info(root)
    elif lang == "python":
        frameworks, test_fw, tools = _python_info(root)
    elif lang == "rust":
        frameworks, test_fw, tools = _rust_info(root)
    elif lang == "go":
        frameworks, test_fw, tools = _go_info(root)
    else:
        frameworks, test_fw, tools = [], None, []

    return {
        "language": lang,
        "frameworks": frameworks,
        "test_framework": test_fw,
        "test_detail": _detect_test_suite(root),
        "dev_tools": tools,
        "build_commands": _detect_build_commands(root, lang),
        "branches": _detect_branches(path),
        "entry_points": _detect_entry_points(root),
        "structure": _annotated_dirs(root),
        "root_files": [name for name in ROOT_FILES if (root / name).exists()],
    }


def profile(path: str) -> str:
    d = detect(path)
    if not d:
        return "Workspace does not exist."

    lines: list[str] = []

    lines.append(f"Language: {d['language']}")
    if d["frameworks"]:
        lines.append(f"Frameworks/Libraries: {', '.join(d['frameworks'])}")
    if d["dev_tools"]:
        lines.append(f"Dev Tools: {', '.join(d['dev_tools'])}")

    test_fw = d["test_framework"]
    suite_detail = d["test_detail"]
    if test_fw and suite_detail:
        lines.append(f"Test Suite: {test_fw}  |  {suite_detail}")
    elif test_fw:
        lines.append(f"Test Suite: {test_fw}")
    elif suite_detail:
        lines.append(f"Test Suite: {suite_detail}")
    else:
        lines.append("Test Suite: none detected")

    if d["build_commands"]:
        lines.append(f"Build Commands: {', '.join(d['build_commands'])}")
    if d["branches"]:
        lines.append(f"Active Branches: {', '.join(d['branches'])}")
    if d["entry_points"]:
        lines.append(f"Entry Points: {', '.join(d['entry_points'])}")

    if d["structure"]:
        lines.append("Structure:")
        for item in d["structure"]:
            lines.append(f"  {item}")
    if d["root_files"]:
        lines.append(f"Root Files: {', '.join(d['root_files'])}")

    return "\n".join(lines)
