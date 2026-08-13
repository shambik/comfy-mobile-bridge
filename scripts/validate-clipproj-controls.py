"""Run the official ClipProj zero/identity/learned controls on local H3."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from backend.comfy import ComfyClient, find_video, media_probe  # noqa: E402
from backend.config import CLIPPROJ_PROJECTION, LOGS  # noqa: E402
from backend.workflows import turbo_workflow  # noqa: E402


CASES = (
    ("zero", "<control:zero>"),
    ("identity", "<control:identity>"),
    ("learned", CLIPPROJ_PROJECTION),
)


async def wait_for_result(client: ComfyClient, prompt_id: str, timeout: int) -> dict:
    started = time.monotonic()
    next_report = 0
    while time.monotonic() - started < timeout:
        history = await client.history(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("completed"):
                if status.get("status_str") != "success":
                    raise RuntimeError(json.dumps(status, ensure_ascii=False)[:4000])
                return history
        elapsed = int(time.monotonic() - started)
        if elapsed >= next_report:
            print(f"  waiting {elapsed}s", flush=True)
            next_report = elapsed + 10
        await asyncio.sleep(2)
    raise TimeoutError(f"ClipProj control timed out after {timeout}s")


async def run(args: argparse.Namespace) -> int:
    client = ComfyClient()
    await client.ensure_started()
    queue = await client.queue()
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue must be empty before the control run")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    results: list[dict] = []
    for label, projection in CASES:
        prefix = f"clipproj_control_{stamp}_{label}"
        workflow = turbo_workflow(
            prompt=args.prompt,
            duration=5,
            seed=args.seed,
            prefix=prefix,
            steps=args.steps,
            width=args.width,
            height=args.height,
            encoder="clipproj",
        )
        workflow["13"]["inputs"]["projection"] = projection
        print(f"[{label}] projection={projection}", flush=True)
        started = time.monotonic()
        prompt_id = await client.submit(workflow, uuid.uuid4().hex)
        history = await wait_for_result(client, prompt_id, args.timeout)
        output = find_video(prefix)
        if output is None:
            raise RuntimeError(f"No MP4 was found for {label}")
        probe = media_probe(output)
        result = {
            "label": label,
            "projection": projection,
            "prompt_id": prompt_id,
            "seconds": round(time.monotonic() - started, 1),
            "output": str(output),
            "probe": probe,
            "history_status": history.get("status", {}),
        }
        results.append(result)
        print(f"  completed in {result['seconds']}s: {output}", flush=True)
        await client.free_models()

    report = LOGS / f"clipproj-controls-{stamp}.json"
    report.write_text(
        json.dumps(
            {
                "prompt": args.prompt,
                "seed": args.seed,
                "steps": args.steps,
                "width": args.width,
                "height": args.height,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"report": str(report), "outputs": [r["output"] for r in results]}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        default=(
            "A single bright red ceramic ball rests at the center of a dark wooden table "
            "inside a quiet studio. Static camera, soft daylight, realistic video, clear room tone."
        ),
    )
    parser.add_argument("--seed", type=int, default=7319042)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=288)
    parser.add_argument("--timeout", type=int, default=1200)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
