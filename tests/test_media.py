import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.comfy import media_probe
from backend.media import assemble_clips


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
class MediaAssemblyTests(unittest.TestCase):
    def make_clip(self, path: Path, color: str, size: str, tone: int):
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d=0.5",
            "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration=0.5",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", str(path),
        ], check=True, timeout=60)

    def test_mixed_resolution_clips_are_normalized_and_joined(self):
        with tempfile.TemporaryDirectory(prefix="h3-assembly-test-") as temp:
            root = Path(temp)
            first = root / "first.mp4"
            second = root / "second.mp4"
            output = root / "joined.mp4"
            self.make_clip(first, "red", "512x288", 440)
            self.make_clip(second, "blue", "736x416", 660)

            result = assemble_clips([first, second], output)
            probe = media_probe(output)
            video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (512, 288))
            self.assertEqual(result["source_count"], 2)
            self.assertGreater(float(probe["format"]["duration"]), 0.9)


if __name__ == "__main__":
    unittest.main()
