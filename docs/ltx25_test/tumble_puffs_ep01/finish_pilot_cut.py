"""Honor the stop request: edit only the fifteen already completed clips."""
import copy
import json
from pathlib import Path
import episode_runner as run

source = run.OUT
data = run.read()
manifest = json.loads((source/'manifest.json').read_text())
assert (source/'STOPPED.json').exists()
selected = [s for s in manifest['shots'] if data['items'].get(s['id'],{}).get('status')=='verified']
assert len(selected)==15 and sum(s['duration'] for s in selected)==89
cut = source.parent/'fluffies_berry_pilot_cut'
cut.mkdir(exist_ok=True)
spec = copy.deepcopy(manifest)
spec.update(title='Fluffies — Berry pilot, completed shots cut',total_frames=2136,total_seconds=89)
spec['shots'] = selected
for shot in selected:
    shot['clip'] = str(source/shot['clip'])
    shot['frame'] = str(source/shot['frame'])
(cut/'manifest.json').write_text(json.dumps(spec,indent=2))
(cut/'execution.json').write_text(json.dumps(dict(items=data['items'],review='User requested shortened cut and stopped remaining shots'),indent=2))
# Preserve the original full-length score; the cut receives its own copy.
(cut/'episode_score_and_foley.wav').write_bytes((source/'episode_score_and_foley.wav').read_bytes())
run.OUT,run.JOURNAL,run.FINAL = cut,cut/'execution.json',cut/'Fluffies_Berry_Pilot_89s_with_music.mp4'
run.assemble()
run.publish(run.FINAL,2136,'Fluffies - Berry pilot - completed shots cut - 89s with music.mp4')
