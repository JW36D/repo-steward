"""Behavioral tests use isolated fixtures and never import or execute project code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_steward.py"


class StewardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="repo-steward-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究 project"
        self.root.mkdir()
        self.write("README.md", "# Reproduction\n")

    def write(self, path, text=""):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def invoke(self, *args, root=None):
        proc = subprocess.run([sys.executable, "-B", str(SCRIPT), *args, "--root", str(root or self.root), "--json"],
                              capture_output=True, text=True, timeout=20)
        self.assertNotIn("Traceback", proc.stderr)
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"Invalid CLI JSON: {proc.stdout!r} {proc.stderr!r}")
        return proc.returncode, result

    def git(self, *args):
        if not shutil.which("git"):
            self.skipTest("git is unavailable")
        proc = subprocess.run(["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
                               "-c", "user.name=Skill Test", "-c", "user.email=skill-test@example.invalid", *args],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def init_git(self):
        self.git("init", "-q", "--initial-branch=main")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "fixture")

    def findings(self, result, rule):
        return [x for x in result["findings"] if x["rule"] == rule]

    def policy(self, **extra):
        value = {"schema_version": 1, "profile": "python-research", **extra}
        self.write(".repo-policy.json", json.dumps(value))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}

    def test_audit_detects_python_without_running_code_or_writing_reports(self):
        self.write("train.py", "raise RuntimeError('must not execute')\n")
        self.write("models/policy.py", "raise RuntimeError('must not import')\n")
        before = self.snapshot()
        code, result = self.invoke("audit")
        self.assertEqual(code, 0)
        self.assertEqual(result["profile"], "python-research")
        self.assertIn("train.py", result["entrypoints"])
        self.assertEqual(self.snapshot(), before)

    def test_init_preview_then_exclusive_write_and_no_other_changes(self):
        self.write("robot_policy/__init__.py")
        before = self.snapshot()
        code, preview = self.invoke("init")
        self.assertEqual(code, 0)
        self.assertFalse(preview["written"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(preview["policy"]["paths"]["source"], ["robot_policy/**"])
        code, written = self.invoke("init", "--write")
        self.assertEqual(code, 0)
        self.assertTrue(written["written"])
        after = self.snapshot()
        self.assertEqual(set(after) - set(before), {".repo-policy.json"})
        code, result = self.invoke("init", "--write")
        self.assertEqual(code, 2)
        self.assertIn("already exists", result["error"])
        self.assertEqual(after, self.snapshot())

    def test_models_and_robot_assets_are_not_payloads(self):
        self.init_git()
        self.write("models/policy.py")
        self.write("assets/robot.urdf", "<robot/>\n")
        self.write("scenes/table.xml", "<mujoco/>\n")
        self.write("tests/fixtures/sample.h5", "small fixture")
        self.commit()
        code, result = self.invoke("audit")
        self.assertEqual(code, 0)
        self.assertFalse(self.findings(result, "tracked-payload"))
        code, result = self.invoke("locate", "source")
        self.assertEqual(code, 0)
        self.assertIn("models/policy.py", {x["path"] for x in result["matches"]})

    def test_opaque_data_does_not_expand_and_source_loaders_remain_visible(self):
        self.write("data/episode/data.h5", "payload")
        self.write("outputs/run/video.mp4", "payload")
        self.write("models/encoder.py")
        code, result = self.invoke("audit", "--max-entries", "10")
        self.assertEqual(code, 0)
        self.assertIn("data", result["opaque_paths"])
        self.assertIn("outputs", result["opaque_paths"])
        _, found = self.invoke("locate", "data")
        self.assertEqual({x["path"] for x in found["matches"]}, {"data"})
        self.write("data/loader.py")
        _, found = self.invoke("locate", "loader")
        self.assertEqual(found["matches"][0]["role"], "source")

    def test_custom_payload_area_is_not_recursively_scanned(self):
        self.policy(paths={"data": ["storage/**"]})
        self.write("storage/many/episodes/episode.h5", "payload")
        code, result = self.invoke("audit", "--max-entries", "4")
        self.assertEqual(code, 0)
        self.assertIn("storage", result["opaque_paths"])

    def test_vendor_code_and_scratch_remain_opaque_even_with_python_files(self):
        self.write("third_party/setup.py")
        self.write("third_party/big_tree/more.py")
        self.write(".scratch/debug_test.py")
        _, result = self.invoke("audit")
        self.assertIn("third_party", result["opaque_paths"])
        self.assertIn(".scratch", result["opaque_paths"])
        self.assertEqual(self.invoke("locate", "more.py")[0], 1)

    def test_nested_python_source_recognizes_research_profile(self):
        self.write("models/policy.py")
        _, result = self.invoke("audit")
        self.assertEqual(result["profile"], "python-research")
        self.assertFalse(self.findings(result, "root-entry"))

    def test_staged_checkpoint_inside_opaque_directory_fails_check(self):
        self.init_git()
        self.commit()
        self.write("checkpoints/policy.pt", "not a real model")
        self.git("add", "checkpoints/policy.pt")
        code, result = self.invoke("check")
        self.assertEqual(code, 1)
        self.assertEqual(self.findings(result, "tracked-payload")[0]["path"], "checkpoints/policy.pt")

    def test_legacy_payload_and_unrelated_broken_link_do_not_fail_incremental_check(self):
        self.init_git()
        self.write("checkpoints/legacy.pt", "old model")
        self.write("README.md", "[old](never-existed.md)\n")
        self.write("models/policy.py", "v = 1\n")
        self.commit()
        self.write("models/policy.py", "v = 2\n")
        code, result = self.invoke("check")
        self.assertEqual(code, 0)
        self.assertFalse(result["findings"])

    def test_untracked_debug_file_is_checked(self):
        self.init_git()
        self.commit()
        self.write("debug_camera.py")
        code, result = self.invoke("check")
        self.assertEqual(code, 0)
        self.assertTrue(self.findings(result, "scratch-location"))
        self.assertTrue(self.findings(result, "root-entry"))
        self.assertEqual(self.invoke("check", "--strict")[0], 1)

    def test_untracked_directory_descendants_are_checked(self):
        self.init_git()
        self.commit()
        self.write("probe/debug_sensor.py")
        _, result = self.invoke("check")
        self.assertEqual(self.findings(result, "scratch-location")[0]["path"], "probe/debug_sensor.py")

    def test_untracked_weight_in_model_source_warns_about_placement(self):
        self.init_git()
        self.commit()
        self.write("models/model.pt", "payload")
        _, result = self.invoke("check")
        self.assertEqual(self.findings(result, "payload-location")[0]["path"], "models/model.pt")

    def test_deleted_target_breaks_unchanged_readme(self):
        self.init_git()
        self.write("docs/reproduce.md", "guide\n")
        self.write("README.md", "[reproduce](docs/reproduce.md)\n")
        self.commit()
        (self.root / "docs/reproduce.md").unlink()
        code, result = self.invoke("check")
        self.assertEqual(code, 1)
        self.assertEqual(self.findings(result, "broken-local-link")[0]["path"], "README.md")

    def test_rename_breaks_unchanged_navigation_even_with_git_rename_detection(self):
        self.init_git()
        self.write("docs/old.md", "same content\n" * 10)
        self.write("README.md", "[guide](docs/old.md)\n")
        self.commit()
        self.git("mv", "docs/old.md", "docs/new.md")
        code, result = self.invoke("check")
        self.assertEqual(code, 1)
        self.assertTrue(self.findings(result, "broken-local-link"))

    def test_committed_changes_can_be_checked_against_explicit_base(self):
        self.init_git()
        self.commit()
        self.git("branch", "baseline")
        self.write("weights/bad.pt", "payload")
        self.commit()
        self.assertEqual(self.invoke("check")[0], 0)
        code, result = self.invoke("check", "--base", "baseline")
        self.assertEqual(code, 1)
        self.assertTrue(self.findings(result, "tracked-payload"))

    def test_ignored_local_outputs_are_outside_git_change_scope(self):
        self.init_git()
        self.write(".gitignore", "outputs/\n.scratch/\n")
        self.commit()
        self.write("outputs/run/metrics.json", "{}")
        self.write(".scratch/task/debug.py")
        code, result = self.invoke("check")
        self.assertEqual(code, 0)
        self.assertEqual(result["changed_paths"], [])
        self.assertFalse(result["findings"])

    def test_exact_exception_does_not_exempt_next_checkpoint(self):
        self.init_git()
        self.policy(exceptions=[{"rule": "tracked-payload", "path": "weights/intentional.pt", "reason": "reference input"}])
        self.write("weights/intentional.pt", "small")
        self.write("weights/unintended.pt", "small")
        self.git("add", "--all")
        code, result = self.invoke("check")
        self.assertEqual(code, 1)
        self.assertEqual([x["path"] for x in self.findings(result, "tracked-payload")], ["weights/unintended.pt"])

    def test_symlink_directory_is_not_followed_and_symlink_root_is_rejected(self):
        external = Path(self.temp.name) / "outside"
        external.mkdir()
        (external / "bad.md").write_text("[bad](missing.md)\n")
        (self.root / "linked").symlink_to(external, target_is_directory=True)
        _, result = self.invoke("audit")
        self.assertFalse(self.findings(result, "broken-local-link"))
        _, result = self.invoke("locate", "bad")
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(self.invoke("audit", root=self.root / "linked")[0], 2)

    def test_policy_symlink_is_rejected_without_modifying_target(self):
        external = Path(self.temp.name) / "external-policy.json"
        external.write_text("{}")
        (self.root / ".repo-policy.json").symlink_to(external)
        self.assertEqual(self.invoke("init", "--write")[0], 2)
        self.assertEqual(external.read_text(), "{}")

    def test_truncation_is_not_a_pass_and_does_not_write_policy(self):
        self.init_git()
        self.write("train.py")
        code, result = self.invoke("check", "--max-entries", "1")
        self.assertEqual(code, 2)
        self.assertFalse(result["complete"])
        self.assertTrue(self.findings(result, "scan-incomplete"))
        self.assertEqual(self.invoke("init", "--write", "--max-entries", "1")[0], 2)
        self.assertFalse((self.root / ".repo-policy.json").exists())

    def test_markdown_link_scope_and_encoded_filenames(self):
        self.write("docs/run guide.md", "text")
        self.write("README.md", "[ok](docs/run%20guide.md)\n[remote](https://example.invalid/a)\n[anchor](#intro)\n```md\n[example](not-real.md)\n```\n")
        _, result = self.invoke("audit")
        self.assertFalse(self.findings(result, "broken-local-link"))
        self.write("README.md", "[bad](docs/missing.md)\n")
        _, result = self.invoke("audit")
        self.assertEqual(len(self.findings(result, "broken-local-link")), 1)

    def test_large_markdown_is_skipped_with_a_visible_warning(self):
        self.write("README.md", "a" * (256 * 1024 + 1))
        _, result = self.invoke("audit")
        self.assertTrue(self.findings(result, "link-check-skipped"))

    def test_check_without_git_and_nested_root_do_not_use_parent_worktree(self):
        self.assertEqual(self.invoke("check")[0], 2)
        self.init_git()
        nested = self.root / "nested"
        nested.mkdir()
        self.assertEqual(self.invoke("check", root=nested)[0], 2)

    def test_empty_git_repository_checks_untracked_files(self):
        self.init_git()
        self.write("debug_probe.py")
        code, result = self.invoke("check")
        self.assertEqual(code, 0)
        self.assertTrue(self.findings(result, "scratch-location"))

    def test_invalid_policy_fields_paths_and_exceptions_fail_clearly(self):
        invalid = [
            {"schema_version": 1, "profile": "python-research", "typo": True},
            {"schema_version": True, "profile": "python-research"},
            {"schema_version": 1, "profile": "unknown"},
            {"schema_version": 1, "profile": "python-research", "paths": {"source": ["../outside/**"]}},
            {"schema_version": 1, "profile": "python-research", "exceptions": [{"rule": "tracked-payload", "path": "weights/**", "reason": "all"}]},
            {"schema_version": 1, "profile": "python-research", "exceptions": [{"rule": "tracked-payload", "path": "weights/a.pt", "reason": ""}]},
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.write(".repo-policy.json", json.dumps(value))
                code, result = self.invoke("audit")
                self.assertEqual(code, 2)
                self.assertIn("error", result)

    def test_invalid_base_is_not_interpreted_as_git_options(self):
        self.init_git()
        self.commit()
        self.assertEqual(self.invoke("check", "--base=--output=bad-file")[0], 2)
        self.assertFalse((self.root / "bad-file").exists())

    def test_policy_change_rechecks_existing_inventory(self):
        self.init_git()
        self.write("weights/legacy.pt", "legacy")
        self.commit()
        self.policy()
        code, result = self.invoke("check")
        self.assertEqual(code, 1)
        self.assertIn("full inventory", result["scope"])

    def test_locate_chinese_alias_and_no_match_return_codes(self):
        self.write("configs/train.yaml", "seed: 1\n")
        self.write("train.py")
        code, result = self.invoke("locate", "配置")
        self.assertEqual(code, 0)
        self.assertIn("configs/train.yaml", {x["path"] for x in result["matches"]})
        self.assertEqual(self.invoke("locate", "does-not-exist")[0], 1)


if __name__ == "__main__":
    unittest.main()
