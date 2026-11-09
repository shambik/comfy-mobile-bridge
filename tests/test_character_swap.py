"""Character swap flow (backend/character_swap.py) - what Viggle receives in both modes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import backend.character_swap as cs


class CharacterSwapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-swap-test-")
        root = Path(self.temp.name)
        self.patches = [patch.object(cs, "SWAPS", root / "swaps"), patch.object(cs, "CHARACTERS", root / "chars"),
                        patch.object(cs, "CHARACTERS_FILE", root / "chars" / "characters.json")]
        for item in self.patches:
            item.start()
        cs.SWAPS.mkdir(parents=True)
        self.root = root
        png = root / "c.png"
        Image.new("RGB", (64, 64), (200, 10, 10)).save(png)
        self.suit = cs.add_character("Suit man", png.read_bytes(), "bald, round sunglasses, black suit")
        self.hippie = cs.add_character("Record man", png.read_bytes())
        # a two-shot swap made by hand (create_swap needs FFmpeg and a video)
        self.swap = {"id": "abcdef123456", "title": "test", "status": "marking", "stage": "", "error": None,
                     "width": 320, "height": 180, "source_frames": 124, "frames": 124, "seconds": 5.17,
                     "trimmed": False, "marks": [], "job_id": None, "mode": "reference", "notes": "",
                     "shots": [{"index": 0, "start": 0, "end": 60, "key_frame": 30, "frame": "shot0_frame.png"},
                               {"index": 1, "start": 60, "end": 124, "key_frame": 92, "frame": "shot1_frame.png"}]}
        folder = cs.SWAPS / self.swap["id"]
        folder.mkdir()
        for shot in self.swap["shots"]:
            Image.new("RGB", (320, 180), (10, 10, 10)).save(folder / shot["frame"])
        (folder / "swap.json").write_text(json.dumps(self.swap), encoding="utf-8")

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def marks(self):
        return [{"shot": 0, "x": 0.2, "y": 0.4, "character_id": self.suit["id"], "description": "the man on the left"},
                {"shot": 0, "x": 0.7, "y": 0.4, "character_id": self.hippie["id"], "description": "the woman in yellow"},
                {"shot": 1, "x": 0.5, "y": 0.5, "character_id": self.suit["id"], "description": "the man in the close-up"}]

    def test_window_is_17n_plus_5_within_one_render(self):
        self.assertEqual(cs.window_frames(124), 124)
        self.assertEqual(cs.window_frames(121), 107)
        self.assertEqual(cs.window_frames(300), 124)
        self.assertEqual(cs.window_frames(80), 0)

    def test_characters_need_no_ai(self):
        self.assertEqual(self.suit["status"], "ready")
        self.assertEqual(self.suit["look"], "bald, round sunglasses, black suit")
        edited = cs.update_character(self.hippie["id"], look="bucket hat, denim jacket")
        self.assertEqual(edited["look"], "bucket hat, denim jacket")

    def test_marks_need_a_description_and_one_character_per_person(self):
        swap = cs.set_marks(self.swap["id"], self.marks(), "reference", "two friends talk")
        self.assertEqual(len(swap["marks"]), 3)
        bad = self.marks()
        bad[0]["description"] = " "
        with self.assertRaisesRegex(ValueError, "Describe person 1"):
            cs.set_marks(self.swap["id"], bad)
        twice = self.marks()
        twice[1]["character_id"] = self.suit["id"]
        with self.assertRaisesRegex(ValueError, "only one person in a part"):
            cs.set_marks(self.swap["id"], twice)
        with self.assertRaises(ValueError):
            cs.set_marks(self.swap["id"], self.marks(), "magic")

    def test_reference_prompt_names_each_replaced_person_and_pins_nothing(self):
        swap = cs.set_marks(self.swap["id"], self.marks(), "reference", "two friends talk")
        chars = {c["id"]: c for c in cs.list_characters()}
        prompt = cs.build_prompt(swap, chars)
        self.assertIn("<Subject 1> is Suit man: bald, round sunglasses, black suit. Suit man replaces the man on the "
                      "left and the man in the close-up in <Video 1>.", prompt)
        self.assertIn("<Picture 1> shows <Subject 1>, <Picture 2> shows <Subject 2>", prompt)
        self.assertIn("a hard cut", prompt)
        self.assertNotIn("matching <Picture", prompt)
        graph = cs.build_graph(swap, {"source": "s.mp4", "refs": [("a.png", None), ("b.png", None)]}, prompt)
        self.assertEqual(graph["set"]["11.pins"], "")
        self.assertEqual(graph["set"]["11.ref_2"], ["10", 0])
        self.assertEqual(graph["add"]["30"]["inputs"]["attention"], "comfy kitchen attention")

    def test_painted_prompt_pins_each_shot_frame(self):
        swap = cs.set_marks(self.swap["id"], self.marks(), "painted")
        chars = {c["id"]: c for c in cs.list_characters()}
        prompt = cs.build_prompt(swap, chars)
        self.assertIn("matching <Picture 2> at 00:03.833", prompt)
        graph = cs.build_graph(swap, {"source": "s.mp4", "refs": [("p0.png", 30), ("p1.png", 92)]}, prompt)
        self.assertEqual(graph["set"]["11.pins"], "30, 92")
        one = cs.build_graph(swap, {"source": "s.mp4", "refs": [("p0.png", 30)]}, prompt)
        self.assertIn("10", one["remove"])
        self.assertIn("11.ref_2", one["unset"])

    def test_your_own_painted_frame_is_fitted_and_completes_the_review(self):
        cs.set_marks(self.swap["id"], self.marks(), "painted")
        upload = self.root / "mine.png"
        Image.new("RGB", (1000, 1000), (0, 200, 0)).save(upload)
        swap = cs.set_painted(self.swap["id"], 0, upload.read_bytes())
        self.assertEqual(swap["status"], "marking")       # shot 2 still needs a painted frame
        swap = cs.set_painted(self.swap["id"], 1, upload.read_bytes())
        self.assertEqual(swap["status"], "review")
        with Image.open(cs.SWAPS / self.swap["id"] / "shot1_painted.png") as im:
            self.assertEqual(im.size, (320, 180))
        self.assertEqual(swap["shots"][1]["painted_by"], "user")
        with self.assertRaises(ValueError):
            cs.set_painted(self.swap["id"], 0, b"not an image")

    def test_delete_removes_the_swap_but_not_while_codex_paints(self):
        cs._set(self.swap["id"], status="preparing")
        with self.assertRaisesRegex(ValueError, "still painting"):
            cs.delete_swap(self.swap["id"])
        cs._set(self.swap["id"], status="marking")
        cs.delete_swap(self.swap["id"])
        self.assertEqual(cs.list_swaps(), [])
        self.assertFalse((cs.SWAPS / self.swap["id"]).exists())
        with self.assertRaises(KeyError):
            cs.delete_swap(self.swap["id"])
        with self.assertRaises(KeyError):
            cs.delete_swap("../../etc")

    def test_only_isolated_jumps_are_cuts(self):
        self.assertEqual(cs.isolated_cuts([60], 124), [60])
        self.assertEqual(cs.isolated_cuts([60, 100], 124), [60, 100])
        self.assertEqual(cs.isolated_cuts(list(range(194, 227, 4)) + [300], 432), [300])   # camera swing + one cut
        self.assertEqual(cs.isolated_cuts([5, 120], 124), [])                                # no 0.2 s shots

    def test_long_clips_chain_windows_that_end_on_the_last_frame(self):
        self.assertEqual(cs.plan_windows(100), [(0, 90)])
        self.assertEqual(cs.plan_windows(124), [(0, 124)])
        self.assertEqual(cs.plan_windows(432), [(0, 124), (107, 124), (214, 124), (308, 124)])
        self.assertEqual(cs.plan_windows(231), [(0, 124), (107, 124)])
        for total in range(125, 481):
            windows = cs.plan_windows(total)
            self.assertEqual(windows[-1][0] + windows[-1][1], total)
            keeps = cs.keep_ranges(windows)
            covered = [w[0] + a for w, (a, b) in zip(windows, keeps) for a in range(a, b)]
            self.assertEqual(covered, list(range(total)))            # every frame exactly once, in order
            for (s0, n0), (s1, n1) in zip(windows, windows[1:]):
                self.assertTrue(s0 < s1 and s1 + cs.LOCK <= s0 + n0)  # locked frames come from the previous window
                self.assertIn(n1, (90, 107, 124))

    def _long_swap(self, mode):
        swap = dict(self.swap, windows=[[0, 124], [107, 124], [214, 124], [308, 124]], frames=432, seconds=18.0,
                    shots=[{"index": 0, "start": 0, "end": 432, "key_frame": 62, "frame": "shot0_frame.png"}])
        (cs.SWAPS / swap["id"] / "swap.json").write_text(json.dumps(swap), encoding="utf-8")
        marks = [{"shot": 0, "x": 0.75, "y": 0.2, "character_id": self.suit["id"], "description": "the white-haired man"},
                 {"shot": 0, "x": 0.25, "y": 0.2, "character_id": self.hippie["id"], "description": "the bearded man"}]
        return cs.set_marks(swap["id"], marks, mode)

    def test_one_graph_chains_the_windows_and_joins_with_the_source_sound(self):
        swap = self._long_swap("reference")
        chars = {c["id"]: c for c in cs.list_characters()}
        views = [cs.window_view(swap, k) for k in range(4)]
        self.assertIn("continuing seamlessly from the previous take", cs.build_prompt(views[1], chars))
        self.assertNotIn("continuing seamlessly", cs.build_prompt(views[0], chars))
        # people are listed left to right, from where they were tapped
        self.assertIn("from left to right, <Subject 2> in place of the bearded man; <Subject 1> in place of the "
                      "white-haired man", cs.build_prompt(views[0], chars))
        windows = [{"start": s, "frames": n, "refs": [("a.png", None), ("b.png", None)], "prompt": f"p{k}"}
                   for k, (s, n) in enumerate(swap["windows"])]
        g = cs.multi_window_graph(windows, 5, "swap_x_source.mp4")
        add, sets = g["add"], g["set"]
        self.assertEqual(sets["7.file"], "swap_x_source.mp4")      # the user's clip, not the shipped example
        self.assertEqual(sets["11.source"], ["w0_src", 0])
        self.assertEqual(add["w0_src"]["inputs"], {"image": ["8", 0], "batch_index": 0, "length": 124})
        self.assertEqual(add["w3_aud"]["inputs"]["start_index"], 308 / 24)
        self.assertEqual(add["w1_prefix"]["inputs"]["prefix"], ["17", 0])
        self.assertEqual(add["w1_prefix"]["inputs"]["prefix_at"], 107)
        self.assertEqual(add["w3_prefix"]["inputs"]["prefix"], ["w2_decode", 0])
        self.assertEqual(add["w3_prefix"]["inputs"]["prefix_at"], 94)
        self.assertEqual(add["w2_noise"]["inputs"]["seed"], 7)
        self.assertEqual(add["w0_keep"]["inputs"]["length"], 124)
        self.assertEqual((add["w3_keep"]["inputs"]["batch_index"], add["w3_keep"]["inputs"]["length"]), (17, 107))
        self.assertEqual(sets["19.images"], ["join3", 0])
        self.assertEqual(add["final_aud"]["inputs"]["duration"], 18.0)
        self.assertIn("18", g["remove"])

    def test_the_final_graph_reads_only_the_swaps_own_files(self):
        from backend.workflows import graph_spec_workflow as lab_graph_workflow
        windows = [{"start": s, "frames": n, "refs": [("swap_char_a.png", None)], "prompt": "p"}
                   for s, n in cs.plan_windows(432)]
        nodes = lab_graph_workflow(cs.multi_window_graph(windows, 1, "swap_x_source.mp4"), "out")
        files = [n["inputs"].get("file") or n["inputs"].get("image") for n in nodes.values()
                 if n["class_type"] in ("LoadVideo", "LoadImage")]
        self.assertEqual(sorted(files), ["swap_char_a.png", "swap_x_source.mp4"])
        for node in nodes.values():                                   # every link points at a real node
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                    self.assertIn(value[0], nodes)
        single = lab_graph_workflow({**cs.build_graph(self.swap, {"source": "swap_y.mp4", "refs": [("swap_c.png", None)]}, "p")}, "o")
        self.assertEqual(sorted(n["inputs"].get("file") or n["inputs"].get("image") for n in single.values()
                                if n["class_type"] in ("LoadVideo", "LoadImage")), ["swap_c.png", "swap_y.mp4"])

    def _parts_swap(self, scenes, total):
        windows = cs.plan_windows(total)
        parts = cs.make_parts(windows, scenes)
        for part in parts:
            part["frame"] = f"shot{part['index']}_frame.png"
            Image.new("RGB", (320, 180)).save(cs.SWAPS / self.swap["id"] / part["frame"])
        swap = dict(self.swap, windows=windows, scenes=scenes, shots=parts, frames=total, seconds=round(total / 24, 2))
        (cs.SWAPS / swap["id"] / "swap.json").write_text(json.dumps(swap), encoding="utf-8")
        return swap

    def test_a_long_shot_is_split_into_parts_with_their_own_frames(self):
        swap = self._parts_swap([{"start": 0, "end": 300}, {"start": 300, "end": 432}], 432)
        parts = [(p["start"], p["end"], p["scene"], p["window"]) for p in swap["shots"]]
        self.assertEqual(parts, [(0, 124, 0, 0), (124, 231, 0, 1), (231, 300, 0, 2), (300, 325, 1, 2),
                                 (325, 432, 1, 3)])
        windows = swap["windows"]
        for p in swap["shots"]:                                  # key frames come after the locked frames
            self.assertGreaterEqual(p["key_frame"] - windows[p["window"]][0], 0 if p["window"] == 0 else cs.LOCK)

    def test_marks_carry_over_inside_a_shot_until_nobody_is_there(self):
        swap = self._parts_swap([{"start": 0, "end": 300}, {"start": 300, "end": 432}], 432)
        mark = {"shot": 0, "x": 0.7, "y": 0.2, "character_id": self.suit["id"], "description": "the white-haired man"}
        swap = cs.set_marks(swap["id"], [mark], "reference", "", "viggle", empty=[2])
        people = [len(cs._shot_marks(swap, i)) for i in range(5)]
        self.assertEqual(people, [1, 1, 0, 0, 0])               # part 3 "nobody here"; shot 2 starts with nobody
        self.assertTrue(cs._shot_marks(swap, 1)[0]["inherited"])
        chars = {c["id"]: c for c in cs.list_characters()}
        view = cs.window_view(swap, 1)
        self.assertEqual(len(view["marks"]), 1)
        self.assertIn("in place of the white-haired man", cs.build_prompt(view, chars))
        with self.assertRaisesRegex(ValueError, "Nobody to swap in"):
            cs._window_spec(swap, 2, False, chars)

    def test_painted_frames_pin_in_their_own_window(self):
        swap = self._parts_swap([{"start": 0, "end": 432}], 432)
        marks = [{"shot": i, "x": 0.7, "y": 0.2, "character_id": self.suit["id"], "description": "the man"}
                 for i in range(4)]
        swap = cs.set_marks(swap["id"], marks, "painted")
        for part in swap["shots"]:
            part["painted"] = f"shot{part['index']}_frame.png"
        chars = {c["id"]: c for c in cs.list_characters()}
        with patch.object(cs, "INPUT", self.root):
            specs = [cs._window_spec(swap, k, True, chars) for k in range(4)]
        local_keys = [p["key_frame"] - swap["windows"][p["window"]][0] for p in swap["shots"]]
        self.assertEqual([s["refs"][0][1] for s in specs], local_keys)
        self.assertTrue(all(k >= cs.LOCK for k in local_keys[1:]))
        self.assertIn(f"matching <Picture 1> at {cs.ts(local_keys[1])}", specs[1]["prompt"])

    def test_a_part_can_be_split_where_people_change(self):
        swap = self._parts_swap([{"start": 0, "end": 432}], 432)
        marks = [{"shot": 0, "x": 0.7, "y": 0.2, "character_id": self.suit["id"], "description": "the white-haired man"},
                 {"shot": 3, "x": 0.3, "y": 0.2, "character_id": self.hippie["id"], "description": "the bearded man"}]
        cs.set_marks(swap["id"], marks, "painted")
        folder = cs.SWAPS / swap["id"]
        Image.new("RGB", (320, 180), (9, 9, 9)).save(folder / "shot3_painted.png")
        cs._set(swap["id"], shots=[{**p, "painted": "shot3_painted.png"} if p["index"] == 3 else p for p in swap["shots"]])
        source = folder / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=24:d=18",
                        "-pix_fmt", "yuv420p", str(source)], check=True)
        with self.assertRaisesRegex(ValueError, "Pick a moment"):
            cs.split_part(swap["id"], 2, 233)
        swap = cs.split_part(swap["id"], 2, 280)              # part 3 (231-325) -> 231-280 and 280-325
        self.assertEqual([(p["start"], p["end"], p["window"]) for p in swap["shots"]][2:],
                         [(231, 280, 2), (280, 325, 2), (325, 432, 3)])
        self.assertEqual([m["shot"] for m in swap["marks"]], [0, 4])     # later marks moved up by one
        self.assertEqual(swap["shots"][4]["painted"], "shot4_painted.png")
        self.assertTrue((folder / "shot4_painted.png").exists() and not (folder / "shot3_painted.png").exists())
        view = cs.window_view(swap, 2)
        self.assertEqual([(p["start"], p["end"], p["part"]) for p in view["shots"]], [(0, 66, 2), (66, 124, 3)])
        chars = {c["id"]: c for c in cs.list_characters()}
        self.assertIn("the same shot continues", cs.build_prompt(view, chars))
        self.assertIn("single continuous shot with no cut", cs.build_prompt(view, chars))

    def test_codex_keeps_every_painted_part_when_one_is_refused(self):
        swap = self._parts_swap([{"start": 0, "end": 432}], 432)
        marks = [{"shot": i, "x": 0.5, "y": 0.3, "character_id": self.suit["id"], "description": "the man"}
                 for i in range(4)]
        cs.set_marks(swap["id"], marks, "painted")

        def paint(folder, swap, shot, people, characters):
            if shot["index"] == 2:
                raise RuntimeError("Codex returned no image (blocked: public figure)")
            return f"shot{shot['index']}_painted.png"

        with patch.object(cs, "_paint", side_effect=paint):
            cs._prepare(swap["id"])
        swap = cs.get_swap(swap["id"])
        self.assertEqual([p.get("painted") for p in swap["shots"]],
                         ["shot0_painted.png", "shot1_painted.png", None, "shot3_painted.png"])
        self.assertEqual(swap["status"], "marking")
        self.assertIn("part 3: Codex returned no image (blocked: public figure)", swap["error"])
        with patch.object(cs, "_paint", side_effect=paint) as again:   # a second run paints only what is missing
            cs._prepare(swap["id"])
        self.assertEqual([c.args[2]["index"] for c in again.call_args_list], [2])

    def test_later_parts_are_painted_from_the_first_painted_version_of_each_character(self):
        swap = self._parts_swap([{"start": 0, "end": 432}], 432)
        marks = [{"shot": 0, "x": 0.3, "y": 0.3, "character_id": self.hippie["id"], "description": "the bearded man"},
                 {"shot": 2, "x": 0.3, "y": 0.3, "character_id": self.hippie["id"], "description": "the bearded man"},
                 {"shot": 2, "x": 0.7, "y": 0.3, "character_id": self.suit["id"], "description": "the other man"}]
        cs.set_marks(swap["id"], marks, "painted")
        folder = cs.SWAPS / swap["id"]
        Image.new("RGB", (320, 180)).save(folder / "shot0_painted.png")
        cs._set(swap["id"], shots=[{**p, "painted": "shot0_painted.png"} if p["index"] == 0 else p
                                   for p in cs.get_swap(swap["id"])["shots"]])
        swap = cs.get_swap(swap["id"])
        self.assertEqual(cs.consistency_frame(swap, 2, self.hippie["id"]), "shot0_painted.png")
        self.assertIsNone(cs.consistency_frame(swap, 2, self.suit["id"]))       # not painted anywhere yet
        seen = {}
        with patch.object(cs, "_codex_image", side_effect=lambda task, images, *a: seen.update(task=task, images=images)):
            cs._marked_image(folder, swap["shots"][2], cs._own_marks(swap, 2))
            cs._paint(folder, swap, swap["shots"][2], cs._people(swap), {c["id"]: c for c in cs.list_characters()})
        self.assertIn(folder / "shot0_painted.png", seen["images"])
        self.assertEqual(seen["task"].count("already painted"), 1)

    def test_rerender_from_a_part_keeps_the_start_and_opens_with_it(self):
        swap = self._parts_swap([{"start": 0, "end": 432}], 432)
        marks = [{"shot": 0, "x": 0.3, "y": 0.3, "character_id": self.hippie["id"], "description": "the bearded man"}]
        cs.set_marks(swap["id"], marks, "reference")
        with self.assertRaisesRegex(ValueError, "no finished render"):
            cs.rerender_from(swap["id"], 1)
        previous = self.root / "done.mp4"
        previous.write_bytes(b"x")
        cs._set(swap["id"], status="done", last_output=str(previous))
        with patch.object(cs, "INPUT", self.root), patch.object(cs, "_submit_segment", return_value={}) as submit:
            cs.rerender_from(swap["id"], 1)                       # part 2 sits in window 2 (starts at frame 107)
        submit.assert_called_once_with(swap["id"], 0)
        swap = cs.get_swap(swap["id"])
        self.assertEqual(swap["head"]["frames"], 107 + cs.LOCK)    # the old video is kept up to 124
        self.assertEqual([s["windows"] for s in swap["segments"]], [[1, 2, 3]])
        self.assertEqual(swap["segments"][0]["keep"][0], 124)       # the new part starts right where the old one ends
        self.assertEqual(swap["segments"][0]["prefix"]["at"], 107)  # and opens with the old video's frames 107-123
        self.assertIsNone(swap["built"][0])
        with patch.object(cs, "INPUT", self.root), patch.object(cs, "_submit_segment", return_value={}):
            cs._set(swap["id"], status="done")
            cs.rerender_from(swap["id"], 1, only=True)            # window 2 alone, the old video around it
        swap = cs.get_swap(swap["id"])
        self.assertEqual([s["windows"] for s in swap["segments"]], [[1]])
        self.assertEqual(swap["segments"][0]["keep"], [124, 231])
        self.assertEqual(swap["tail"]["from"], 231)

    def test_cut_keeps_exactly_the_frames_at_24_fps(self):
        source = self.root / "src.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=18", "-f", "lavfi", "-i",
                        "testsrc=s=64x112:r=24:d=18", "-map", "0:a", "-map", "1:v", "-pix_fmt", "yuv420p",
                        "-video_track_timescale", "12288", str(source)], check=True)
        out = self.root / "cut.mp4"
        cs._cut(source, 107, 231, out)
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries",
                                "stream=r_frame_rate,nb_read_frames", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(probe, ["24/1,124"])                     # 2026-11-09: 25 fps and 128 frames before the fix

    def test_long_clips_run_as_a_chain_of_jobs(self):
        windows = cs.plan_windows(24 * 60)                       # one minute
        segments = cs.plan_segments(windows)
        self.assertEqual([len(s["windows"]) for s in segments], [4, 4, 4, 2])
        covered = [f for s in segments for f in range(*s["keep"])]
        self.assertEqual(covered, list(range(24 * 60)))          # the jobs' videos join without overlap
        for a, b in zip(segments, segments[1:]):                  # each job's first window opens inside the previous video
            start = windows[b["windows"][0]][0]
            self.assertTrue(a["keep"][0] <= start and start + cs.LOCK == a["keep"][1])
        wins = [{"start": 0, "frames": 124, "refs": [("a.png", None)], "prompt": "p"},
                {"start": 107, "frames": 124, "refs": [("a.png", None)], "prompt": "p"}]
        g = cs.multi_window_graph(wins, 1, "part1.mp4", [(17, 124), (17, 124)], {"file": "part0_out.mp4", "at": 304},
                                  (17 / 24, 214 / 24))
        self.assertEqual(g["set"]["16.latent_image"], ["w0_prefix", 0])
        self.assertEqual(g["add"]["w0_prefix"]["inputs"]["prefix_at"], 304)
        self.assertEqual(g["add"]["p_load"]["inputs"]["file"], "part0_out.mp4")
        self.assertEqual(g["add"]["w0_keep"]["inputs"]["batch_index"], 17)
        from backend.workflows import graph_spec_workflow as lab_graph_workflow
        nodes = lab_graph_workflow(g, "out")
        for node in nodes.values():                               # every link points at a real node
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                    self.assertIn(value[0], nodes)

    def test_the_watcher_moves_from_part_to_part_and_then_joins(self):
        swap = self._parts_swap([{"start": 0, "end": 24 * 30}], 24 * 30)
        segments = cs.plan_segments(cs.windows_of(swap))
        self.assertEqual(len(segments), 2)
        segments[0]["job_id"] = "job0"
        cs._set(swap["id"], status="rendering", job_id="job0", segments=segments)
        jobs = {"job0": {"status": "completed", "output_path": "D:/out0.mp4"}}
        started = []

        def next_part(sid, k):
            started.append(k)
            segs = cs.get_swap(sid)["segments"]
            segs[k]["job_id"] = f"job{k}"
            return cs._set(sid, job_id=f"job{k}", segments=segs)

        with patch.object(cs, "_submit_segment", side_effect=next_part), \
                patch.object(cs, "_finish", side_effect=lambda sid: cs._set(sid, final_job="final", job_id="final")):
            cs.follow(lambda job_id, public=True: jobs.get(job_id))
            self.assertEqual(started, [1])
            self.assertEqual(cs.get_swap(swap["id"])["segments"][0]["output"], "D:/out0.mp4")
            cs.follow(lambda job_id, public=True: jobs.get(job_id))                                  # job1 not finished yet: nothing happens
            self.assertEqual(started, [1])
            jobs["job1"] = {"status": "completed", "output_path": "D:/out1.mp4"}
            cs.follow(lambda job_id, public=True: jobs.get(job_id))
            self.assertEqual(cs.get_swap(swap["id"])["final_job"], "final")
            jobs["final"] = {"status": "completed", "output_path": "D:/full.mp4"}
            cs.follow(lambda job_id, public=True: jobs.get(job_id))
        self.assertEqual(cs.get_swap(swap["id"])["status"], "done")
        jobs["job9"] = {"status": "failed", "error": "boom"}
        cs._set(swap["id"], status="rendering", job_id="job9")
        cs.follow(lambda job_id, public=True: jobs.get(job_id))
        self.assertEqual((cs.get_swap(swap["id"])["status"], cs.get_swap(swap["id"])["error"]), ("failed", "boom"))

    def test_akatz_takes_one_person_and_picks_by_where_you_tapped(self):
        with self.assertRaisesRegex(ValueError, "one person"):
            cs.set_marks(self.swap["id"], self.marks()[:2], "reference", "", "akatz")
        swap = cs.set_marks(self.swap["id"], self.marks()[:1], "reference", "", "akatz")
        self.assertEqual(swap["engine"], "akatz")
        self.assertEqual(cs._pick(0.2), "leftmost")
        self.assertEqual(cs._pick(0.5), "largest")
        self.assertEqual(cs._pick(0.9), "rightmost")
        prompt = cs.akatz_prompt(swap["marks"][0], self.suit)
        self.assertIn("Replace the man on the left in <Video 1> with the character in <Picture 1>", prompt)
        g = cs.akatz_graph({"source": "s.mp4", "ref": "r.png"}, {**swap["marks"][0], "pick": "leftmost"}, prompt,
                           2 ** 40 + 3, 18.0)
        self.assertEqual(g["set"]["select.selection"], "leftmost")
        self.assertEqual(g["set"]["plan.seed"], 3)
        self.assertEqual(g["set"]["prepare.duration_seconds"], 18.0)
        # the card says how many windows akatz's own planner renders (checked against H3 Relay's plan_windows)
        self.assertEqual([cs.akatz_windows(n) for n in (90, 124, 125, 247, 432)], [1, 1, 2, 2, 4])


if __name__ == "__main__":
    unittest.main()
