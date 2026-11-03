"""Publish a verified music mix to the main bridge's Video Vault, once."""
import argparse
import hashlib
import json
from pathlib import Path

import tumble_puffs_execute as bridge


def publish(key, name):
    video = bridge.OUT / (key + '_with_music.mp4')
    proof = json.loads(video.with_name(video.stem + '_proof.json').read_text())
    if proof.get('full_decode') != 'passed':
        raise SystemExit('The final music mix has not passed full decode.')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    session = bridge.session()
    response = session.get(bridge.BASE + '/api/video-vault', timeout=30)
    response.raise_for_status()
    existing = next((item for item in response.json()['items']
                     if item.get('sha256') == digest and item.get('available')), None)
    record = bridge.OUT / (key + '_published.json')
    if existing is None:
        if record.exists() and json.loads(record.read_text()).get('status') == 'submitting':
            raise SystemExit('Previous upload result uncertain; inspect the vault before retrying.')
        record.write_text(json.dumps({'status': 'submitting', 'path': str(video), 'sha256': digest}, indent=2))
        with video.open('rb') as handle:
            response = session.post(bridge.BASE + '/api/video-vault',
                                    data={'name': name},
                                    files={'video': (video.name, handle, 'video/mp4')},
                                    timeout=180)
        response.raise_for_status()
        existing = response.json()
    if existing.get('sha256') != digest or not existing.get('available'):
        raise SystemExit('Vault file did not match the verified final mix.')
    record.write_text(json.dumps({'status': 'completed', 'path': str(video), 'item': existing}, indent=2))
    print(json.dumps(existing), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('key')
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    publish(args.key, args.name)
