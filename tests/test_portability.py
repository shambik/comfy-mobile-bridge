import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.skill_catalog import selected_skill_manifest_context


ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_config_root_does_not_depend_on_current_working_directory(self):
        code = "from backend.config import ROOT; print(ROOT)"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT)
        result = subprocess.run(
            [os.environ.get("PYTHON", "python"), "-c", code],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
            check=True,
            env=environment,
        )
        self.assertEqual(Path(result.stdout.strip()).resolve(), ROOT)

    def test_example_config_is_local_only(self):
        config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["runtime_root"], ".runtime")
        self.assertEqual(config["app"], {"host": "127.0.0.1", "port": 8787})
        self.assertEqual(config["comfy"], {"host": "127.0.0.1", "port": 8190})
        self.assertEqual(config["tailscale"], {"enabled": True, "scope": "tailnet"})

    def test_missing_local_config_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory(prefix="h3-config-test-") as directory:
            environment = os.environ.copy()
            environment["H3_CONFIG_PATH"] = str(Path(directory) / "missing.json")
            environment["PYTHONPATH"] = str(ROOT)
            result = subprocess.run(
                [os.environ.get("PYTHON", "python"), "-c", "from backend.config import COMFY_URL; print(COMFY_URL)"],
                cwd=ROOT.parent,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), "http://127.0.0.1:8190")

    def test_invalid_local_config_fails_loudly(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            handle.write("not json")
            invalid_path = handle.name
        try:
            environment = os.environ.copy()
            environment["H3_CONFIG_PATH"] = invalid_path
            environment["PYTHONPATH"] = str(ROOT)
            result = subprocess.run(
                [os.environ.get("PYTHON", "python"), "-c", "import backend.config"],
                cwd=ROOT.parent,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid local configuration", result.stderr)
        finally:
            Path(invalid_path).unlink(missing_ok=True)

    def test_non_local_listener_config_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {
                    "runtime_root": ".runtime",
                    "profile": "full",
                    "app": {"host": "192.168.1.1", "port": 8787},
                    "comfy": {"host": "127.0.0.1", "port": 8190},
                    "tailscale": {"enabled": True, "scope": "tailnet"},
                },
                handle,
            )
            invalid_path = handle.name
        try:
            environment = os.environ.copy()
            environment["H3_CONFIG_PATH"] = invalid_path
            environment["PYTHONPATH"] = str(ROOT)
            result = subprocess.run(
                [os.environ.get("PYTHON", "python"), "-c", "import backend.config"],
                cwd=ROOT.parent,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be 127.0.0.1", result.stderr)
        finally:
            Path(invalid_path).unlink(missing_ok=True)

    def test_tailscale_hostname_is_loaded_only_from_local_config(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {
                    "runtime_root": ".runtime",
                    "profile": "full",
                    "app": {"host": "127.0.0.1", "port": 8787},
                    "comfy": {"host": "127.0.0.1", "port": 8190},
                    "tailscale": {"enabled": True, "scope": "tailnet", "hostname": "other-machine.example." + "ts.net"},
                },
                handle,
            )
            config_path = handle.name
        try:
            environment = os.environ.copy()
            environment["H3_CONFIG_PATH"] = config_path
            environment["PYTHONPATH"] = str(ROOT)
            result = subprocess.run(
                [os.environ.get("PYTHON", "python"), "-c", "from backend.config import ALLOWED_HOSTS; print(ALLOWED_HOSTS[-1])"],
                cwd=ROOT.parent,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), "other-machine.example." + "ts.net")
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_manifests_are_complete_and_pinned(self):
        dependencies = json.loads((ROOT / "manifests" / "dependencies.json").read_text(encoding="utf-8"))
        models = json.loads((ROOT / "manifests" / "models.json").read_text(encoding="utf-8"))
        self.assertEqual(len(dependencies["repositories"]), 5)
        self.assertEqual(len(models["models"]), 13)
        for item in dependencies["repositories"]:
            self.assertRegex(item["revision"], r"^[0-9a-f]{40}$")
        for item in models["models"]:
            self.assertRegex(item["revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(item["bytes"], 0)

    def test_required_agent_instruction_layout_exists(self):
        self.assertLessEqual(len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()), 20)
        required = {
            "h3-environment-bootstrap",
            "h3-mobile-bridge-codebase",
            "git-standards",
            "code-patterns",
            "release-process",
        }
        production = {
            "e2e-music-video",
            "e2e-music-video-poc",
            "realistic-rap-turbo-poc",
            "lipsync-skill",
            "council-roles",
            "audio-analyst",
            "visual-director",
            "storyboard-editor",
            "scene-frame-designer",
            "prompt-engineer",
            "technical-director",
            "technical-qc",
            "av-sync-reviewer",
            "continuity-editor",
            "post-production-editor",
            "executive-producer",
            "creative-director",
        }
        actual = {path.name for path in (ROOT / ".agents" / "skills").iterdir() if path.is_dir()}
        self.assertTrue(required.issubset(actual))
        self.assertTrue(production.issubset(actual))
        for name in required | production:
            self.assertTrue((ROOT / ".agents" / "skills" / name / "SKILL.md").is_file())
        for name in production:
            text = (ROOT / ".agents" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), name)
            self.assertIn("name:", text.split("---\n", 2)[1], name)
            self.assertIn("description:", text.split("---\n", 2)[1], name)

    def test_selected_skill_context_references_file_without_injecting_body(self):
        with tempfile.TemporaryDirectory(prefix="skill-manifest-test-") as directory:
            skill_root = Path(directory) / "specialist"
            skill_root.mkdir()
            (skill_root / "SKILL.md").write_text(
                "---\nname: specialist\ndescription: Test specialist\n---\nSECRET BODY\n",
                encoding="utf-8",
            )
            catalog_entry = {
                "name": "specialist",
                "description": "Test specialist",
                "path": str(skill_root),
                "enabled": True,
                "valid": True,
            }
            with patch("backend.skill_catalog.get_skill", return_value=catalog_entry):
                context = selected_skill_manifest_context(["specialist-id"])
            self.assertIn(str(skill_root / "SKILL.md"), context)
            self.assertIn("Test specialist", context)
            self.assertNotIn("SECRET BODY", context)

    def test_source_has_no_parent_workspace_or_fixed_tailnet_values(self):
        source = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
        self.assertNotIn("H3_ROOT", source)
        self.assertNotIn("100." + "81.116.55", source)
        self.assertNotIn("ts." + "net", source)
        self.assertNotIn("parents[2]", source)

    def test_verified_download_pattern_is_present(self):
        source = (ROOT / "scripts" / "common.ps1").read_text(encoding="utf-8")
        self.assertIn("$Destination.part", source)
        self.assertIn("--continue-at -", source)
        self.assertIn("Get-FileHash", source)
        self.assertIn("Move-Item -LiteralPath $partial", source)

    def test_preflight_has_all_hard_requirements_and_exit_codes(self):
        source = (ROOT / "scripts" / "preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("ram_32_gib", source)
        self.assertIn("free_disk_100_gib", source)
        self.assertIn("vram_8_gib", source)
        for tool in ("git", "node", "ffmpeg", "ffprobe", "curl"):
            self.assertIn(f"'{tool}'", source)
        self.assertIn("failure_code -eq 3", source)


if __name__ == "__main__":
    unittest.main()
