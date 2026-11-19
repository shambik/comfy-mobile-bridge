"""The Singularity job card tag names what ran (issue #63): src/skinLabels.ts, compiled with the project's esbuild and
run in Node. Skipped when Node or node_modules are missing."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESBUILD = ROOT / "node_modules" / "esbuild" / "bin" / "esbuild"

CASES = [
    # (workflow_variant, mode, skin options, expected tag)
    ("skin_max", "opening", {"model": "base", "speed_lora": "pika", "flow": "pika"}, "H3 + Pika (no Singularity)"),
    ("skin_god", "reference", {"model": "base", "speed_lora": "pika", "flow": "pika"}, "H3 Ref2VA + Pika (no Singularity)"),
    ("skin_max", "opening", {"model": "base", "speed_lora": "tier"}, "H3 (no Singularity)"),
    ("skin_max", "opening", {"model": "pruned", "speed_lora": "tier"}, "Singularity · Max Intelligence"),
    ("skin_god", "reference", {"model": "full"}, "Singularity · God Tier"),
    ("skin_balanced", "opening", {"model": "pruned", "speed_lora": "pika", "people_strength": 1}, "Singularity · Balanced"),
    ("skin_max", "opening", {"model": "pruned", "speed_lora": "pika"}, "Singularity (own LoRAs)"),
    ("skin_god", "opening", {"model": "pruned", "speed_lora": "ema600", "people_strength": 0}, "Singularity (own LoRAs)"),
    ("skin_app", "opening", {"model": "pruned", "speed_lora": "none", "people_strength": 0}, "Singularity · App flow"),
    (None, "opening", None, "Singularity · God Tier"),
]


@unittest.skipUnless(shutil.which("node") and ESBUILD.exists(), "needs Node and node_modules")
class SkinCardTagTest(unittest.TestCase):
    def test_tag_names_what_ran(self):
        bundle = subprocess.run(["node", str(ESBUILD), str(ROOT / "src" / "skinLabels.ts"), "--bundle", "--format=cjs",
                                 "--platform=node"], capture_output=True, text=True, check=True).stdout
        jobs = [{"workflow_variant": v, "mode": m, "skin_options_json": json.dumps(o) if o is not None else None}
                for v, m, o, _ in CASES]
        script = (bundle + "\nconst jobs = " + json.dumps(jobs) + ";\n"
                  "console.log(JSON.stringify(jobs.map(j => module.exports.skinJobTag({...j, workflow_variant: j.workflow_variant ?? undefined}))));")
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout
        self.assertEqual(json.loads(out), [expected for *_, expected in CASES])

    def test_bad_options_fall_back(self):
        bundle = subprocess.run(["node", str(ESBUILD), str(ROOT / "src" / "skinLabels.ts"), "--bundle", "--format=cjs",
                                 "--platform=node"], capture_output=True, text=True, check=True).stdout
        script = bundle + "\nconsole.log(module.exports.skinJobTag({workflow_variant: 'skin_max', skin_options_json: '{not json'}));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout
        self.assertEqual(out.strip(), "Singularity · Max Intelligence")


if __name__ == "__main__":
    unittest.main()
