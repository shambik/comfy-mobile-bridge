# Runtime layout

The default local layout is:

    repo/
    ├── .runtime/
    │   ├── comfyui/
    │   │   └── custom_nodes/
    │   ├── models/
    │   │   ├── diffusion_models/
    │   │   ├── text_encoders/
    │   │   ├── vae/
    │   │   ├── loras/
    │   │   └── clip_projections/
    │   └── python/
    ├── state/
    └── config.local.json

config.example.json is the safe template. config.local.json can contain
absolute paths only for a temporary migration of an existing installation. It
must remain ignored and must never be copied into a commit.
