"""Fluffies — The Big Scooter Race: Dedicated LTX-2.5 Video Runner.

Submits opening-mode LTX jobs to the local H3 Mobile Bridge (http://127.0.0.1:8787).
For each completed shot:
- Downloads video to state/fluffies_ep04_scooter_race/clips/{id}.mp4
- Probes format and runs full ffmpeg decode proof
- Generates 1-fps contact sheet in qc/{id}_sheet.jpg for immediate visual inspection
- Updates execution.json
"""
import argparse
from contextlib import ExitStack
import json
import msvcrt
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[2]
EP_DIR = ROOT / 'state' / 'fluffies_ep04_scooter_race'
BASE = 'http://127.0.0.1:8787'


def log(**data):
    print(json.dumps(data), flush=True)


def session():
    client = requests.Session()
    response = client.get(BASE + '/api/session', timeout=30)
    response.raise_for_status()
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return client


def probe(path: Path, min_frames=None, audio=True):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(path)],
        check=True, capture_output=True
    )
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    sounds = [s for s in info['streams'] if s['codec_type'] == 'audio']
    assert video['r_frame_rate'] == '24/1', video['r_frame_rate']
    count = int(video['nb_read_frames'])
    assert min_frames is None or count >= min_frames, (count, min_frames)
    assert bool(sounds) == audio, f"Audio presence mismatch on {path}"
    # Full ffmpeg decode verification
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = {
        'path': str(path),
        'width': video['width'],
        'height': video['height'],
        'fps': 24,
        'decoded_frames': count,
        'duration': float(info['format']['duration']),
        'audio': bool(sounds),
        'full_decode': 'passed'
    }
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    return proof


def build_contact_sheet(clip_path: Path, sheet_path: Path):
    """Generate a contact sheet with 1 frame per second for visual QC."""
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y', '-i', str(clip_path),
        '-vf', 'fps=1,scale=320:-1,tile=7x1',
        str(sheet_path)
    ], check=True)


def render(preview_count=None):
    journal_path = EP_DIR / 'execution.json'

    def read_journal():
        return json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else {'items': {}, 'created': time.time()}

    def write_journal(data):
        tmp = journal_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        tmp.replace(journal_path)

    spec = json.loads((EP_DIR / 'manifest.json').read_text(encoding='utf-8'))
    shots = spec['shots'][:preview_count] if preview_count else spec['shots']
    client = session()

    for shot in shots:
        key = shot['id']
        data = read_journal()
        item = data['items'].get(key)
        if item and item.get('status') == 'verified':
            continue

        if item is None:
            frame_path = EP_DIR / shot['frame']
            while not frame_path.exists():
                if (EP_DIR / 'STOPPED.json').exists():
                    raise SystemExit('Stopped marker present.')
                log(shot=key, status='waiting_for_frame', frame=str(frame_path))
                time.sleep(10)

            # Wait for any active GPU job to complete
            while True:
                if (EP_DIR / 'STOPPED.json').exists():
                    raise SystemExit('Stopped marker present.')
                health = client.get(BASE + '/api/health', timeout=30)
                health.raise_for_status()
                if not health.json().get('active_job'):
                    break
                log(shot=key, status='waiting_for_active_bridge_job')
                time.sleep(12)

            payload = {
                'engine': 'ltx',
                'mode': 'opening',
                'steps': '8',
                'ltx_quality': 'balanced',
                'aspect_ratio': '16:9',
                'ltx_sharp_decode': 'true',
                'ltx_calm_sampler': 'true',
                'no_audio': 'false',
                'prompt': shot['video_prompt'],
                'duration': str(shot['duration']),
                'seed': str(shot['seed']),
            }

            item = {
                'status': 'submitting',
                'submitted': time.time(),
                'frame': shot['frame'],
                'payload': payload,
            }
            data['items'][key] = item
            write_journal(data)

            with ExitStack() as handles:
                parts = [(k, (None, v)) for k, v in payload.items()]
                f_img = handles.enter_context(frame_path.open('rb'))
                parts.append(('image', (f'{key}-image.png', f_img, 'image/png')))
                response = client.post(BASE + '/api/jobs', files=parts, timeout=180)

            item['http_status'] = response.status_code
            if response.ok:
                item.update(id=response.json()['created'][0], status='queued')
            else:
                item['status'] = 'submission_failed'
                item['response'] = response.text
            write_journal(data)
            response.raise_for_status()
            log(shot=key, id=item['id'], status=item['status'])

        # Poll status
        while True:
            response = client.get(BASE + '/api/jobs?limit=200&include_library=false&include_sequences=false', timeout=30)
            response.raise_for_status()
            job = next(j for j in response.json()['jobs'] if j['id'] == item['id'])
            item.update(status=job['status'], response=job)
            write_journal(data)
            log(shot=key, status=item['status'], step=job.get('step'), total_steps=job.get('total_steps'))

            if item['status'] == 'completed':
                clip_dest = EP_DIR / shot['clip']
                clip_dest.parent.mkdir(parents=True, exist_ok=True)
                if not clip_dest.exists():
                    media = client.get(f'{BASE}/api/jobs/{item["id"]}/video', timeout=180)
                    media.raise_for_status()
                    temp_file = clip_dest.with_suffix('.download')
                    temp_file.write_bytes(media.content)
                    temp_file.replace(clip_dest)

                item['proof'] = probe(clip_dest, min_frames=shot['edit_frames'], audio=True)
                sheet_dest = EP_DIR / 'qc' / f'{key}_sheet.jpg'
                build_contact_sheet(clip_dest, sheet_dest)
                item['sheet'] = str(sheet_dest)
                item['status'] = 'verified'
                write_journal(data)
                log(shot=key, status='verified', path=str(clip_dest), sheet=str(sheet_dest))
                break

            if item['status'] in {'failed', 'error', 'cancelled'}:
                raise RuntimeError(f"Shot {key} job failed with status: {item['status']}")

            time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', type=int, default=None)
    args = parser.parse_args()
    render(args.preview)
