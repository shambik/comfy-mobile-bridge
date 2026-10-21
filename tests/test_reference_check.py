import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
from PIL import Image, ImageDraw

import backend.db as db_module
from backend.reference_check import sheet_frames
from backend.worker import LTX_REFERENCE_ATTEMPTS, QueueWorker, ReferenceSheetShown


def make_sheet(path: Path) -> Path:
    """A 16:9 reference sheet: five coloured panels split by black gutters."""
    sheet = Image.new("RGB", (1600, 900), "black")
    draw = ImageDraw.Draw(sheet)
    for box, colour in (((10, 10, 520, 440), (200, 120, 60)), ((540, 10, 1060, 440), (150, 110, 200)),
                        ((1080, 10, 1590, 440), (210, 90, 40)), ((10, 460, 400, 890), (40, 200, 190)),
                        ((420, 460, 1590, 890), (40, 60, 160))):
        draw.rectangle(box, fill=colour)
    sheet.save(path)
    return path


def make_clip(path: Path, sheet: Path, sheet_count: int, scene_count: int, *,
              collage: bool = False, cinema_bars: bool = False) -> Path:
    """An MP4 whose first frames show the letterboxed sheet (or a collage of it), then a scene."""
    grid = Image.new("RGB", (768, 448))
    with Image.open(sheet) as image:
        grid.paste(image.convert("RGB").resize((768, 432)), (0, 8))
    sheet_frame = np.asarray(grid.resize((1536, 896))).copy()
    rng = np.random.default_rng(3)
    scene = np.clip(rng.normal(110, 40, (896, 1536, 3)), 25, 255).astype(np.uint8)
    if collage:
        # Sheet panels on the left, the animated scene filling the right side.
        sheet_frame[:, 560:] = scene[:, 560:]
    if cinema_bars:
        scene[:40] = 0
        scene[-40:] = 0
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 1536, 896, "yuv420p"
        for index in range(sheet_count + scene_count):
            frame = av.VideoFrame.from_ndarray(sheet_frame if index < sheet_count else scene, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


class SheetFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-sheet-check-")
        self.root = Path(self.temp.name)
        self.sheet = make_sheet(self.root / "sheet.png")

    def tearDown(self):
        self.temp.cleanup()

    def test_flags_exactly_the_opening_sheet_frames(self):
        result = sheet_frames(make_clip(self.root / "bad.mp4", self.sheet, 6, 18), self.sheet)
        self.assertTrue(result["shows_sheet"])
        self.assertEqual(result["sheet_frames"], list(range(6)))
        self.assertEqual(result["frames"], 24)

    def test_flags_a_collage_of_sheet_panels_and_scene(self):
        result = sheet_frames(make_clip(self.root / "collage.mp4", self.sheet, 8, 16, collage=True), self.sheet)
        self.assertEqual(result["sheet_frames"], list(range(8)))

    def test_clean_scene_passes(self):
        result = sheet_frames(make_clip(self.root / "good.mp4", self.sheet, 0, 24), self.sheet)
        self.assertFalse(result["shows_sheet"])
        self.assertEqual(result["sheet_frames"], [])
        self.assertEqual((result["max_matching_cells"], result["max_gutter_lines"]), (0, 0))

    def test_cinema_bars_on_a_real_scene_are_not_a_sheet(self):
        result = sheet_frames(make_clip(self.root / "bars.mp4", self.sheet, 0, 24, cinema_bars=True), self.sheet)
        self.assertFalse(result["shows_sheet"])


class ReferenceRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-sheet-retry-")
        self.root = Path(self.temp.name)
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        db_module.init_db()
        with closing(sqlite3.connect(db_module.DB_PATH)) as connection:
            connection.execute(
                """INSERT INTO jobs (id,prompt,mode,duration,engine,ltx_reference_model,turbo_profile,encoder,steps,
                   width,height,aspect_ratio,seed,status,position,reference_images_json,created_at,updated_at)
                   VALUES ('job','p','reference',5,'ltx','2.5','v1','native',8,1536,896,'16:9','100','queued',1,
                   '["sheet.png"]','t','t')""")
            connection.commit()
        self.worker = QueueWorker()

    def tearDown(self):
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    def job(self):
        return db_module.get_job("job", public=False)

    def run_with(self, outcomes):
        seeds = []

        async def fake_run_job(job, recovered_prompt=None, reference_retries=None):
            seeds.append(job["seed"])
            outcome = outcomes[len(seeds) - 1]
            if outcome == "sheet":
                video = self.root / f"h3_bridge_job_{len(seeds):05d}_.mp4"
                video.write_bytes(b"render")
                raise ReferenceSheetShown(video, {"sheet_frames": [0, 1, 2]})
            db_module.update_job(job["id"], status="completed", phase="completed",
                                 metrics={"reference_retries": reference_retries})

        with patch.object(self.worker, "run_job", side_effect=fake_run_job):
            asyncio.run(self.worker._execute_job(self.job()))
        return seeds

    def test_sheet_renders_are_set_aside_and_re_rendered_with_new_seeds(self):
        seeds = self.run_with(["sheet", "sheet", "clean"])
        self.assertEqual(len(seeds), 3)
        self.assertEqual(len(set(seeds)), 3)
        job = self.job()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["seed"], seeds[-1])
        self.assertEqual(sorted(p.name for p in self.root.glob("rejected*.mp4")),
                         ["rejected1_h3_bridge_job_00001_.mp4", "rejected2_h3_bridge_job_00002_.mp4"])
        self.assertFalse(list(self.root.glob("h3_bridge_job_*.mp4")))

    def test_gives_up_with_a_clear_error_after_the_attempt_limit(self):
        seeds = self.run_with(["sheet"] * LTX_REFERENCE_ATTEMPTS)
        self.assertEqual(len(seeds), LTX_REFERENCE_ATTEMPTS)
        job = self.job()
        self.assertEqual(job["status"], "failed")
        self.assertIn("kept showing the reference sheet", job["error"])
        self.assertEqual(len(list(self.root.glob("rejected*.mp4"))), LTX_REFERENCE_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
