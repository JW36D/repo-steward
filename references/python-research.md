# Python research adapter

Use for small Python repositories involving paper reproduction, embodied AI, robotics, simulation, or algorithm development. Adapt the current project; do not create every directory shown here.

## Recognize the project before changing it

Inspect the README, dependency/environment manifests, relevant launch/train/eval scripts, configuration entrypoints, and existing output conventions. Determine what is upstream code, the user's algorithm change, external assets, and local experiment state. Respect repository instructions and user changes.

- Preserve upstream entrypoints and directory layout when reproduction fidelity matters. Explain the user's additions in the existing map rather than reorganizing the upstream tree.
- Recognize `pyproject.toml`, `requirements*.txt`, Conda environment files, ROS package manifests and launch directories, Hydra or similar config trees, notebooks, and simulator resources. Reuse the environment manager the repository already uses.
- Record the paper/upstream revision, necessary environment constraints, data/checkpoint source, runnable command, and expected evaluation protocol in an existing reproduction section or guide when relevant. Distinguish paper-reported metrics from locally measured metrics. Record missing evidence as unknown.
- Do not assume `models/`, `data/`, or `assets/` is disposable. They can contain Python modules, dataset loaders, URDF/Xacro/MJCF, meshes, scenes, calibration, or task definitions. The scanner skips large payload areas by default and reports their boundaries; inspect relevant source explicitly.

## File roles and placement

| Role | Prefer existing locations | Lifecycle |
| --- | --- | --- |
| Algorithm/model/policy source | Existing package, `src/`, `models/`, `policies/`, `algorithms/` | Versioned, with explicit entrypoints and focused tests |
| Train/eval/preprocess entrypoints | Existing root entrypoints, `scripts/`, `tools/` | Versioned; document invocation when useful |
| Experiment/task configuration | Existing `configs/`, `config/`, or upstream tree | Versioned, reusable settings; avoid local absolute paths |
| Robot/simulator resources | Existing `assets/`, `robots/`, `scenes/`, `launch/`, `urdf/` | Often maintained source inputs; retain provenance/licensing where relevant |
| Dataset/recording payload | Existing data storage or documented external path | Usually excluded from Git; record source/version and processing command |
| Model weights/checkpoints | Existing weight/checkpoint location | Usually excluded from Git; identify source or producing run |
| Runs, videos, TensorBoard/W&B logs, evaluation output | Existing run/output directory | Per-run output; retain useful results with a stated purpose |
| Notebooks | Existing notebooks/examples location | Keep meaningful notebooks; inspect embedded outputs before committing or sharing |
| Smoke-test inputs and golden snapshots | Existing small fixtures/snapshots | May intentionally be versioned; do not apply blanket output deletion |
| One-off debugging/probing | Existing temporary area or `.scratch/<task>/` | Review at task closeout; promote only if repeatedly useful |

Use descriptive experiment names that capture the change, such as `grasp-baseline` or `grasp-no-depth`. Existing tool-generated multirun directories are valid. Do not rename experiment directories merely for cosmetic consistency or create a hand-written parallel run database.

## Minimum reproducibility evidence

For a meaningful run, keep these facts together using the existing logger, run configuration, or a small manifest beside its output:

- Source revision and whether local changes were present; experiment/config identity.
- Exact command or launch settings, seed, and relevant environment/hardware constraints.
- Dataset/task split and checkpoint identity, using versions or existing hashes when available.
- Output location, metric names/units, and evaluation protocol.

Do not hash terabytes of data as a routine governance step. A run ID alone is insufficient if its configuration is lost. Preserve failed runs when they are needed for diagnosis; do not automatically delete runs based on age or score. Configuration snapshots produced by Hydra or logging tools are outputs, while the reusable configuration templates remain source.

## Development and verification

Choose the cheapest check that addresses the change: relevant unit tests, import checks when imports are safe, parser/config validation, a tiny CPU dataset, or an existing dry-run mode. Importing a module can itself initialize hardware or allocate resources, so inspect the entrypoint before executing it. Avoid full training as a structure test.

Training, simulator starts, external telemetry, large downloads, and real robot actions require the applicable task authorization and resource bounds. Do not infer permission for a long GPU run from a request to organize files.

Before moving a resource, check launch files, configuration references, package-data rules, relative working-directory assumptions, subprocess commands, and notebook references as applicable. Text search alone cannot establish that a resource is unused.

## Git, deliverables, and sharing

Use the existing ignore rules for local environments, caches, datasets, checkpoints, outputs, and scratch materials. `.gitignore` does not untrack committed files. Never automatically untrack or delete them; identify the conflict and its intended exception or migration.

Small test fixtures and intentionally published model assets can be valid exceptions. The policy accepts exact-path exceptions with reasons. A project using Git LFS/DVC or another asset mechanism may intentionally track pointers or metadata; inspect and document an exception rather than adding a broad exemption for every future weight file.

For a code release, use existing build/package tooling and inspect the actual archive or package contents. For a reproduction handoff, include the necessary source, configs, environment/setup instructions, evaluation command, and references to external inputs. Large payloads and experiment outputs are included only when they are part of the requested deliverable. Preserve package resources that runtime loading requires.

## Example decision

Request: add a depth ablation to an existing grasping experiment.

1. Find the current grasp policy, its configuration, and the train/eval entrypoints.
2. Extend the current configuration if it already expresses the variation. Add a separate config only if it is a reusable experiment definition.
3. Put algorithm code in the current policy/module, not a new root `grasp_v2_final.py`.
4. Put outputs in the existing run system and retain seed/config/source evidence there.
5. Update the existing reproduction guide only if its command or interpretation changes.
6. Check the diff and new files, validate configuration and the changed behavior with a small test, and explain any unexecuted GPU evaluation.
