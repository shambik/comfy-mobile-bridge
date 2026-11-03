"""Explicit recovery of the canceled sample using the app's Fused SLA graph."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import tumble_puffs_execute as bridge
from tumble_puffs_minimax import PROMPT, proof

KEY = 'gag_02_pinwheel_fused'
OUT = bridge.OUT
DURATION = 8
SEED = 1023610


def submit():
    data = bridge.read()
    if KEY in data['items']:
        raise SystemExit('Recovery already journaled; poll it instead of repeating the POST.')
    if (OUT / 'STOPPED.json').exists():
        raise SystemExit('Recovery is stopped.')
    s = bridge.session()
    health = s.get(bridge.BASE + '/api/health', timeout=30)
    health.raise_for_status()
    if health.json().get('active_job'):
        raise SystemExit('The bridge is busy.')
    payload = {
        'prompt': PROMPT.replace('eight-second', 'five-second') if DURATION == 5 else PROMPT,
        'mode': 'opening', 'duration': str(DURATION),
        'engine': 'fused_sla', 'workflow_variant': 'direct',
        'attention_mode': 'standard',  # Fused graph already contains H3SLAAttention.
        'steps': '6', 'encoder': 'native', 'megapixels': '1.5',
        'aspect_ratio': '16:9', 'seed': str(SEED), 'no_audio': 'false',
    }
    path = Path(data['items']['opening_02_pinwheel_imagegen_v1']['path'])
    item = {
        'kind': 'video', 'status': 'submitting', 'submitted': time.time(),
        'bridge_base': bridge.BASE,
        'source': 'opening_02_pinwheel_imagegen_v1', 'payload': payload,
        'recovery_of': data['items']['gag_02_pinwheel']['id'],
        'reason': 'First forward stalled with heavy shared GPU memory. Compare existing low-VRAM fused graph; same image, prompt, seed, size, duration and steps.',
        'sparse_attention': 'Built into official Fused SLA Direct low-VRAM graph; no extra attention patch.',
    }
    data['items'][KEY] = item
    bridge.write(data)
    with path.open('rb') as f:
        parts = [(k, (None, v)) for k, v in payload.items()]
        parts.append(('image', (path.name, f, 'image/png')))
        response = s.post(bridge.BASE + '/api/jobs', files=parts, timeout=180)
    item['http_status'] = response.status_code
    item['response'] = response.json()
    if response.ok:
        item.update(id=response.json()['created'][0], status='queued')
    else:
        item['status'] = 'submission_failed'
    bridge.write(data)
    response.raise_for_status()
    print(json.dumps({'key': KEY, 'id': item['id'], 'settings': payload}), flush=True)


def finish():
    bridge.wait(KEY)
    proof(OUT / (KEY + '.mp4'))
    subprocess.run([
        os.environ['TUMBLE_PUFFS_MEDIA_PYTHON'],
        str(Path(__file__).with_name('tumble_puffs_music.py')),
        '--key', KEY,
    ], check=True)
    proof(OUT / (KEY + '_with_music.mp4'))
    print('Recovered MiniMax sample with music complete.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['submit', 'poll', 'finish'])
    parser.add_argument('--base', default=bridge.BASE)
    parser.add_argument('--key', default=KEY)
    parser.add_argument('--duration', type=int, choices=[5, 8], default=DURATION)
    parser.add_argument('--seed', type=int, default=SEED)
    args = parser.parse_args()
    bridge.BASE = args.base.rstrip('/')
    KEY = args.key
    DURATION = args.duration
    SEED = args.seed
    if args.action == 'submit':
        submit()
    elif args.action == 'poll':
        bridge.poll(KEY)
    else:
        finish()
