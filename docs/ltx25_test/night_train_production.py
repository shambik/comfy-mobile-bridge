"""Production prompts and app-only serial rendering after pilot publication."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
import night_train_execute as bridge

OUT=bridge.OUT
STYLE=bridge.STYLE
SOUND='Only the sounds these actions make are heard; no background ambience, no music, no dialogue and no singing.'
SHOTS={
 'C1': (9,'K0','K1','The camera glides backward ahead of Bramble at his shoulder height as he walks slowly down the swaying sleeper corridor, his lantern swinging gently with the train. He hums softly to himself. He stops at a compartment door, listens with one ear, waits a beat, nods and walks on. Behind him, unseen, a door slides open a crack. A tiny duckling hops onto the carpet and waddles after him. Bramble slows and lifts his ears. Rain streaks the windows on the right and the lamps sway above-left. His footsteps thud softly, the sliding door squeaks and tiny feet patter.'),
 'C2': (10,'K1','K2',bridge.C2),
 'C3': (9,'K2','K3','The camera eases backward ahead of Bramble at shoulder height along the sleeper corridor. He looks down at the duckling between his boots and waits a beat. The duckling squeaks happily, turns and waddles away down the carpet. Bramble slowly raises a finger to his lips and makes a tiny shushing breath. He follows on tiptoe, keeping his lantern steady. They approach the dining-car doorway, where the camera passes beside the dark door jamb before revealing candlelit tables, card-playing mice and a chef at the stove. Rain beads on the right-hand windows and lamps sway with the carriage. Tiny feet patter, his coat rustles and the door gives a soft wooden creak.'),
 'C4': (10,'K3','K4','The camera tracks gently at Bramble shoulder height into the dining car, then lowers beside the table edge with his crouching movement. The duckling waddles under a table. The two mice stop with a card held halfway over their game and stare. Bramble waits a beat, bends carefully and crawls under the table after it. His cap brushes the underside of the table and tips crooked. The duckling emerges up onto the tabletop beside a pudding while one searching paw reaches up from below. The hedgehog chef quietly tends a pan and candles tremble with the carriage. Little feet tap, cloth brushes the wood, one card slaps the table and a pan gives a light clink.'),
 'C5': (9,'K4','K5','The camera begins beside the dining tabletop and gently follows Bramble as he rises. The duckling pauses beside the pudding and hops into it with a small splat. The chef turns around. Bramble slowly raises the pudding, smiles innocently and holds very still for a beat. The duckling slips out behind the plate and waddles toward the luggage-van door. Bramble notices, lowers the plate safely and follows with his lantern. The camera moves past the dark doorway into the dim luggage van, its single lamp swaying over stacked suitcases. The pudding makes a soft splat, the plate clinks, tiny feet patter and the door rolls softly.'),
 'C6': (9,'K5','K6','The camera follows slowly beside Bramble at shoulder height in the dim luggage van, then eases closer as he crouches. He raises his lantern and searches between the stacked suitcases. A tiny peep sounds from an open hat box. He stops and listens for a beat. He peers inside and his worried face softens. The duckling lies asleep in the box. He rests the lantern safely beside it, slides both paws under the duckling and gently lifts it, waiting for it to settle. The single overhead lamp sways and parcel ribbons stir with the moving carriage. Leather creaks softly, paper rustles, the duckling peeps once and Bramble releases a quiet relieved breath.'),
 'C7': (10,'K6','K7','The camera retreats slowly ahead of Bramble at shoulder height as he carries the sleeping duckling back through the train. He takes careful tiptoe steps, pauses for a beat and steadies his cupped paws. The camera passes through the dark gangway and into the sleeper corridor. A walrus snores behind a partly open compartment door. One floorboard creaks beneath Bramble. He freezes, eyes wide, waits, then continues when the sleeper remains still. He gently slides open Mother Duck’s compartment door and stops beside the bunk, where an empty dent lies next to her pillow. Rain trails the right-hand windows and the small lamps sway. His boots tap softly, the floorboard creaks, the walrus gives one deep snore and the sliding door rolls quietly.'),
 'C8': (10,'K7','K8','The camera holds gently beside Bramble at shoulder height inside the dim sleeper compartment, then retreats with him into the corridor. He slowly lowers the sleeping duckling into the empty pillow dent beside Mother Duck. He waits a beat and lifts his paws away. Without waking, she draws the duckling beneath one wing and gives a single sleepy quack. Bramble smiles, backs carefully out and slides the door shut. He releases a tired satisfied sigh and leans beside the corridor window as dawn turns the sky pale pink and the train crosses a bridge. The lamps still glow softly above-left and dawn enters from the right. Bedding rustles, the door closes with a soft wooden click, a tiny sleepy quack sounds and Bramble sighs.'),
}

def manifest():
    payload={k:{'duration':v[0],'planned_first':v[1],'planned_last':v[2],'seed':102400+i,'prompt':STYLE+' '+v[3]+' '+SOUND} for i,(k,v) in enumerate(SHOTS.items())}
    (OUT/'production_manifest.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
    text=['# Night Train — production prompts','', 'Visual and listening review belongs to the user, as instructed. All clips use LTX High, 8 distilled steps, sharp decode, 16:9, and generated foley. The selected pilot chain method determines actual image inputs.','']
    for k,v in payload.items():
        text += [f"## {k} — {v['duration']} s; seed {v['seed']}",'',v['prompt'],'']
    (Path(__file__).parent/'PRODUCTION_PROMPTS.md').write_text('\n'.join(text),encoding='utf-8')
    return payload

def submit(key,spec,method,previous):
    data=bridge.read()
    if key in data['items']: raise RuntimeError('Already journaled; no automatic retry')
    mode='frames' if method=='planned' else 'opening'
    first=spec['planned_first'] if method=='planned' or previous is None else previous+'_last'
    last=spec['planned_last'] if method=='planned' else None
    if method=='opening_closing' and previous is not None:
        mode='closing'; first=spec['planned_last']
    payload={'prompt':spec['prompt'],'mode':mode,'duration':str(spec['duration']),'engine':'ltx','steps':'8','aspect_ratio':'16:9','ltx_quality':'high','ltx_sharp_decode':'true','seed':str(spec['seed']),'no_audio':'false'}
    data['items'][key]={'kind':'video','payload':payload,'status':'submitting','source':first,'last_source':last,'chain_method':method,'submitted':time.time()}
    bridge.write(data)
    s=bridge.session(); files=[];opened=[]
    try:
        for field,image in ([('first_frame',first),('last_frame',last)] if mode=='frames' else [('image',first)]):
            p=OUT/(image+'.png');f=p.open('rb');opened.append(f);files.append((field,(p.name,f,'image/png')))
        files += [(k,(None,v)) for k,v in payload.items()]
        r=s.post(bridge.BASE+'/api/jobs',files=files,timeout=180)
        data['items'][key]['http_status']=r.status_code;data['items'][key]['response']=r.json()
        if r.ok:
            data['items'][key]['id']=r.json()['created'][0];data['items'][key]['status']='queued'
        else: data['items'][key]['status']='submission_failed'
        bridge.write(data);r.raise_for_status();print(key,r.json(),flush=True)
    finally:
        for f in opened:f.close()

def render():
    if (OUT/'STOPPED.json').exists():
        raise SystemExit('Night Train was stopped by the user. Do not resume it.')
    decision=json.loads((OUT/'pilot_decision.json').read_text())
    if not (Path(__file__).parent/'PILOT_RESULTS.md').is_file():
        raise RuntimeError('Publish pilot results before production')
    payload=manifest();method=decision['chain_method'];previous=None
    for key,spec in payload.items():
        if key not in bridge.read()['items']:submit(key,spec,method,previous)
        while True:
            bridge.poll(key);status=bridge.read()['items'][key]['status']
            if status=='completed':break
            if status not in {'queued','starting','running','verifying'}:raise RuntimeError(f'{key}: {status}; no automatic retry')
            time.sleep(20)
        subprocess.run([os.environ['NIGHT_TRAIN_MEDIA_PYTHON'],str(Path(__file__).with_name('night_train_media.py')),'verify',key],check=True)
        previous=key
    print('All production clips rendered and decoded; ready for assembly.',flush=True)

def finish():
    render()
    subprocess.run([os.environ['NIGHT_TRAIN_MEDIA_PYTHON'],str(Path(__file__).with_name('night_train_assemble.py'))],check=True)
    subprocess.run([os.sys.executable,str(Path(__file__).with_name('night_train_report.py')),'final'],check=True)
    print('Episode and execution report complete.',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['manifest','render','finish']);a=p.parse_args()
    if a.action=='manifest':manifest()
    elif a.action=='render':render()
    else:finish()
