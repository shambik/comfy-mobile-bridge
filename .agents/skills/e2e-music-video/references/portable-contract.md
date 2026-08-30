# Portable contract

Drive the pipeline with a JSON project manifest. Paths may be Windows or POSIX paths.

```json
{
  "bridge": "http://127.0.0.1:8787",
  "song": "song.wav",
  "lyrics": "lyrics.txt",
  "output_dir": "project-output",
  "mode": "hybrid",
  "song_duration": 154.64,
  "shots": [
    {"id":"intro-01","mode":"t2v","duration":10,"resolution":"1120x640","section":"intro","prompt":"...","continuity":"fresh"},
    {"id":"verse-01","mode":"i2v","duration":15,"resolution":"960x544","section":"verse 1","prompt":"...","continuity":"agy_decides","anchor":"kofi_face.jpg"}
  ]
}
```

`mode` can be `sequential`, `segmented`, `independent`, `hybrid`, or `single`. `continuity` can be `fresh`, `previous_last_frame`, `anchor`, or `agy_decides`.

An AGY QC adapter should receive shot metadata, video path, extracted frame paths, previous QC result, and next-shot requirements. It should return JSON with `approved`, `reason`, and optionally `next_input` (`last_frame`, `anchor`, or a frame path).
