import unittest

from backend.generation import GenerationSettings, normalize_generation_settings
from backend.workflows import (native_audio_lock_workflow, reference_workflow,
                               spectrum_workflow, standard_workflow, turbo_workflow)


class GenerationSettingsTests(unittest.TestCase):
    def test_current_defaults_are_preserved(self):
        self.assertEqual(
            normalize_generation_settings("text"),
            GenerationSettings("turbo", 4, 736, 416),
        )
        self.assertEqual(
            normalize_generation_settings("reference"),
            GenerationSettings("standard", 20, 736, 416),
        )
        self.assertEqual(
            normalize_generation_settings("lip_sync"),
            GenerationSettings("standard", 20, 736, 416),
        )
        self.assertEqual(
            normalize_generation_settings("reference", "spectrum", 16),
            GenerationSettings("spectrum", 16, 736, 416),
        )
        self.assertEqual(
            normalize_generation_settings("text", "turbo", 4, "512x288", "clipproj"),
            GenerationSettings("turbo", 4, 512, 288, "clipproj"),
        )

    def test_safe_ranges_and_presets_are_enforced(self):
        cases = [
            ("text", "turbo", 3, "736x416"),
            ("text", "turbo", 13, "736x416"),
            ("text", "standard", 7, "736x416"),
            ("text", "standard", 31, "736x416"),
            ("reference", "turbo", 5, "736x416"),
            ("text", "spectrum", 7, "736x416"),
            ("text", "spectrum", 31, "736x416"),
            ("text", "standard", 20, "1025x576"),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                normalize_generation_settings(*case)
        with self.assertRaises(ValueError):
            normalize_generation_settings("text", encoder="unknown")
        with self.assertRaises(ValueError):
            normalize_generation_settings("text", "turbo", 9, turbo_profile="v4")
        with self.assertRaises(ValueError):
            normalize_generation_settings("text", turbo_profile="unknown")
        with self.assertRaises(ValueError):
            normalize_generation_settings("lip_sync", "turbo", 4)
        with self.assertRaises(ValueError):
            normalize_generation_settings("lip_sync", "standard", 20, encoder="clipproj")

    def test_turbo_v4_profile_is_explicit_and_keeps_v1_default(self):
        self.assertEqual(normalize_generation_settings("text").turbo_profile, "v1")
        settings = normalize_generation_settings("text", "turbo", 6, turbo_profile="v4")
        self.assertEqual(settings.turbo_profile, "v4")


class WorkflowTests(unittest.TestCase):
    def test_turbo_uses_selected_steps_and_resolution(self):
        workflow = turbo_workflow("test", 5, 1, "turbo", steps=6, width=512, height=288)
        self.assertEqual(workflow["9"]["inputs"]["steps"], 6)
        self.assertEqual(workflow["7"]["class_type"], "ResolutionSelector")
        self.assertEqual(workflow["7"]["inputs"]["aspect_ratio"], "16:9 (Widescreen)")
        self.assertAlmostEqual(workflow["7"]["inputs"]["megapixels"], 512 * 288 / (1024 * 1024))
        self.assertEqual(workflow["104"]["inputs"]["width"], ["7", 0])
        self.assertEqual(workflow["104"]["inputs"]["height"], ["7", 1])
        self.assertEqual(workflow["104"]["inputs"]["length"], ["106", 1])
        self.assertEqual(workflow["106"]["class_type"], "ComfyMathExpression")
        self.assertEqual(workflow["17"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual(workflow["19"]["class_type"], "MiniMaxH3TurboSampler")
        self.assertEqual(workflow["18"]["class_type"], "MiniMaxH3TurboLoRA")

    def test_turbo_v4_selects_the_side_by_side_lora(self):
        workflow = turbo_workflow("test", 5, 11, "turbo-v4", steps=6, turbo_profile="v4")
        self.assertEqual(
            workflow["18"]["inputs"]["lora_name"],
            "minimax_h3_turbo_v4_step600_ema.safetensors",
        )

    def test_standard_omits_turbo_nodes_and_keeps_frames(self):
        workflow = standard_workflow(
            "test", 10, 2, "standard", first_frame_name="first.png",
            last_frame_name="last.png", steps=8, width=864, height=480,
        )
        self.assertNotIn("18", workflow)
        self.assertNotIn("19", workflow)
        self.assertEqual(workflow["17"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(workflow["9"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["104"]["inputs"]["first_frame"], ["200", 0])
        self.assertEqual(workflow["104"]["inputs"]["last_frame"], ["201", 0])
        self.assertEqual(workflow["104"]["inputs"]["length"], ["106", 1])

    def test_native_audio_lock_uses_exact_audio_and_optional_first_frame(self):
        workflow = native_audio_lock_workflow(
            "natural lip sync", 5, 42, "lip-sync", "voice.wav",
            first_frame_name="face.png", steps=20, width=864, height=480,
        )
        self.assertEqual(workflow["18"]["class_type"], "MiniMaxH3NativeAudioLock")
        self.assertEqual(workflow["23"], {
            "class_type": "LoadAudio", "inputs": {"audio": "voice.wav"},
        })
        self.assertEqual(workflow["104"]["inputs"]["first_frame"], ["200", 0])
        self.assertEqual(workflow["14"]["inputs"]["latent_image"], ["18", 1])
        self.assertEqual(workflow["91"]["inputs"]["audio"], ["18", 2])
        self.assertNotIn("VAEDecodeAudio", {node["class_type"] for node in workflow.values()})

    def test_reference_uses_selected_standard_profile(self):
        workflow = reference_workflow(
            "test", 5, 3, "reference", "face.png", steps=24, width=736, height=416,
        )
        self.assertEqual(workflow["124"]["inputs"]["steps"], 24)
        self.assertEqual(workflow["136"]["inputs"]["width"], ["7", 0])
        self.assertEqual(workflow["136"]["inputs"]["height"], ["7", 1])
        self.assertEqual(workflow["123"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(workflow["123"]["inputs"]["sampler_name"], "res_multistep")

    def test_reference_audio_uses_official_ref_audio_input(self):
        workflow = reference_workflow(
            "<Picture 1> speaks in time with <Audio 1>", 5, 12,
            "reference-audio", "face.png", audio_name="voice.wav",
        )
        self.assertEqual(workflow["180"], {
            "class_type": "LoadAudio", "inputs": {"audio": "voice.wav"},
        })
        self.assertEqual(
            workflow["136"]["inputs"]["ref_audios"],
            {"ref_audio_0": ["180", 0]},
        )

    def test_reference_turbo_uses_dedicated_chain_and_multiple_media(self):
        workflow = reference_workflow(
            "test", 5, 13, "reference-turbo", None, turbo=True,
            image_names=["one.png", "two.png"], video_names=["ref.mp4"],
            include_audio=False,
        )
        self.assertEqual(workflow["128"]["inputs"]["lora_name"], "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors")
        self.assertEqual(workflow["129"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual(workflow["130"]["class_type"], "MiniMaxH3TurboSampler")
        self.assertEqual(workflow["136"]["inputs"]["ref_images"], {"ref_image_0": ["137", 0], "ref_image_1": ["138", 0]})
        self.assertEqual(workflow["136"]["inputs"]["ref_videos"], {"ref_video_0": ["151", 0]})
        self.assertNotIn("23", workflow)

    def test_spectrum_is_separate_from_turbo_and_keeps_frames(self):
        workflow = spectrum_workflow(
            "test", 10, 4, "spectrum", first_frame_name="first.png",
            last_frame_name="last.png", steps=16, width=736, height=416,
        )
        self.assertEqual(workflow["17"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual(workflow["18"]["class_type"], "SpectrumApplyMiniMaxH3")
        self.assertEqual(workflow["19"]["inputs"]["sampler_name"], "res_multistep")
        self.assertNotIn("MiniMaxH3TurboSampler", {node["class_type"] for node in workflow.values()})
        self.assertEqual(workflow["104"]["inputs"]["first_frame"], ["200", 0])
        self.assertEqual(workflow["104"]["inputs"]["last_frame"], ["201", 0])

    def test_reference_can_use_spectrum_chain(self):
        workflow = reference_workflow("test", 5, 5, "reference-spectrum", "face.png", steps=16, spectrum=True)
        self.assertEqual(workflow["124"]["inputs"]["model"], ["129", 0])
        self.assertEqual(workflow["129"]["class_type"], "SpectrumApplyMiniMaxH3")
        self.assertEqual(workflow["130"]["inputs"]["sampler_name"], "res_multistep")
        self.assertNotIn("123", workflow)

    def test_clipproj_replaces_only_the_text_encoder(self):
        workflow = turbo_workflow(
            "test", 5, 7, "clipproj", steps=4, width=512, height=288,
            encoder="clipproj",
        )
        self.assertEqual(workflow["13"]["class_type"], "ClipProjLoader")
        self.assertEqual(workflow["13"]["inputs"]["projection"], "h3_qwen3vl_4b_tap24.safetensors")
        self.assertEqual(workflow["13"]["inputs"]["mode"], "dynamic")
        self.assertEqual(workflow["19"]["class_type"], "MiniMaxH3TurboSampler")

    def test_clipproj_reference_uses_resident_mode(self):
        workflow = reference_workflow(
            "test", 5, 8, "clipproj-reference", "face.png", encoder="clipproj",
        )
        self.assertEqual(workflow["13"]["class_type"], "ClipProjLoader")
        self.assertEqual(workflow["13"]["inputs"]["mode"], "resident")


if __name__ == "__main__":
    unittest.main()
