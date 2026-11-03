"""Revision after the user's frozen-start feedback: render 10s, edit 8s."""
import copy
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT/'state/fluffies_ep01_shortcut'
OUT = ROOT/'state/fluffies_ep01_shortcut_motion_v2'


def build():
    for folder in ['frames', 'clips', 'prompts']:
        (OUT/folder).mkdir(parents=True, exist_ok=True)
    spec = copy.deepcopy(json.loads((OLD/'manifest.json').read_text(encoding='utf-8')))
    spec.update(schema='execution_manifest.v1', revision='motion-v2',
                intro='state/fluffies_cast_intro_app_v4/Fluffies_All_Cast_Intro_v4_8s.mp4',
                source_revision='state/fluffies_ep01_shortcut/manifest.json',
                trim_policy='Generate ten seconds; cut the first two seconds and use eight seconds per story shot. Preserve native sound with the same trim.',
                master_filename='Fluffies_The_Great_Shortcut_Motion_v2_120s.mp4')
    for number, shot in enumerate(spec['shots']):
        old_duration = shot['duration']
        shot.update(duration=10, edit_frames=192, trim_start_frame=48,
                    start=8+number*8, end=16+number*8)
        shot['video_prompt'] = (
            'Continue the movement already suggested in the opening image immediately. '
            'No introductory freeze, posed establishing hold, stationary anticipation or slow motion. '
            'Visible body movement starts at once and flows through the whole shot. '
            + shot['video_prompt'].replace(f'During this {old_duration}-second single shot',
                                           'During this 10-second single shot'))
        frame = OUT/shot['frame']
        if not frame.exists():
            shutil.copyfile(OLD/shot['frame'], frame)
        (OUT/'prompts'/f'{shot["id"]}-video.txt').write_text(shot['video_prompt'], encoding='utf-8')
    assert sum(s['edit_frames'] for s in spec['shots']) == 2688
    assert spec['shots'][-1]['end'] == 120
    (OUT/'manifest.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    score = OUT/'shortcut_original_score_120s.wav'
    if not score.exists():
        shutil.copyfile(OLD/score.name, score)
    shutil.copyfile(OLD/'score_manifest.json', OUT/'score_manifest.json')
    print(json.dumps(dict(manifest=str(OUT/'manifest.json'), requested_seconds=140, edited_story_seconds=112, full_episode_seconds=120)))


if __name__ == '__main__':
    build()
