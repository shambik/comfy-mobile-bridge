# Python pattern

    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]
    runtime = (ROOT / ".runtime").resolve()
    if not runtime.is_relative_to(ROOT):
        raise RuntimeError("runtime must stay inside the repository")

Production code should use the shared configuration module instead of
recreating this resolution. Tests may patch module constants with temporary
directories.
