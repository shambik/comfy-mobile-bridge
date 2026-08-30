"""Isolated multi-agent Council pipeline.

Legacy production orchestration intentionally remains in ``backend.production``.
Council modules may share low-level infrastructure, but never Legacy state
transitions.
"""

COUNCIL_PIPELINE = "council_music_video_v1"
LEGACY_PIPELINE = "legacy_music_video_v1"
