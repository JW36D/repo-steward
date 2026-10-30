# Policy and CLI reference

The script requires Python 3.10+ and uses only the standard library. Configuration is optional. The root must be the intended project directory; Git checks use Git metadata only when this is the Git worktree root, so they do not silently inspect a parent repository.

## Commands

All commands accept `--root PATH`, `--profile auto|generic|python-research`, `--json`, and `--max-entries N` (default 10000). `auto` uses an existing policy or bounded inspection for Python project markers.

- `audit`: inspect the bounded repository inventory, report role counts, entrypoints, opaque payload directories, and findings. Read-only; returns 0 even when findings exist, or 2 for invalid input/incomplete inventory.
- `init`: preview a policy inferred from the current layout. `--write` creates `.repo-policy.json` exclusively and refuses to overwrite an existing file. It does not create folders, alter ignore rules, or edit documentation. During requested initialization, the agent updates the existing README/instructions separately using evidence from the project.
- `check`: check working-tree changes against HEAD plus non-ignored untracked files. `--base REF` compares tracked changes against a verified commit, useful for a branch/CI comparison. Include relevant unchanged Markdown files when deleted paths break their links. A changed policy triggers a whole-inventory check. Read-only.
- `locate QUERY`: case-insensitive path search and a small alias set (`train`, `eval`, `config`, `data`, `weights`, `output`, `docs`, `source`, `temporary`, and Chinese equivalents). It returns paths and roles, including opaque directory boundaries. It does not read code to infer semantics or query the model.

`check` requires Git and an actual worktree root. In an empty Git repository it checks all available files. A comparison is against the provided commit itself, not an automatically selected merge base; resolve the desired merge base with the project's existing CI setup when needed. Ignored local outputs are outside the Git-change scope; use `audit` for the local overview.

Exit codes: `check` uses 0 for no error findings, 1 for error findings, and 2 for invalid input or incomplete inventory. Warnings do not fail by default; `check --strict` also fails on warnings. `locate` returns 1 when no path matches, or 2 for incomplete inventory. JSON reports include `complete`, `scope`, and `findings`; do not treat an incomplete result as a pass.

## Optional policy

`.repo-policy.json` is this skill's configuration format, not a required ecosystem standard. JSON avoids adding a parser dependency. For example:

```json
{
  "schema_version": 1,
  "profile": "python-research",
  "root_entries": ["README.md", "pyproject.toml", "train.py", "robot_policy", "configs", "data", "runs"],
  "paths": {"source": ["robot_policy/**"]},
  "exceptions": [
    {"rule": "tracked-payload", "path": "assets/demo-policy.pt", "reason": "Published small reference weight required by the demo"}
  ]
}
```

`root_entries` adds recognized root basenames or basename globs to the profile's defaults. `init` observes existing entries to preserve the current layout; this is recognition, not certification that they are well designed. New unknown root entries produce warnings, not automatic rejection. Suspicious backup and scratch filenames still produce findings even if recognized here.

`paths` extends the default role patterns. Roles: `source`, `test`, `config`, `asset`, `docs`, `notebook`, `data`, `checkpoint`, `output`, and `temporary`. Patterns are root-relative POSIX globs: `*` matches within a segment; `**` matches zero or more segments. Do not use absolute paths, `..`, or backslashes. Declaring source/config/doc paths does not exempt tracked checkpoint or output payloads; use a justified exception if such an input is intentional.

`exceptions` suppress an exact `(rule, path)` only and require a nonempty `reason`. They do not exempt a whole directory. Use the path and rule returned by the report. Unknown fields, profiles, roles, malformed patterns, and duplicate exceptions are rejected. The policy and its parent directory must not be symlinks at load/write time.

## Checks and limits

| Finding | Default severity | Meaning |
| --- | --- | --- |
| `tracked-payload` | error | Dataset/checkpoint/output/cache payload appears tracked, outside recognized small fixture locations |
| `payload-location` | warning | A likely dataset/checkpoint/output file is outside its recorded area |
| `scratch-location` | warning | Likely one-off debug/backup file lies outside the temporary area; review its purpose |
| `root-entry` | warning | New or unknown top-level entry has no recorded place in the current policy/profile |
| `broken-local-link` | error | An ordinary inline Markdown link/image points at a missing local file |
| `large-file` | warning | A scanned file exceeds 10 MiB; check whether it belongs in the source deliverable |
| `missing-readme` | warning | No root README provides a human entrypoint |
| `scan-incomplete` | warning | The entry limit or an I/O failure prevented a complete bounded inventory |
| `link-check-skipped` | warning | A selected Markdown file could not be read within the bounded/safe checks |

The scanner never follows directory symlinks and does not read payload contents. Large data/output/environment/cache/external-source directories are represented as opaque boundaries. Direct Python source among the first 100 entries of a data/output directory makes it inspectable; environments, caches, vendor code, and `.scratch` remain opaque. Configured data/output paths are also skipped. `models/` and robot assets are not blanket-skipped. Tracked filenames inside opaque areas remain available for payload checks, without reading their contents. Source content, model tensors, dataset records, and notebook outputs are not parsed.

The Markdown check handles ordinary inline local links/images, skips fenced code, and ignores remote URLs and anchor-only links. It does not validate headings, reference-style links, HTML links, deeply nested Markdown constructs, or paths outside the repository. Files above 256 KiB and symlinked files are not read. Use an existing documentation checker when the project needs more coverage.

The tool does not establish semantic duplication, unused-code status, dependency correctness, scientific validity, or release-package completeness. It does not install hooks or CI automatically. Suggested locations and opaque boundaries are a navigation aid, not evidence that their contents are safe to remove.

## Verify the skill implementation

```bash
python3 -B -m unittest discover -s /absolute/path/to/repo-steward/tests -v
```

Tests create isolated temporary repositories and do not access datasets, GPUs, robot hardware, or project services.
