"""Upload both Fluffies Episode 04 cuts to the Video Vault via Bridge API."""
import hashlib
import json
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[2]
EP_DIR = ROOT / 'state' / 'fluffies_ep04_scooter_race'
BASE = 'http://127.0.0.1:8787'


def session():
    client = requests.Session()
    res = client.get(BASE + '/api/session', timeout=30)
    res.raise_for_status()
    client.headers['X-CSRF-Token'] = res.json()['csrf_token']
    return client


def upload_video(client, path: Path, title: str):
    print(f"\nUploading to Video Vault: '{title}' ({path.name})...")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    # Check if already in vault
    res = client.get(BASE + '/api/video-vault', timeout=30)
    res.raise_for_status()
    vault_items = res.json().get('items', [])
    existing = next((i for i in vault_items if i.get('sha256') == sha256), None)
    if existing:
        print(f"Already in vault! ID: {existing['id']}")
        return existing

    with path.open('rb') as f:
        files = {'video': (path.name, f, 'video/mp4')}
        data = {'name': title}
        post_res = client.post(BASE + '/api/video-vault', files=files, data=data, timeout=300)
        post_res.raise_for_status()
        item = post_res.json()
        print(f"Upload complete! ID: {item.get('id')}, Duration: {item.get('duration')}s")
        return item


def main():
    client = session()

    # 1. Version 1: Full Scenes 89s
    v1_path = EP_DIR / 'Fluffies_The_Big_Scooter_Race_v1_full_scenes_89s.mp4'
    assert v1_path.exists(), f"V1 file missing at {v1_path}"
    v1_title = 'Fluffies - Episode 04 - The Big Scooter Race - v1 Full Scenes 89s.mp4'
    v1_res = upload_video(client, v1_path, v1_title)
    (EP_DIR / 'Fluffies_The_Big_Scooter_Race_v1_vault.json').write_text(json.dumps(v1_res, indent=2), encoding='utf-8')

    # 2. Version 2: Motion Trimmed + Outro
    v2_path = EP_DIR / 'Fluffies_The_Big_Scooter_Race.mp4'
    assert v2_path.exists(), f"V2 file missing at {v2_path}"
    v2_title = 'Fluffies - Episode 04 - The Big Scooter Race - Motion Trimmed Complete with Outro 91s.mp4'
    v2_res = upload_video(client, v2_path, v2_title)
    (EP_DIR / 'Fluffies_The_Big_Scooter_Race_v2_vault.json').write_text(json.dumps(v2_res, indent=2), encoding='utf-8')

    print("\n=======================================================")
    print("Both Fluffies Episode 04 cuts published to Video Vault:")
    print(f"V1 Vault ID: {v1_res.get('id')} - {v1_title}")
    print(f"V2 Vault ID: {v2_res.get('id')} - {v2_title}")
    print("=======================================================")


if __name__ == '__main__':
    main()
