import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.comfy import media_probe
from backend.media import assemble_clips, attach_song, extract_review_frames


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
class MediaAssemblyTests(unittest.TestCase):
    def make_clip(self, path: Path, color: str, size: str, tone: int | None):
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d=0.5",
        ]
        if tone is not None:
            command += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration=0.5", "-shortest"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if tone is not None:
            command += ["-c:a", "aac", "-b:a", "96k"]
        command += [str(path)]
        subprocess.run(command, check=True, timeout=60)

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

    def test_no_audio_clips_join_without_creating_an_audio_track(self):
        with tempfile.TemporaryDirectory(prefix="h3-no-audio-test-") as temp:
            root = Path(temp)
            first = root / "first.mp4"
            second = root / "second.mp4"
            output = root / "joined.mp4"
            self.make_clip(first, "red", "512x288", None)
            self.make_clip(second, "blue", "736x416", None)

            assemble_clips([first, second], output)
            probe = media_probe(output, require_audio=False)
            self.assertFalse(any(stream["codec_type"] == "audio" for stream in probe["streams"]))

    def test_review_frames_and_original_song_mux(self):
        with tempfile.TemporaryDirectory(prefix="h3-final-test-") as temp:
            root = Path(temp)
            video = root / "silent.mp4"
            song = root / "song.wav"
            output = root / "final.mp4"
            self.make_clip(video, "purple", "512x288", None)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                "sine=frequency=330:sample_rate=48000:duration=0.5", str(song),
            ], check=True, timeout=60)
            frames = extract_review_frames(video, root / "frames", fps=2, limit=4)
            self.assertGreaterEqual(len(frames), 1)
            result = attach_song(video, song, output)
            self.assertTrue(output.exists())
            self.assertTrue(any(stream["codec_type"] == "audio" for stream in result["ffprobe"]["streams"]))


if __name__ == "__main__":
    unittest.main()
