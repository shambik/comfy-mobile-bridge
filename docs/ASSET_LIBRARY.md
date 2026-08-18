# Studio asset library

The Studio asset library organizes generated videos without copying them. A
project or folder selected in the UI corresponds directly to a directory on
disk, and moving or renaming an asset updates both its actual file and the
database path used by the app.

## Canonical layout

The root defaults to `state/projects` and can be overridden with
`projects_dir` in `config.json`.

```text
state/projects/
├── Belly of the Beast/
│   ├── final-cut.mp4
│   ├── Accepted shots/
│   │   ├── corner-intro.mp4
│   │   └── rover-arrival.mp4
│   └── Alternate shots/
│       └── sirens-take-2.mp4
└── Commercial demo/
    └── product-reveal.mp4
```

Projects support one folder level. This keeps paths predictable for the app,
ComfyUI, FFmpeg, agents, backups, and manual browsing.

## Behavior

- New generations can be assigned to a project and optional folder before
  they enter the queue. ComfyUI may initially render to its output directory;
  after completion the bridge moves the result to the selected location.
- Existing completed results have an **Organize** action. Moving an asset
  physically moves the video; moving it to **Unassigned** returns it to the
  configured ComfyUI output directory.
- Renaming an asset renames the real `.mp4` file. Database references used by
  job playback, connected sequences, and Production Studio attempts are kept
  synchronized.
- Renaming a project or folder renames its real directory and updates paths for
  every managed asset below it.
- Asset deletion requires browser confirmation and permanently deletes the
  real video using the existing job or sequence deletion endpoint.
- A project or folder can only be deleted when it has no managed assets. It is
  also refused if the directory contains unmanaged files.
- Windows-invalid and reserved names are rejected. Existing filenames are not
  overwritten; moves receive a numbered suffix when needed.

Unassigned historical generations remain where ComfyUI created them until the
user explicitly organizes them. The feature does not silently migrate or
duplicate existing videos.
