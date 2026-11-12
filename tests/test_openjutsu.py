"""Openjutsu swap engine (backend/openjutsu.py, issue #58): the graph the worker runs and the sheet's limits."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import backend.character_swap as cs
import backend.openjutsu as oj
from backend.workflows import graph_spec_workflow


def links(nodes):
    for node_id, node in nodes.items():
        for key, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                yield node_id, key, value


class OpenjutsuGraphTests(unittest.TestCase):
    def build(self, resolution="736p", remove_hair=False):
        return oj.build_graph("src.mp4", [("char.png", oj.role_text("the man   on the right"))], 2 ** 40 + 7,
                              resolution, remove_hair)

    def test_the_graph_is_openjutsus_advanced_swap_with_its_app_defaults(self):
        g = self.build()
        plan = g[oj.by_title(g, oj.PLAN)]["inputs"]
        self.assertEqual(plan["resolution"], "736p")
        self.assertEqual(plan["seed"], 7)                          # Openjutsu's seed range is 32 bit
        self.assertEqual((plan["clip_seconds"], plan["steps"]), (6, 6))
        self.assertEqual(plan["roles"], "the person - the man on the right")
        self.assertNotIn("no_lip_sync", plan)                      # lip-sync on: H3 hears the soundtrack
        self.assertEqual(g[oj.by_title(g, oj.VIDEO)]["inputs"]["video"], "src.mp4")
        self.assertEqual(g[oj.by_title(g, "Picture 1")]["inputs"]["image"], "char.png")
        titles = {n.get("_meta", {}).get("title", "") for n in g.values()}
        for gone in ("Picture 2", "Picture 4", "SAM: hats", "SAM: faces", "Mute the clip audio H3 hears"):
            self.assertNotIn(gone, titles)
        loras = [n["inputs"]["lora_name"] for n in g.values() if n["class_type"] == "LoraLoaderModelOnly"]
        self.assertEqual(loras, ["h3_edit\minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors"])
        self.assertIn(("loras/h3_edit", "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors"), oj.MODELS)
        encoders = [n["inputs"]["clip_name"] for n in g.values() if n["class_type"] == "CLIPLoader"]
        self.assertIn(oj.TEXT_ENCODER, encoders)
        self.assertIn(oj.DESCRIBER, encoders)
        self.assertTrue(all(n["inputs"]["expand"] == oj.MARGIN for n in g.values()
                            if n["class_type"] == "GrowMaskWithBlur" and " grow mask " in n["_meta"]["title"]))
        self.assertEqual([n["inputs"]["largest_size"] for n in g.values()
                          if "motion reference" in n.get("_meta", {}).get("title", "").lower()
                          and n["class_type"] == "ImageScaleToMaxDimension"], [oj.MOTION_SIZE])
        r2v = next(n for n in g.values() if n["class_type"] == "MiniMaxH3ReferenceToVideo")
        self.assertNotIn("ref_images.ref_image_1", r2v["inputs"])
        for node_id, key, value in links(g):
            self.assertIn(value[0], g, f"{node_id}.{key}")
        self.assertFalse(any(n["class_type"].startswith("H3InpaintArea") for n in g.values()))

    def test_the_result_is_saved_by_one_savevideo_for_the_bridge(self):
        nodes = graph_spec_workflow({"base": self.build("480p")}, "h3_bridge_x")
        saves = [n for n in nodes.values() if n["class_type"] == "SaveVideo"]
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["inputs"]["filename_prefix"], "h3_bridge_x")
        load = nodes[saves[0]["inputs"]["video"][0]]["inputs"]["images"][0]
        final = nodes[load]["inputs"]["video"][0]
        self.assertEqual(nodes[final]["class_type"], "MiniMaxH3ChainAssemble")

    def test_the_hair_eraser_feeds_h3_a_mannequin_without_the_source_hair(self):
        g = self.build(remove_hair=True)
        mannequin = next(i for i, n in g.items() if n["class_type"] == "H3GreyMannequins")
        users = [(i, k) for i, k, v in links(g) if v == [mannequin, 0]]
        self.assertEqual(users, [("hair_erased", "images")])        # only the eraser reads the raw mannequin
        r2v = next(n for n in g.values() if n["class_type"] == "MiniMaxH3ReferenceToVideo")
        self.assertEqual(r2v["inputs"]["ref_videos.ref_video_0"], ["hair_erased", 0])
        # hair is detected per frame on the replaced person alone (a whole-frame track missed a late entrance)
        self.assertEqual(g["hair_detect"]["class_type"], "SAM3_Detect")
        self.assertEqual(g["hair_detect"]["inputs"]["image"], ["hair_alone", 0])
        self.assertEqual(g["hair_area"]["inputs"]["mask"], g[mannequin]["inputs"]["mask"])
        self.assertTrue(set(oj.HELPER_NODES) <= {n["class_type"] for n in g.values()})

    def test_up_to_three_characters_each_with_its_own_picture_and_role(self):
        people = [(f"c{k}.png", oj.role_text(f"look {k}", who)) for k, who in
                  enumerate(oj.positions([0.8, 0.1, 0.5]), 1)]
        self.assertEqual([r.split(" - ")[0] for _p, r in people],
                         ["the person on the right", "the person on the left", "the person in the middle"])
        g = oj.build_graph("src.mp4", people, 1, "736p", False)
        self.assertEqual([g[oj.by_title(g, f"Picture {k}")]["inputs"]["image"] for k in (1, 2, 3)],
                         ["c1.png", "c2.png", "c3.png"])
        self.assertEqual(g[oj.by_title(g, oj.PLAN)]["inputs"]["roles"].splitlines(), [r for _p, r in people])
        r2v = next(n for n in g.values() if n["class_type"] == "MiniMaxH3ReferenceToVideo")
        self.assertEqual(sorted(k for k in r2v["inputs"] if k.startswith("ref_images.")),
                         ["ref_images.ref_image_0", "ref_images.ref_image_1", "ref_images.ref_image_2"])
        self.assertNotIn("Picture 4", {n.get("_meta", {}).get("title") for n in g.values()})
        for node_id, key, value in links(g):
            self.assertIn(value[0], g, f"{node_id}.{key}")
        with self.assertRaisesRegex(ValueError, "1-3 characters"):
            oj.build_graph("src.mp4", people + [("c4.png", "x - y")], 1, "736p", False)
        self.assertEqual(oj.positions([0.3, 0.6]), ["the person on the left", "the person on the right"])

    def test_only_the_tested_sizes(self):
        with self.assertRaisesRegex(ValueError, "480p or 736p"):
            self.build("1080p")
        self.assertEqual(oj.canvas(1024, 576, "480p"), (864, 480))     # The Last Fold, measured
        self.assertEqual(oj.canvas(1024, 576, "736p"), (1312, 736))
        self.assertEqual(oj.canvas(832, 480, "480p"), (832, 480))      # the pizza clip, measured
        self.assertEqual(oj.canvas(720, 1280, "736p"), (736, 1312))


class OpenjutsuSwapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-oj-test-")
        root = Path(self.temp.name)
        self.patches = [patch.object(cs, "SWAPS", root / "swaps"), patch.object(cs, "CHARACTERS", root / "chars"),
                        patch.object(cs, "CHARACTERS_FILE", root / "chars" / "characters.json"),
                        patch.object(cs, "INPUT", root / "input"),
                        patch.object(cs, "OPENJUTSU_PATCH", root / "video_edit.py")]
        for item in self.patches:
            item.start()
        cs.SWAPS.mkdir(parents=True)
        cs.INPUT.mkdir()
        png = root / "c.png"
        Image.new("RGB", (64, 64), (200, 10, 10)).save(png)
        self.suit = cs.add_character("Suit man", png.read_bytes(), "bald")
        self.other = cs.add_character("Other", png.read_bytes())
        self.swap = {"id": "abcdef123456", "title": "fold", "status": "marking", "stage": "", "error": None,
                     "width": 1024, "height": 576, "source_frames": 362, "frames": 362, "seconds": 15.08,
                     "trimmed": False, "marks": [], "job_id": None, "mode": "reference", "notes": "",
                     "shots": [{"index": 0, "start": 0, "end": 362, "key_frame": 30, "frame": "f.png"}]}
        folder = cs.SWAPS / self.swap["id"]
        folder.mkdir()
        Image.new("RGB", (1024, 576)).save(folder / "f.png")
        (folder / "source.mp4").write_bytes(b"x")
        (folder / "swap.json").write_text(json.dumps(self.swap), encoding="utf-8")
        self.queued = []
        cs.set_job_queue(lambda **kw: self.queued.append(kw) or "job1")

    def tearDown(self):
        cs.set_job_queue(None)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def mark(self, character):
        return {"shot": 0, "x": 0.7, "y": 0.4, "character_id": character["id"], "description": "the man with red hair"}

    def test_up_to_three_characters_and_the_tested_settings(self):
        png = Path(self.temp.name) / "c.png"
        extra = [cs.add_character(f"Extra {k}", png.read_bytes()) for k in range(2)]
        four = [{**self.mark(c), "x": x} for c, x in zip([self.suit, self.other, *extra], (0.1, 0.4, 0.6, 0.9))]
        with self.assertRaisesRegex(ValueError, "up to 3"):
            cs.set_marks(self.swap["id"], four, engine="openjutsu")
        swap = cs.set_marks(self.swap["id"], four[:3], engine="openjutsu")
        self.assertEqual(len(swap["marks"]), 3)
        with self.assertRaisesRegex(ValueError, "480p or 736p"):
            cs.set_marks(self.swap["id"], [self.mark(self.suit)], engine="openjutsu",
                         openjutsu_options={"resolution": "1080p"})
        swap = cs.set_marks(self.swap["id"], [self.mark(self.suit)], engine="openjutsu",
                            openjutsu_options={"resolution": "480p", "remove_hair": 1, "extra": "x"})
        self.assertEqual(swap["openjutsu"], {"resolution": "480p", "remove_hair": True})

    def test_two_characters_render_as_one_job_with_two_pictures(self):
        cs.OPENJUTSU_PATCH.write_text("comfy-mobile-bridge #58", encoding="utf-8")
        cs.set_marks(self.swap["id"], [{**self.mark(self.suit), "x": 0.8},
                                       {**self.mark(self.other), "x": 0.2, "description": "the woman"}], engine="openjutsu")
        cs.render(self.swap["id"], None)
        nodes = graph_spec_workflow(self.queued[0]["options"]["graph"], "p")
        roles = nodes[oj.by_title(nodes, oj.PLAN)]["inputs"]["roles"].splitlines()
        self.assertEqual(roles, ["the person on the right - the man with red hair", "the person on the left - the woman"])
        self.assertEqual(nodes[oj.by_title(nodes, "Picture 2")]["inputs"]["image"], f"swap_char_{self.other['id']}.png")

    def test_render_needs_the_patched_pack_and_queues_one_job(self):
        cs.set_marks(self.swap["id"], [self.mark(self.suit)], engine="openjutsu",
                     openjutsu_options={"resolution": "736p", "remove_hair": True})
        with self.assertRaisesRegex(ValueError, "bridge patch"):
            cs.render(self.swap["id"], None)
        cs.OPENJUTSU_PATCH.write_text("# comfy-mobile-bridge #58: keep that clip", encoding="utf-8")
        cs.render(self.swap["id"], None)
        self.assertEqual(len(self.queued), 1)
        job = self.queued[0]
        self.assertEqual((job["variant"], job["width"], job["height"], job["steps"]), ("openjutsu", 1312, 736, 6))
        self.assertEqual(job["options"]["models"], oj.MODELS)
        nodes = graph_spec_workflow(job["options"]["graph"], "p")
        self.assertIn("hair_erased", nodes)
        self.assertTrue((cs.INPUT / f"swap_char_{self.suit['id']}.png").is_file())

    def test_clips_longer_than_tested_are_refused(self):
        swap = cs.get_swap(self.swap["id"])
        swap.update(frames=24 * 16, seconds=16.0)
        cs._save_swap(swap)
        cs.OPENJUTSU_PATCH.write_text("comfy-mobile-bridge #58", encoding="utf-8")
        cs.set_marks(self.swap["id"], [self.mark(self.suit)], engine="openjutsu")
        with self.assertRaisesRegex(ValueError, "tested up to 15.1 s"):
            cs.render(self.swap["id"], None)


if __name__ == "__main__":
    unittest.main()
