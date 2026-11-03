"""Publish measured pilot decisions and the completed production handoff."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DOC=Path(__file__).parent
OUT=ROOT/'state'/'night_train'

def load(name):return json.loads((OUT/name).read_text())

def pilots():
    metrics=load('pilot_metrics.json');motion=load('motion_metrics.json');journal=load('execution.json')
    scores={'planned':metrics['P1a_seam']['percent_255'],'native':max(metrics['P1b_seam_1']['percent_255'],metrics['P1b_seam_2']['percent_255']),'opening_closing':metrics['P1c_seam']['percent_255']}
    method=min(scores,key=scores.get)
    decision={'chain_method':method,'seam_scores_percent_255':scores,'basis':'Smallest measured boundary MAD; full-speed visual judgement deferred to user by instruction. Native uses the worse of two joins.','motion':'stepped','motion_basis':'Documented claymation direction; subjective motion judgement deferred to user.','production_audio':'foley only; continuous bed and motif in post','review_policy':journal.get('review_policy')}
    (OUT/'pilot_decision.json').write_text(json.dumps(decision,indent=2))
    rows=['# Night Train pilot results','', 'All pilot renders use the bridge app: LTX 2.5, Balanced 1600×896, 5-second requests, 8 steps, sharp decode, generated audio. No AGY or delegated agents were used. As instructed, the user performs visual and listening review; strict inspection gates were skipped.','', '## Decisions','',f'- Chain method: **{method}**, selected by the lowest measured seam MAD. Native chaining is scored by its worse measured join.', '- Motion: **stepped stop-motion at 12 fps feel**, following the documented creative direction. This is not a verified perceptual winner.', '- Production sound: generated **foley only**, with the continuous train bed and recurring motif mixed in post. This conservative mix choice avoids adding a second generated location bed in every clip; no listening judgement is claimed.', '- C2 pantomime uses the explicitly separated physical beats from P1b_1. Readability with sound off is left to the user.','', '## P1 boundary and landing measurements','', '| Measurement | MAD, 0–255 | Percent of 255 |','| --- | ---: | ---: |']
    rows += [f"| {k} | {v['mad_0_255']:.4f} | {v['percent_255']:.4f}% |" for k,v in metrics.items()]
    rows += ['', 'MAD compares RGB pixels of the exact last decoded frame and the next clip’s first decoded frame. Landing compares the last decoded frame with K2; reference images are Lanczos resized only if their sizes differ. The plan’s ~3% number is a heuristic, not a perceptual proof. Native drift is available to review in the three-clip P1b comparison.','', '## P2 temporal measurements','', '| Clip | Mean frame delta | P10 | P90 | Fraction below 1/255 |','| --- | ---: | ---: | ---: | ---: |']
    rows += [f"| {k} | {v['mean_frame_delta_0_255']:.4f} | {v['p10']:.4f} | {v['p90']:.4f} | {v['low_motion_frame_fraction']:.4f} |" for k,v in motion.items()]
    rows += ['', 'These numerical differences do not establish handmade feel or absence of jitter.','', '## P3 sound assets and P4 review','', '- `state/night_train/location_loop_test.wav`: 10-second bed test built from repeated 5-second P3a audio with one-second crossfades.', '- `state/night_train/music_motif.wav`: approximately nine seconds, made from two P3b takes of the same five-second source with a one-second crossfade. The plan asks for 5-second pilots and an 8–10-second motif; this is an edited motif, not an 8–10-second original phrase.', '- `state/night_train/P3c_mix_check.mp4`: numerically winning pilot chain with the bed at −14 dB for user listening review.', '- `state/night_train/P1b_1.mp4`: clear C2 physical-beat test, also the stepped P2 and P4 example.', '- No Whisper or listening/visual acceptance gate was imposed, following the user’s instruction to leave inspection to them.','', '## Render ledger','', '| Asset | App ID | Seed | Generation seconds |','| --- | --- | ---: | ---: |']
    for key,item in journal['items'].items():
        if not key.startswith(('P1','P2','P3')):continue
        response=item.get('response',{});m=response.get('metrics') or {}
        if not isinstance(m,dict):m={}
        seconds=m.get('generation_seconds',response.get('generation_seconds',''))
        rows.append(f"| {key} | {item.get('id','')} | {item['payload'].get('seed','')} | {seconds} |")
    rows += ['', 'Basic proof files (`*_proof.json`) record resolution, 24 fps, decoded frame count, audio stream and a successful full FFmpeg decode for every pilot. Contact sheets and untouched source clips remain in `state/night_train/`. No GPU retry was made automatically.','', '## Review files','', '- [Keyframe contact sheet](../../state/night_train/keyframes_contact.png)', '- [All nine keyframes in one strip](../../state/night_train/keyframes_strip.png)', '- [Planned-frame chain](../../state/night_train/P1a_chain.mp4)', '- [Three-clip native chain](../../state/night_train/P1b_chain.mp4)', '- [Opening + closing chain](../../state/night_train/P1c_chain.mp4)', '- [Smooth-motion comparison](../../state/night_train/P2_smooth.mp4)', '- [Sound mix check](../../state/night_train/P3c_mix_check.mp4)','']
    (DOC/'PILOT_RESULTS.md').write_text('\n'.join(rows),encoding='utf-8')
    print(json.dumps(decision,indent=2))

def final():
    journal=load('execution.json');assembly=load('assembly_report.json');seams=load('production_seams.json')
    rows=['# Night Train — execution report','', 'The generated episode is `state/night_train/Night_Train_E01_The_Stowaway.mp4`. Visual and listening review belongs to the user; no AGY or delegated agents were used.','',f"Duration: {assembly['duration_seconds']:.3f} seconds, including two-second title and end cards. All eight production clips use LTX High, 8 steps, sharp decode and generated foley. See PILOT_RESULTS.md for the selected chain method and measurement limits.",'', '## Files','', '- [Episode](../../state/night_train/Night_Train_E01_The_Stowaway.mp4)', '- [Keyframes](../../state/night_train/keyframes_contact.png)', '- [Keyframes strip](../../state/night_train/keyframes_strip.png)', '- [Full episode 2 fps contact sheet](../../state/night_train/Night_Train_E01_The_Stowaway_contact.png)', '- [Exact submission journal](../../state/night_train/execution.json)', '- [Final media proof](../../state/night_train/Night_Train_E01_The_Stowaway_proof.json)','', '## Production seam measurements','', '| Join | MAD | Percent of 255 |','| --- | ---: | ---: |']
    rows += [f"| {k} | {v['mad_0_255']:.4f} | {v['percent_255']:.4f}% |" for k,v in seams.items()]
    rows += ['', 'Small numerical jumps above 3% receive a three-frame dissolve. C3→C4 and C5→C6 use a half-second dip through black (a quarter-second out and in). The same grade and uniform grain cover the whole film. The train bed uses one-second overlap loops, is 14 dB below mean foley level, brightens in the dining car and is low-passed in the luggage van. The motif appears at the title, the sleeping-duckling discovery and the dawn ending. The mix is mastered with two-pass loudnorm to −16 LUFS; the final measurement is saved in `loudness-final.log`.','', '## Render times and retries','', '| Asset | App ID | Seed | Generation seconds |','| --- | --- | ---: | ---: |']
    total=0
    for key,item in journal['items'].items():
        if not key.startswith('C') or not key[1:].isdigit():continue
        r=item.get('response',{});m=r.get('metrics') or {};seconds=m.get('generation_seconds',r.get('generation_seconds','')) if isinstance(m,dict) else ''
        if isinstance(seconds,(int,float)):total+=seconds
        rows.append(f"| {key} | {item.get('id','')} | {item['payload'].get('seed','')} | {seconds} |")
    rows += ['', f'Total recorded production generation time: {total:.1f} seconds. No automatic render retry was performed. Before the user relaxed inspection, K0 was corrected for the early duckling/left-wall windows and then rendered at exact native dimensions. One rejected image-size override never entered the GPU queue. All attempts and payloads are retained.','', '## Verification limits','', '- Every generated video and the final master: ffprobe frame/audio proof and full FFmpeg decode.', '- Visual inspection, full-speed playback judgement, audio listening and stray-word acceptance: deferred to the user as requested.', '- Frontend build passed; configured bridge Python tests: 300 of 301 passed, with the existing AGENTS.md line-count assertion failing.', '- Preflight and doctor retain the existing Tailscale/runtime configuration findings recorded in EXECUTION_STATUS.md. No runtime repair was performed.','']
    (DOC/'EXECUTION_REPORT.md').write_text('\n'.join(rows),encoding='utf-8')
    print(DOC/'EXECUTION_REPORT.md')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['pilots','final']);a=p.parse_args();pilots() if a.action=='pilots' else final()
