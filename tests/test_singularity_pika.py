import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.config import OFFICIAL_LTX_TEMPLATES, PIKA_FL2VA_LORA, PIKA_REF2VA_LORA, PIKA_TURBO4_FL2VA_LORA, SKIN_PEOPLE_LORA
from backend.generation import (PIKA_OPTIONS, PIKA_TURBO4_MODES, PIKA_TURBO4_OPTIONS, SKIN_OPTION_DEFAULTS,
                                normalize_generation_settings, normalize_skin_options, pika_options)
from backend.worker import history_retry_phase
from backend.workflows import (apply_attention_mode, apply_steady_memory, official_ltx_template_workflow, singularity_app_workflow, singularity_workflow,
                               steady_memory_needed,
                               skin_loras, skin_prompt, turbo_workflow, workflow_node_values)


def classes(workflow):
    return {node["class_type"] for node in workflow.values()}


class PikaEngineTests(unittest.TestCase):
    def test_settings_are_the_tested_recipe(self):
        settings = normalize_generation_settings("opening", engine="pika", aspect_ratio="16:9")
        self.assertEqual((settings.engine, settings.steps, settings.width, settings.height), ("pika", 6, 1632, 928))
        self.assertEqual((settings.attention_mode, settings.workflow_variant, settings.encoder), ("standard", "direct", "native"))

    def test_untested_choices_are_refused(self):
        for kwargs in ({"mode": "closing"}, {"mode": "opening", "steps": 8}, {"mode": "opening", "aspect_ratio": "1:1"},
                       {"mode": "opening", "encoder": "clipproj"}, {"mode": "opening", "workflow_variant": "skin_god"},
                       {"mode": "opening", "attention_mode": "sla"}, {"mode": "frames", "attention_mode": "sage_sla"}):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                normalize_generation_settings(engine="pika", **kwargs)

    def test_workflow_needs_no_t8_nodes(self):
        for mode, kwargs in (("opening", {"first_frame_name": "a.png"}), ("reference", {"image_names": ["a.png"]}),
                             ("lip_sync", {"first_frame_name": "a.png", "audio_name": "a.wav"})):
            args = {"image_names": [], **kwargs}
            workflow = singularity_workflow("hello", 5, 1, "x", "skin_max", 1632, 928, args.pop("image_names"), mode=mode,
                                            steps=6, options=PIKA_OPTIONS, **args)
            with self.subTest(mode):
                self.assertFalse([name for name in classes(workflow) if "T8" in name])
                self.assertIn("ManualSigmas", classes(workflow))

    def test_reference_inputs_are_flat_keys(self):
        # ComfyUI silently drops a nested {"ref_images": {...}} dict and then renders the prompt alone.
        workflow = singularity_workflow("hello", 5, 1, "x", "skin_max", 1632, 928, ["a.png", "b.png"], mode="reference",
                                        steps=6, options=PIKA_OPTIONS, video_names=["v.mp4"], audio_name="s.wav")
        inputs = workflow["136"]["inputs"]
        self.assertEqual(inputs["ref_images.ref_image_0"], ["137", 0])
        self.assertEqual(inputs["ref_images.ref_image_1"], ["138", 0])
        self.assertEqual(inputs["ref_videos.ref_video_0"], ["151", 0])
        self.assertEqual(inputs["ref_video_audios.ref_video_audio_0"], ["151", 1])
        self.assertEqual(inputs["ref_audios.ref_audio_0"], ["180", 0])
        self.assertFalse([key for key, value in inputs.items() if isinstance(value, dict)])

    def test_lora_matches_the_base_model(self):
        self.assertEqual(skin_loras("skin_max", PIKA_OPTIONS, "opening"), [(PIKA_FL2VA_LORA, 1.0)])
        self.assertEqual(skin_loras("skin_max", PIKA_OPTIONS, "reference"), [(PIKA_REF2VA_LORA, 1.0)])


class PikaTurboTests(unittest.TestCase):
    def test_settings_are_the_tested_recipe(self):
        for mode in PIKA_TURBO4_MODES:
            settings = normalize_generation_settings(mode, engine="pika", workflow_variant="turbo4", aspect_ratio="16:9")
            with self.subTest(mode):
                self.assertEqual((settings.steps, settings.width, settings.height), (4, 1632, 928))
                self.assertEqual((settings.attention_mode, settings.workflow_variant), ("sage", "turbo4"))
        self.assertIs(pika_options("turbo4"), PIKA_TURBO4_OPTIONS)
        self.assertIs(pika_options("direct"), PIKA_OPTIONS)

    def test_untested_choices_are_refused(self):
        for kwargs in ({"mode": "reference"}, {"mode": "text"}, {"mode": "closing"}, {"mode": "opening", "steps": 6},
                       {"mode": "opening", "attention_mode": "standard"}, {"mode": "lip_sync", "attention_mode": "sage_sla"}):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                normalize_generation_settings(engine="pika", workflow_variant="turbo4", **kwargs)

    def test_workflow_is_the_lab_graph(self):
        for mode, kwargs in (("opening", {"first_frame_name": "a.png"}), ("frames", {"first_frame_name": "a.png", "last_frame_name": "b.png"}),
                             ("lip_sync", {"first_frame_name": "a.png", "audio_name": "a.wav"})):
            workflow = singularity_workflow("hello", 5, 1, "x", "skin_max", 1632, 928, [], mode=mode,
                                            steps=4, options=PIKA_TURBO4_OPTIONS, **kwargs)
            sampler = next(node["inputs"] for node in workflow.values() if node["class_type"] == "MiniMaxH3DualClockSamplerT8")
            loras = [node["inputs"] for node in workflow.values() if node["class_type"] == "LoraLoaderModelOnly"]
            with self.subTest(mode):
                self.assertEqual((sampler["steps"], sampler["scheduler"], sampler["shift_video"], sampler["shift_audio"]),
                                 (4, "simple", 12.0, 3.0))
                self.assertEqual([(lora["lora_name"], lora["strength_model"]) for lora in loras], [(PIKA_TURBO4_FL2VA_LORA, 1.0)])
                self.assertNotIn("ManualSigmas", classes(workflow))
                self.assertTrue(steady_memory_needed("pika", "sage"))


class SingularityEngineTests(unittest.TestCase):
    def test_limits(self):
        settings = normalize_generation_settings("reference", engine="singularity", workflow_variant="skin_god", megapixels=1.5, aspect_ratio="16:9")
        self.assertEqual((settings.width, settings.height, settings.steps), (1632, 928, 8))
        for kwargs in ({"mode": "reference", "workflow_variant": "skin_app"}, {"mode": "opening", "steps": 20},
                       {"mode": "opening", "megapixels": 2.0}, {"mode": "opening", "aspect_ratio": "1:1"}):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                normalize_generation_settings(engine="singularity", **kwargs)

    def test_options_are_validated(self):
        self.assertEqual(normalize_skin_options(None), SKIN_OPTION_DEFAULTS)
        for raw in ('{"unknown": 1}', '{"model": "other"}', '{"speed_strength": 9}', '{"flow": "pika", "tail_steps": 2}', "nope"):
            with self.subTest(raw), self.assertRaises(ValueError):
                normalize_skin_options(raw)

    def test_people_trigger_only_with_the_people_lora(self):
        self.assertEqual(skin_prompt("r34l1sm\nhello", False), "hello")
        self.assertEqual(skin_prompt("hello", True), "r34l1sm\n\nhello")
        self.assertIn((SKIN_PEOPLE_LORA, 1.0), skin_loras("skin_god", SKIN_OPTION_DEFAULTS))

    def test_app_flow_needs_no_t8_nodes(self):
        workflow = singularity_app_workflow("hello", 5, 1, "x", "lip_sync", 928, 1632, first_frame_name="a.png", audio_name="a.wav",
                                            steps=8, options=SKIN_OPTION_DEFAULTS)
        self.assertFalse([name for name in classes(workflow) if "T8" in name])


class OfficialLtxTemplateTests(unittest.TestCase):
    def test_templates_ship_with_the_app_and_take_the_inputs(self):
        for mode, last in (("opening", None), ("frames", "b.png")):
            self.assertTrue(OFFICIAL_LTX_TEMPLATES[mode].exists())
            workflow = official_ltx_template_workflow(mode, "a prompt", 5, 123, "out", 1600, 896, "a.png", last)
            text = json.dumps(workflow)
            with self.subTest(mode):
                self.assertIn("a prompt", text)
                self.assertIn("a.png", text)
                self.assertNotIn("TextGenerateLTX2Prompt", text)
                self.assertNotIn("D:/", text)


class HistoryRetryPhaseTests(unittest.TestCase):
    def test_slow_history_poll_keeps_the_sampling_phase(self):
        self.assertEqual(history_retry_phase(None), {"phase": "starting"})
        self.assertEqual(history_retry_phase(12.5), {})


class NodeValueTests(unittest.TestCase):
    def test_links_show_the_value_and_the_source(self):
        workflow = {
            "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1600}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "3": {"class_type": "ComfyMathExpression", "inputs": {"expression": "a", "values.a": ["1", 0]}},
            "4": {"class_type": "ComfyMathExpression", "inputs": {"expression": "a*2", "values.a": ["1", 0]}},
            "5": {"class_type": "Target", "inputs": {"width": ["1", 0], "input": ["2", 0], "pass": ["3", 0], "made": ["4", 1], "seed": 2 ** 60}},
        }
        inputs = {row["id"]: row["inputs"] for row in workflow_node_values(workflow)}["5"]
        self.assertEqual(inputs["width"], "1600 (from #1)")
        self.assertEqual(inputs["input"], "a.png (from #2)")
        self.assertEqual(inputs["pass"], "1600 (from #3)")
        self.assertEqual(inputs["made"], "from ComfyMathExpression #4.1")
        self.assertEqual(inputs["seed"], str(2 ** 60))

    def test_existing_workflow_rows_are_serializable(self):
        rows = workflow_node_values(turbo_workflow("hello", 5, 1, "x", first_frame_name="a.png", steps=6, width=928, height=1632, turbo_profile="v4"))
        self.assertTrue(json.dumps(rows))


class SteadyMemoryTests(unittest.TestCase):
    def test_only_sage_on_pika_needs_it(self):
        for engine, attention, needed in (("pika", "sage", True), ("singularity", "sage", False), ("pika", "standard", False),
                                          ("singularity", "standard", False), ("turbo", "sage", False), ("ltx", "standard", False)):
            with self.subTest(engine=engine, attention=attention):
                self.assertEqual(steady_memory_needed(engine, attention), needed)

    def test_node_sits_after_sage_and_feeds_its_consumers(self):
        base = singularity_workflow("hello", 5, 1, "x", "skin_max", 1632, 928, [], mode="opening", steps=6, options=PIKA_OPTIONS, first_frame_name="a.png")
        sage = apply_attention_mode(base, "sage")
        steady = apply_steady_memory(sage)
        sage_id = next(key for key, node in steady.items() if node["class_type"] == "PathchSageAttentionKJ")
        steady_id = next(key for key, node in steady.items() if node["class_type"] == "H3SteadyMemory")
        self.assertEqual(steady[steady_id]["inputs"]["model"], [sage_id, 0])
        consumers = [node for key, node in steady.items() if node["inputs"].get("model") == [sage_id, 0]]
        self.assertEqual([node["class_type"] for node in consumers], ["H3SteadyMemory"])
        self.assertTrue([node for node in steady.values() if node["inputs"].get("model") == [steady_id, 0]])
        self.assertNotIn("H3SteadyMemory", classes(sage))


if __name__ == "__main__":
    unittest.main()
