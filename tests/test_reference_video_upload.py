import asyncio
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from backend.main import save_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class ReferenceVideoUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="h3-reference-upload-")
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def make_video(self, frames: int) -> Path:
        path = self.root / f"source_{frames}.mp4"
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=15",
             "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "64k", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def probe(self, path: Path) -> dict:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,nb_frames",
             "-of", "json", str(path)], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def upload(self, source: Path):
        media = UploadFile(
            file=io.BytesIO(source.read_bytes()), filename="reference.mp4",
            headers=Headers({"content-type": "video/mp4"}),
        )
        with patch("backend.main.INPUT", self.root):
            return asyncio.run(save_video(media))

    def test_native_fifteen_second_clip_with_two_extra_frames_is_normalized(self):
        source = self.make_video(362)
        self.assertGreater(float(self.probe(source)["format"]["duration"]), 15)

        saved_path, saved_name = self.upload(source)
        self.assertEqual(Path(saved_path).name, saved_name)
        prepared = self.probe(Path(saved_path))
        self.assertAlmostEqual(float(prepared["format"]["duration"]), 15, places=3)
        video = next(stream for stream in prepared["streams"] if stream["codec_type"] == "video")
        self.assertEqual(int(video["nb_frames"]), 360)

    def test_exact_fifteen_second_video_is_kept_unchanged(self):
        source = self.make_video(360)
        self.assertLessEqual(float(self.probe(source)["format"]["duration"]), 15)
        saved_path, _ = self.upload(source)
        self.assertEqual(Path(saved_path).read_bytes(), source.read_bytes())

    def test_video_beyond_frame_overrun_is_rejected(self):
        source = self.make_video(366)
        with self.assertRaises(HTTPException) as caught:
            self.upload(source)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(list(self.root.glob("reference_video_*")), [])


if __name__ == "__main__":
    unittest.main()
