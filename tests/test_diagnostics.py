import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backend.db as db_module
from backend import diagnostics
from backend.db import connect, get_job, now_iso, update_job
from backend.diagnostics import (JobTimeline, comfy_log_lines, keep_samples, memory_mode_from_argv,
                                 system_sample, workflow_graph)


class DiagnosticsTests(unittest.TestCase):
    def test_memory_mode_is_read_from_launch_arguments(self):
        self.assertEqual(memory_mode_from_argv(["main.py", "--disable-dynamic-vram"]), "legacy")
        self.assertEqual(memory_mode_from_argv(["main.py", "--enable-dynamic-vram", "--async-offload", "2"]), "dynamic")
        self.assertEqual(memory_mode_from_argv(["main.py"]), "default")
        self.assertIsNone(memory_mode_from_argv([]))

    def test_graph_keeps_every_node_input_value(self):
        workflow = {
            "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["7", 0], "sigmas": ["9", 0]}},
            "9": {"class_type": "BasicScheduler", "inputs": {"steps": 6, "denoise": 1.0, "model": ["3", 0]}},
        }
        graph = workflow_graph(workflow)
        self.assertEqual(graph["9"]["inputs"]["steps"], 6)
        self.assertEqual(graph["14"]["inputs"]["noise"], ["7", 0])
        graph["9"]["inputs"]["steps"] = 8
        self.assertEqual(workflow["9"]["inputs"]["steps"], 6, "the stored graph is a copy")

    def test_timeline_records_nodes_cache_and_step_durations(self):
        timeline = JobTimeline({"3": {"class_type": "UNETLoader"}, "14": {"class_type": "SamplerCustomAdvanced"}})
        timeline.record("execution_cached", {"nodes": ["11", "13"]}, 0.2)
        timeline.record("executing", {"node": "3"}, 1.0)
        timeline.record("executing", {"node": "14"}, 30.0)
        for value, seconds in ((0, 30.0), (1, 490.0), (1, 491.0), (2, 600.0), (3, 712.5)):
            timeline.record("progress", {"node": "14", "value": value, "max": 6}, seconds)
        timeline.record("executing", {"node": None}, 900.0)
        result = timeline.as_dict()
        self.assertEqual(result["cached_nodes"], ["11", "13"])
        self.assertEqual(result["nodes"][0], ["3", "UNETLoader", 1.0])
        self.assertEqual(result["nodes"][-1], [None, "finished", 900.0])
        self.assertEqual(result["progress"]["14"]["max"], 6)
        self.assertEqual(result["step_seconds"]["14"], [460.0, 110.0, 112.5])

    def test_samples_keep_the_start_and_the_latest_stretch(self):
        samples = [{"at_seconds": i * 5} for i in range(1000)]
        kept = keep_samples(samples)
        self.assertEqual(len(kept), diagnostics.SAMPLES_HEAD + diagnostics.SAMPLES_TAIL)
        self.assertEqual(kept[0]["at_seconds"], 0)
        self.assertEqual(kept[-1]["at_seconds"], 999 * 5)
        self.assertEqual(keep_samples(samples[:10]), samples[:10])

    def test_comfy_log_lines_keep_loading_lines_since_job_start(self):
        with tempfile.TemporaryDirectory(prefix="h3-diag-log-") as temp:
            log = Path(temp) / "comfy.log"
            log.write_text("Requested to load OldModel\n", encoding="utf-8")
            offset = log.stat().st_size
            with log.open("a", encoding="utf-8") as handle:
                handle.write("got prompt\nRequested to load MiniMaxH3\n"
                             "loaded partially; 0.00 MB loaded, 19996.14 MB offloaded\n"
                             "\r 17%|#         | 1/6 [01:46<08:51, 106.31s/it]\r\n"
                             "some unrelated line\n")
            lines = comfy_log_lines(log, offset)
        self.assertEqual(lines, ["got prompt", "Requested to load MiniMaxH3",
                                 "loaded partially; 0.00 MB loaded, 19996.14 MB offloaded"])

    def test_system_sample_parses_gpu_fields_and_unsupported_values(self):
        output = "9521, 10240, 100, 71, 332.48, 1905, 64, [N/A]\n"
        result = SimpleNamespace(returncode=0, stdout=output)
        with patch("backend.diagnostics.subprocess.run", return_value=result), \
             patch("backend.diagnostics.windows_memory", return_value={"commit_used_mib": 91000}), \
             patch("backend.diagnostics.process_sample", return_value={"comfy_private_mib": 67000}):
            sample = system_sample(1234)
        self.assertEqual(sample["vram_used_mib"], 9521)
        self.assertEqual(sample["gpu_power_w"], 332.48)
        self.assertIsNone(sample["pcie_gen"])
        self.assertEqual(sample["commit_used_mib"], 91000)
        self.assertEqual(sample["comfy_private_mib"], 67000)

    def test_system_sample_is_empty_without_nvidia_smi(self):
        with patch("backend.diagnostics.subprocess.run", side_effect=OSError):
            self.assertEqual(system_sample(), {})


class DiagnosticsPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-diag-db-")
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self.temp.name) / "jobs.sqlite3"
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    def test_public_job_view_does_not_expose_diagnostics(self):
        now = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,
                   seed,status,position,created_at,updated_at)
                   VALUES ('job1','p','text',5,'turbo','v4','native',6,928,1632,'1','completed',1,?,?)""",
                (now, now),
            )
        update_job("job1", metrics={"generation_seconds": 12.5, "diagnostics": {"graph": {"1": {}}}})
        public = get_job("job1")
        self.assertEqual(public["metrics"], {"generation_seconds": 12.5})
        with connect() as db:
            stored = json.loads(db.execute("SELECT metrics_json FROM jobs WHERE id='job1'").fetchone()[0])
        self.assertIn("graph", stored["diagnostics"])


if __name__ == "__main__":
    unittest.main()
