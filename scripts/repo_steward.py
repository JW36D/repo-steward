#!/usr/bin/env python3
"""Bounded, dependency-free navigation and file-lifecycle checks for small repos."""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

POLICY = ".repo-policy.json"
ROLES = ("source", "test", "config", "asset", "docs", "notebook", "data", "checkpoint", "output", "temporary")
PATHS = {
    "source": ["src/**", "lib/**", "scripts/**", "tools/**", "examples/**"],
    "test": ["tests/**", "test/**", "**/test_*.py", "**/*_test.py"],
    "config": ["configs/**", "config/**", "**/pyproject.toml", "**/requirements*.txt", "**/environment*.yml", "**/environment*.yaml"],
    "asset": ["assets/**", "robots/**", "scenes/**", "urdf/**", "meshes/**"],
    "docs": ["docs/**", "doc/**", "**/*.md", "**/*.rst"],
    "notebook": ["notebooks/**", "**/*.ipynb"],
    "data": ["data/**", "datasets/**", "recordings/**", "bags/**"],
    "checkpoint": ["checkpoints/**", "weights/**", "pretrained/**"],
    "output": ["outputs/**", "runs/**", "logs/**", "results/**", "videos/**", "wandb/**", "mlruns/**", "build/**", "dist/**"],
    "temporary": [".scratch/**", ".tmp/**", "tmp/**"],
}
PYTHON_PATHS = {"source": ["models/**", "policies/**", "algorithms/**", "envs/**", "launch/**"]}
ROOT_DEFAULTS = [
    "README*", "LICENSE*", "COPYING*", "NOTICE*", "CITATION*", "CONTRIBUTING*", "CHANGELOG*",
    "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", POLICY, ".gitignore", ".gitattributes", ".gitmodules",
    ".github", ".agents", ".claude", ".cursor", ".vscode", ".editorconfig", ".pre-commit-config.yaml",
    "src", "lib", "include", "scripts", "tools", "examples", "tests", "test", "docs", "doc", "config", "configs",
    "assets", "robots", "scenes", "urdf", "meshes", "data", "datasets", "recordings", "bags", "checkpoints", "weights",
    "pretrained", "outputs", "runs", "logs", "results", "videos", "wandb", "mlruns", "build", "dist", ".scratch", ".tmp", "tmp",
    "third_party", "external", "vendor", "Makefile", "Dockerfile*", "compose*.yml", "compose*.yaml", ".dockerignore",
]
PYTHON_ROOTS = [
    "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "environment*.yml", "environment*.yaml",
    "uv.lock", "poetry.lock", "pdm.lock", "Pipfile*", "conda-lock*", "pytest.ini", "tox.ini", ".python-version",
    "train.py", "eval.py", "evaluate.py", "main.py", "demo.py", "models", "policies", "algorithms", "envs",
    "notebooks", "launch", "package.xml", "CMakeLists.txt", "resource", "MANIFEST.in",
]
OPAQUE = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "data", "datasets", "recordings", "bags", "checkpoints", "weights", "pretrained", "outputs", "runs", "logs", "results",
    "videos", "wandb", "mlruns", "build", "dist", "third_party", "external", "vendor", ".scratch", ".tmp", "tmp",
}
ENV_DIRS = {".venv", "venv", "node_modules"}
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache"}
HARD_OPAQUE = ENV_DIRS | CACHE_DIRS | {"third_party", "external", "vendor", ".scratch", ".tmp"}
CHECKPOINT_EXTS = {".pt", ".pth", ".ckpt", ".safetensors", ".onnx"}
DATA_EXTS = {".h5", ".hdf5", ".parquet", ".bag", ".db3", ".mcap", ".tfrecord"}
SOURCE_EXTS = {".py", ".pyi", ".c", ".cc", ".cpp", ".cu", ".h", ".hpp", ".rs", ".js", ".jsx", ".ts", ".tsx", ".sh", ".sql"}
ASSET_EXTS = {".urdf", ".xacro", ".mjcf", ".usd", ".usda", ".usdc", ".obj", ".stl"}
RULES = {"tracked-payload", "payload-location", "scratch-location", "root-entry", "broken-local-link", "large-file", "missing-readme", "link-check-skipped"}
SCRATCH_NAME = re.compile(r"^(?:tmp[_-]|temp[_-]|debug[_-]|scratch[_-])|(?:\.bak|\.orig|~)$", re.I)
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+[^)\n]*)?\)")


class StewardError(Exception):
    pass


@lru_cache(maxsize=16384)
def _match(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return _match(parts, pattern[1:]) or bool(parts and _match(parts[1:], pattern))
    return bool(parts and fnmatch.fnmatchcase(parts[0], pattern[0]) and _match(parts[1:], pattern[1:]))


def matches(path: str, pattern: str) -> bool:
    return _match(tuple(path.split("/")), tuple(pattern.split("/")))


def any_path(path: str, patterns: list[str]) -> bool:
    return any(matches(path, p) for p in patterns)


def valid_path(value: object, *, pattern: bool = True) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 512 and not value.startswith("/")
            and "\\" not in value and all(p not in ("", ".", "..") for p in value.split("/"))
            and not any(ord(c) < 32 for c in value)
            and (pattern or not any(c in value for c in "*?[]")))


def load_policy(root: Path) -> dict:
    path = root / POLICY
    if path.is_symlink():
        raise StewardError("Policy must not be a symlink.")
    if not path.exists():
        return {}
    if path.stat().st_size > 128 * 1024:
        raise StewardError("Policy exceeds 128 KiB.")
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise StewardError(f"Cannot read policy: {exc}") from exc
    if not isinstance(policy, dict) or set(policy) - {"schema_version", "profile", "root_entries", "paths", "exceptions"}:
        raise StewardError("Policy must be an object with known fields only.")
    if type(policy.get("schema_version")) is not int or policy["schema_version"] != 1:
        raise StewardError("Policy schema_version must be 1.")
    if policy.get("profile") not in ("generic", "python-research"):
        raise StewardError("Policy profile must be generic or python-research.")
    roots = policy.get("root_entries", [])
    if not isinstance(roots, list) or not all(valid_path(x) and "/" not in x for x in roots):
        raise StewardError("root_entries must contain root basenames or basename globs.")
    paths = policy.get("paths", {})
    if not isinstance(paths, dict) or set(paths) - set(ROLES):
        raise StewardError("paths contains an unknown role.")
    for patterns in paths.values():
        if not isinstance(patterns, list) or not all(valid_path(p) for p in patterns):
            raise StewardError("Each paths role must contain safe root-relative glob strings.")
    seen = set()
    exceptions = policy.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise StewardError("exceptions must be a list.")
    for item in exceptions:
        if (not isinstance(item, dict) or set(item) != {"rule", "path", "reason"}
                or not isinstance(item["rule"], str) or item["rule"] not in RULES
                or not valid_path(item["path"], pattern=False)
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise StewardError("Each exception needs a known rule, an exact safe path, and a reason.")
        key = item["rule"], item["path"]
        if key in seen:
            raise StewardError("Duplicate policy exception.")
        seen.add(key)
    return policy


def git(root: Path, *args: str, optional: bool = False) -> bytes | None:
    try:
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True,
                                timeout=15, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        if optional:
            return None
        raise StewardError(f"Git unavailable or timed out: {exc}") from exc
    if result.returncode:
        if optional:
            return None
        raise StewardError("Git command failed: " + result.stderr.decode(errors="replace").strip()[:500])
    return result.stdout


def git_root(root: Path) -> bool:
    output = git(root, "rev-parse", "--show-toplevel", optional=True)
    return output is not None and Path(os.fsdecode(output).strip()).resolve() == root


def git_paths(raw: bytes) -> set[str]:
    return {os.fsdecode(p) for p in raw.split(b"\0") if p}


def profile_for(root: Path, policy: dict, requested: str) -> str:
    if requested != "auto":
        return requested
    if policy:
        return policy["profile"]
    try:
        with os.scandir(root) as items:
            for i, item in enumerate(items):
                if i >= 200:
                    break
                if item.name.endswith(".py") or any(fnmatch.fnmatchcase(item.name, x) for x in ("pyproject.toml", "requirements*.txt", "environment*.y*ml", "setup.cfg")):
                    return "python-research"
                if (item.is_dir(follow_symlinks=False) and item.name not in ENV_DIRS | CACHE_DIRS | {".git"}
                        and python_directory(Path(item.path))):
                    return "python-research"
    except OSError:
        pass
    return "generic"


def python_directory(path: Path) -> bool:
    try:
        with os.scandir(path) as items:
            for i, item in enumerate(items):
                if i >= 100:
                    break
                if item.name.endswith((".py", ".pyi")) and item.is_file(follow_symlinks=False):
                    return True
    except OSError:
        pass
    return False


def safe_file(root: Path, relative: str) -> Path | None:
    """Never read through a symlink, including symlinked ancestors."""
    if not valid_path(relative):
        return None
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            return None
    return current


def inventory(root: Path, limit: int, is_git: bool, paths: dict) -> tuple[dict[str, dict], set[str], list[str], bool]:
    records: dict[str, dict] = {}
    opaque: set[str] = set()
    notes: list[str] = []
    complete = True
    stack = [root]
    visited = 0
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as items:
                for item in items:
                    if item.name == ".git":
                        continue
                    visited += 1
                    if visited > limit:
                        notes.append(f"Inventory limit {limit} reached; increase --max-entries or narrow --root.")
                        complete = False
                        stack.clear()
                        break
                    rel = (directory / item.name).relative_to(root).as_posix()
                    is_dir = item.is_dir(follow_symlinks=False)
                    link = item.is_symlink()
                    record = {"path": rel, "directory": is_dir, "symlink": link, "tracked": False, "opaque": False, "size": 0}
                    records[rel] = record
                    if is_dir:
                        skip = item.name in OPAQUE or any(any_path(rel, paths[role]) for role in ("data", "checkpoint", "output", "temporary"))
                        if skip and item.name not in HARD_OPAQUE and python_directory(Path(item.path)):
                            skip = False
                        if skip:
                            record["opaque"] = True
                            opaque.add(rel)
                        else:
                            stack.append(Path(item.path))
                    elif not link:
                        record["size"] = item.stat(follow_symlinks=False).st_size
        except OSError as exc:
            notes.append(f"Cannot inspect {directory.relative_to(root).as_posix()}: {exc}")
            complete = False
    if is_git:
        tracked = git_paths(git(root, "ls-files", "--cached", "-z") or b"")
        for i, rel in enumerate(sorted(tracked)):
            if i >= limit:
                notes.append("Tracked index exceeds inventory limit.")
                complete = False
                break
            if rel in records:
                records[rel]["tracked"] = True
                continue
            path = safe_file(root, rel)
            if path is None or not path.exists():
                continue
            records[rel] = {"path": rel, "directory": False, "symlink": False, "tracked": True,
                            "opaque": any(rel.startswith(p + "/") for p in opaque), "size": 0}
    return records, opaque, notes, complete


def role_for(path: str, paths: dict[str, list[str]]) -> str:
    parts = PurePosixPath(path).parts
    suffix = PurePosixPath(path).suffix.lower()
    if any(p in ENV_DIRS for p in parts):
        return "environment"
    if any(p in CACHE_DIRS for p in parts) or suffix == ".pyc":
        return "cache"
    if any_path(path, paths["temporary"]):
        return "temporary"
    if suffix in CHECKPOINT_EXTS:
        return "checkpoint"
    if suffix in DATA_EXTS:
        return "data"
    if PurePosixPath(path).name.startswith("events.out.tfevents") or suffix == ".log":
        return "output"
    if any_path(path, paths["test"]):
        return "test"
    if suffix in SOURCE_EXTS and any_path(path, paths["source"]):
        return "source"
    if any_path(path, paths["output"]):
        return "output"
    if any_path(path, paths["checkpoint"]):
        return "checkpoint"
    if any_path(path, paths["notebook"]):
        return "notebook"
    if suffix in {".md", ".rst"}:
        return "docs"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml"}:
        return "asset" if any_path(path, paths["asset"]) else "config"
    if suffix in SOURCE_EXTS or any_path(path, paths["source"]):
        return "source"
    for role in ("data", "asset", "config", "docs"):
        if any_path(path, paths[role]):
            return role
    if suffix in ASSET_EXTS:
        return "asset"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml"}:
        return "config"
    return "other"


def changed_paths(root: Path, base: str | None) -> tuple[set[str], set[str], str]:
    if base and (base.startswith("-") or "\0" in base):
        raise StewardError("Invalid base reference.")
    resolved = git(root, "rev-parse", "--verify", "--end-of-options", (base or "HEAD") + "^{commit}", optional=base is None)
    if resolved:
        commit = resolved.decode().strip()
        changed = git_paths(git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", commit, "--") or b"")
        deleted = git_paths(git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "--diff-filter=D", "-z", commit, "--") or b"")
    else:
        changed = git_paths(git(root, "ls-files", "--cached", "-z") or b"")
        deleted = set()
    untracked = git_paths(git(root, "ls-files", "--others", "--exclude-standard", "--directory", "-z") or b"")
    return changed | untracked, deleted, "diff:" + (base or "HEAD")


def in_scope(path: str, changed: set[str] | None) -> bool:
    return changed is None or path in changed or any(p.endswith("/") and path.startswith(p) for p in changed)


def markdown_targets(text: str, document: str) -> list[tuple[str, str]]:
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            token, rest = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not rest.strip():
                fence = None
            continue
        if fence is None:
            lines.append(line)
    targets = []
    for match in INLINE_LINK.finditer("\n".join(lines)):
        raw = match.group(1).strip("<>")
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        local = unquote(parsed.path)
        target = posixpath.normpath(local.lstrip("/") if local.startswith("/") else posixpath.join(posixpath.dirname(document), local))
        if target == ".." or target.startswith("../") or "\0" in target:
            continue
        targets.append((raw, target))
    return targets


def findings_for(root: Path, records: dict[str, dict], paths: dict, policy: dict, profile: str,
                 changed: set[str] | None, deleted: set[str]) -> list[dict]:
    findings = []
    exceptions = {(x["rule"], x["path"]) for x in policy.get("exceptions", [])}

    def add(rule: str, severity: str, path: str, message: str) -> None:
        if (rule, path) not in exceptions:
            findings.append({"rule": rule, "severity": severity, "path": path, "message": message})

    allowed = ROOT_DEFAULTS + (PYTHON_ROOTS if profile == "python-research" else []) + policy.get("root_entries", [])
    for path, item in sorted(records.items()):
        role = item["role"]
        selected = in_scope(path, changed)
        top = path.split("/")[0]
        if selected:
            if not any(fnmatch.fnmatchcase(top, pattern) for pattern in allowed):
                add("root-entry", "warning", top, "Unrecorded root entry; assign its responsibility or record the existing convention.")
            if not item["directory"]:
                fixture = any_path(path, ["tests/fixtures/**", "test/fixtures/**", "**/tests/fixtures/**"])
                if item["tracked"] and role in {"checkpoint", "data", "output", "temporary", "environment", "cache"} and not fixture:
                    add("tracked-payload", "error", path, f"Tracked {role} file; verify whether this is an intentional maintained input and record an exact exception if needed.")
                if role in {"checkpoint", "data", "output"} and not fixture and not any_path(path, paths[role]):
                    add("payload-location", "warning", path, f"Possible {role} payload outside its recorded area; inspect its role and location.")
                if SCRATCH_NAME.search(PurePosixPath(path).name) and role != "temporary":
                    add("scratch-location", "warning", path, "Possible debug/backup material outside the temporary area; inspect its ongoing purpose.")
                if item["size"] > 10 * 1024 * 1024:
                    add("large-file", "warning", path, "File exceeds 10 MiB; review version-control and deliverable placement.")
        if (item["directory"] or item["opaque"] or item["symlink"]
                or not path.lower().endswith(".md") or (not selected and not deleted)):
            continue
        document = safe_file(root, path)
        try:
            if document is None or document.stat().st_size > 256 * 1024:
                if selected:
                    add("link-check-skipped", "warning", path, "Markdown link check skipped: symlink or file above 256 KiB.")
                continue
            text = document.read_text(encoding="utf-8")
            for raw, target in markdown_targets(text, path):
                if not selected and target not in deleted:
                    continue
                target_path = safe_file(root, target)
                if target_path is not None and not target_path.exists():
                    add("broken-local-link", "error", path, f"Missing local target: {raw}")
        except (OSError, UnicodeError, ValueError) as exc:
            if selected:
                add("link-check-skipped", "warning", path, f"Cannot check Markdown links: {exc}")
    if not any("/" not in p and PurePosixPath(p).name.lower().startswith("readme") for p in records):
        add("missing-readme", "warning", "README.md", "Add or restore a human entrypoint with real commands and module locations.")
    unique = {(x["rule"], x["path"], x["message"]): x for x in findings}
    return sorted(unique.values(), key=lambda x: (x["severity"] != "error", x["path"], x["rule"]))


ALIASES = {
    "config": "config", "配置": "config", "data": "data", "数据": "data", "weights": "checkpoint", "权重": "checkpoint",
    "output": "output", "输出": "output", "docs": "docs", "文档": "docs", "source": "source", "源码": "source",
    "temporary": "temporary", "临时": "temporary", "notebook": "notebook", "asset": "asset", "资产": "asset", "test": "test",
}


def report(args: argparse.Namespace) -> tuple[dict, int]:
    supplied = Path(args.root).expanduser()
    if supplied.is_symlink() or any(p.is_symlink() for p in supplied.absolute().parents):
        raise StewardError("Project root must not use a symlink path.")
    root = supplied.resolve()
    if not root.is_dir():
        raise StewardError("Project root is not an existing directory.")
    policy = load_policy(root)
    profile = profile_for(root, policy, args.profile)
    is_git = git_root(root)
    paths = {role: PATHS[role] + (PYTHON_PATHS.get(role, []) if profile == "python-research" else [])
             + policy.get("paths", {}).get(role, []) for role in ROLES}
    records, opaque, notes, complete = inventory(root, args.max_entries, is_git, paths)
    for item in records.values():
        item["role"] = role_for(item["path"], paths)
    result = {"version": "0.1.0", "root": str(root), "profile": profile, "git": is_git,
              "complete": complete, "scope": "repository" if is_git else "directory", "notes": notes}
    if args.command == "init":
        if policy:
            raise StewardError("A policy already exists; inspect and edit it rather than reinitializing.")
        packages = sorted(p for p, item in records.items() if "/" not in p and item["directory"] and not item["opaque"] and (root / p / "__init__.py").is_file())
        proposed = {"schema_version": 1, "profile": profile,
                    "root_entries": sorted(p for p in records if "/" not in p),
                    "paths": {"source": [p + "/**" for p in packages]} if packages else {}, "exceptions": []}
        result.update({"policy": proposed, "written": False})
        if args.write:
            if not complete:
                raise StewardError("Refusing to initialize from an incomplete inventory.")
            try:
                with (root / POLICY).open("x", encoding="utf-8") as out:
                    json.dump(proposed, out, ensure_ascii=False, indent=2)
                    out.write("\n")
            except FileExistsError as exc:
                raise StewardError("Refusing to overwrite an existing policy.") from exc
            result["written"] = True
        return result, 0 if complete else 2
    if args.command == "locate":
        query = args.query.casefold()
        role = ALIASES.get(query)
        tokens = [query]
        if query in ("train", "训练"):
            tokens = ["train", "learn"]
        elif query in ("eval", "评估"):
            tokens = ["eval", "benchmark", "test"]
        found = [item for path, item in sorted(records.items())
                 if (role and item["role"] == role) or any(token in path.casefold() for token in tokens)]
        result.update({"matches": found[:100], "match_count": len(found)})
        return result, 2 if not complete else (0 if found else 1)
    changed, deleted = None, set()
    if args.command == "check":
        if not is_git:
            raise StewardError("check requires a Git worktree root; use audit for a non-Git directory.")
        changed, deleted, result["scope"] = changed_paths(root, args.base)
        if POLICY in changed:
            changed = None
            result["scope"] += " (policy changed: full inventory)"
        result["changed_paths"] = sorted(changed) if changed is not None else ["*"]
    findings = findings_for(root, records, paths, policy, profile, changed, deleted)
    if not complete:
        findings.append({"rule": "scan-incomplete", "severity": "warning", "path": ".", "message": "Inventory is incomplete; this result is not a complete pass."})
    result.update({"role_counts": dict(sorted(Counter(x["role"] for x in records.values()).items())),
                   "opaque_paths": sorted(opaque), "entrypoints": sorted(p for p in records if "/" not in p and not records[p]["directory"] and (p.lower().startswith("readme") or p in {"train.py", "eval.py", "evaluate.py", "main.py", "demo.py", "pyproject.toml", "setup.py"})),
                   "findings": findings})
    failure = any(x["severity"] == "error" or getattr(args, "strict", False) for x in findings)
    code = 2 if not complete else (1 if args.command == "check" and failure else 0)
    return result, code


def display(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return
    if "error" in result:
        print("ERROR: " + result["error"])
        return
    print(f"Root: {result['root']}\nProfile: {result['profile']} | Scope: {result['scope']} | Complete: {result['complete']}")
    if "policy" in result:
        print(("Created " if result["written"] else "Preview of ") + POLICY)
        print(json.dumps(result["policy"], ensure_ascii=False, indent=2))
    elif "matches" in result:
        for item in result["matches"]:
            tag = " [symlink, not followed]" if item["symlink"] else (" [opaque boundary]" if item["opaque"] else "")
            print(f"{item['role']:12} {item['path']}{tag}")
        print(f"Matches: {result['match_count']} (showing up to 100)")
    else:
        print("Roles: " + ", ".join(f"{k}={v}" for k, v in result["role_counts"].items()))
        print("Entrypoints: " + (", ".join(result["entrypoints"]) or "none recognized"))
        if result["opaque_paths"]:
            print("Opaque boundaries (contents not scanned): " + ", ".join(result["opaque_paths"]))
        for item in result["findings"]:
            print(f"{item['severity'].upper():7} {item['rule']} {item['path']}: {item['message']}")
        print(f"Findings: {len(result['findings'])}")
    for note in result["notes"]:
        print("NOTE: " + note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("audit", "init", "check", "locate"):
        sub = commands.add_parser(command)
        sub.add_argument("--root", default=".", help="Intended project root")
        sub.add_argument("--profile", choices=("auto", "generic", "python-research"), default="auto")
        sub.add_argument("--max-entries", type=int, default=10000)
        sub.add_argument("--json", action="store_true")
        if command == "init":
            sub.add_argument("--write", action="store_true", help="Create policy exclusively; default is preview")
        if command == "check":
            sub.add_argument("--base", help="Compare tracked changes against this commit/ref (default HEAD)")
            sub.add_argument("--strict", action="store_true", help="Also fail on warnings")
        if command == "locate":
            sub.add_argument("query")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.max_entries <= 1000000:
            raise StewardError("--max-entries must be between 1 and 1000000.")
        result, code = report(args)
    except (StewardError, OSError) as exc:
        result, code = {"error": str(exc)}, 2
    display(result, args.json)
    return code


if __name__ == "__main__":
    sys.exit(main())
