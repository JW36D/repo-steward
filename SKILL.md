---
name: repo-steward
description: Keep small research repositories easy to navigate during reproduction and algorithm development. Use when initializing project conventions, adding modules or experiments, deciding where files belong, auditing clutter, finding project entrypoints, or preparing a clean handoff. Includes a Python research adapter for embodied AI, simulation, datasets, checkpoints, and experiment outputs. Apply the relevant placement and closeout steps alongside development; ordinary edits do not require a full audit.
metadata:
  version: "0.1.0"
---

# Repo Steward

Make a research repository understandable without asking an AI where its files are. Preserve useful existing conventions; add only the guidance the current work needs.

## Start with the current task

- **Initialize conventions:** inspect the existing entrypoints, documentation, configuration, and Git state. Preview a policy with `init`, then write it if initialization is requested. Add a concise map and real commands to the existing README, and a short working agreement to the repository's applicable agent instructions. Reuse existing files and sections. Do not initialize unrelated directories merely because they are the current workspace.
- **Develop or reproduce:** locate the relevant module and a comparable implementation. Apply the placement rules below to new files. At closeout, run the incremental `check` when Git is available. No full-repository audit or new report is required for a routine edit.
- **Audit or organize:** run `audit`, inspect the evidence, and resolve the relevant findings. An audit request authorizes inspection; implement cleanup when the request also asks for it. Verify references and behavior after moves.
- **Find something:** start with the README, then `locate`. Return actual paths and their roles. The CLI searches paths, not source semantics; use a focused content search if necessary.

For Python reproduction, robotics, simulation, or algorithm experiments, read [references/python-research.md](references/python-research.md). Read [references/policy-and-cli.md](references/policy-and-cli.md) when using options, writing policy exceptions, or interpreting checks.

## Placement decisions

1. Search for an existing entrypoint or similar implementation before creating another. Reuse or extend it when the responsibilities match; avoid speculative abstractions and an arbitrary second implementation.
2. Give new files a role: maintained source/test/configuration/asset, current documentation, historical decision, external input, reproducible output, or temporary work. Prefer the nearest existing module and the project's established naming. A new top-level directory needs a clear responsibility in the change explanation, not a separate approval ritual.
3. Respect framework discovery, import paths, command-line entrypoints, and upstream reproduction layouts. `models/` may contain neural-network source. Robot description files, meshes, simulator scenes, migrations, test fixtures, and generated source may be maintained inputs. Inspect their purpose before treating them as outputs.
4. Put one-off scripts and intermediate materials in the existing temporary area, or `.scratch/<task>/` if one is needed. Promote a useful script into the existing `scripts/` or `tools/` only when it has an ongoing purpose and a documented invocation.
5. Keep each current fact in one authoritative place. Update an existing guide or specification instead of creating `final`, `latest`, or parallel summaries. Record only consequential architecture decisions; preserve superseded decisions with their status. Git history replaces source-code backup copies.

## Human navigation and persistent rules

The existing README should answer: what this project does; where its entrypoints and main modules are; how to install, run, evaluate, and test; where data, weights, and outputs belong; and where to find further detail. Document commands that were inspected or verified, identifying unverified or hardware-dependent steps. Do not invent results or fill placeholders with guessed commands.

Update navigation only when entrypoints, module responsibilities, commands, or document locations change. Do not enumerate every file or create a report after every task. When a repository already uses specs or another documentation system, link its authoritative entrypoints.

For an initialized repository, merge a short agreement into its existing agent instructions:

```text
Use the README as the project map and preserve existing framework/upstream layout.
Before adding a file, look for an existing implementation and choose its module and role.
Keep data, checkpoints, experiment outputs, and scratch work in their documented locations.
Update navigation when entrypoints, commands, or module responsibilities change.
At closeout, inspect the task's diff and new files; verify affected references and run relevant checks.
Use repo-steward's Python research guidance when changing experiments or reproduction setup.
```

Use the host's supported skill invocation or an actual installed path when adding a pointer; do not copy this entire skill into the repository. Keep machine-checkable paths and justified exceptions in the optional `.repo-policy.json`, rather than duplicating their full lists in agent instructions.

## Close out a development task

- Review the diff and untracked files. Check affected imports, discovery rules, documentation links, and packaging when deleting or moving files. The CLI checks paths and ordinary local Markdown links; language and framework validation still comes from the project tools.
- Run the relevant existing tests or lightweight smoke checks. For expensive training, GPU/simulator jobs, dataset downloads, real hardware, or external logging, follow the user's requested scope and resource limits. A structure audit is read-only and does not launch these operations.
- Account for the temporary files created during this task. Delete only materials whose ownership and lack of continuing use are clear. Preserve files changed or used by another task. Propose treatment of older unknown leftovers; age or absence from search results alone does not establish obsolescence.
- Summarize the behavior changed, relevant paths, verification, and remaining limitations in the response. Persist a handoff only when work spans sessions and the repository lacks an adequate task record; update that record instead of adding another summary.

## Tools

Run with Python 3.10+; no third-party packages are required. Resolve `scripts/repo_steward.py` relative to this skill's actual installation directory.

```bash
python3 /absolute/path/to/repo-steward/scripts/repo_steward.py audit --root /project
python3 /absolute/path/to/repo-steward/scripts/repo_steward.py init --root /project --profile python-research
python3 /absolute/path/to/repo-steward/scripts/repo_steward.py init --root /project --profile python-research --write
python3 /absolute/path/to/repo-steward/scripts/repo_steward.py check --root /project
python3 /absolute/path/to/repo-steward/scripts/repo_steward.py check --root /project --base main
python3 /absolute/path/to/repo-steward/scripts/repo_steward.py locate train --root /project
```

`audit`, `check`, and `locate` do not modify project files. `init` previews by default; `--write` creates only a new policy, never overwrites it. The CLI never moves, deletes, trains, downloads, publishes, or executes repository code.

Checks provide guidance and detect defined violations. Skill matching and agent instructions do not guarantee interception of every write. Introduce hooks or required CI only when the project needs them. A successful check does not authorize deployment or prove experiment correctness.
