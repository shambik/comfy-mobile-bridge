"""Night Train execution journal; renders only through the bridge HTTP API.

One submission per invocation, never retries a POST. Generated media stays in state.
"""
import argparse
import copy
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'night_train'
OUT.mkdir(parents=True, exist_ok=True)
JOURNAL = OUT / 'execution.json'
BASE = 'http://127.0.0.1:8787'
LOOK = 'claymation stop-motion, plasticine characters with visible thumbprints and sculpting marks, hand-built miniature train interior with polished wood panels, brass fittings and velvet curtains, warm amber lamplight, deep blue night outside the windows, shallow depth of field, cosy and tactile'
BRAMBLE = "Bramble is a tall gentle anthropomorphic clay badger, black and cream striped face, big expressive eyes and brows, dark green porter's uniform with brass buttons and a dark green peaked cap, black boots, carrying one small brass lantern."
DUCK = 'The duckling is a single tiny round yellow clay duckling with an orange beak, two small orange feet and big black eyes.'
BASELINE = 'Photograph of a real handmade miniature clay puppet set, tactile plasticine, rounded chunky forms, visible fingerprints. 35 mm lens feel, camera at Bramble shoulder height, warm practical lamps above left, windows to the right, no readable text or labels. Wide landscape composition, entire character readable, no extra limbs. '
STILLS = {
 'K0_master_raw': ('create', None, ''),
 'K0_repair': ('edit', 'K0_master_raw', 'Edit this same shot and retain the exact badger puppet identity, cap, uniform, brass lantern and composition. Remove the yellow duckling entirely: Bramble is completely alone, and there are no ducks or ducklings anywhere. Replace all the windows on the LEFT wall with closed dark polished-wood sliding sleeper-compartment doors with small brass handles. Keep rain-streaked blue windows only on the RIGHT wall. Make the puppets and all scenery visibly handmade plasticine with soft matte clay, irregular sculpting marks, fingerprints and tiny sculpting tool indentations. Keep his face and both boots readable, and warm amber lamps above left. This is a real miniature puppet photograph.'),
 'K0_exact': ('edit', 'K0_repair', 'Preserve this exact corridor scene and its composition. The same badger is alone with no ducks. Preserve closed compartment doors on the left and blue rainy windows on the right, the green uniform, cap and lantern, with face and both boots visible. Render at the selected landscape output dimensions. Emphasize tiny irregular fingerprints pressed into the matte plasticine cheeks, nose, hat and sleeve cuffs, and sculpting tool marks in the miniature wood and velvet. Keep the soft amber lamps and cosy handmade puppet appearance.'),
 'K0': ('create', None, 'Sleeper train corridor at midnight, wide view down the corridor, compartment doors along the left wall, rain-streaked windows along the right wall. Bramble walks toward the camera carrying his lantern, alone, face clearly visible. The corridor is quiet and gently cosy.'),
 'K3': ('create', None, 'The doorway into a miniature sleeper-train dining car at midnight. Bramble stands just inside the doorway looking into the dining car, his face readable. A hedgehog chef stands beside a tiny stove at left, two small mice play cards by candlelight at a low table. Wood tables and burgundy velvet seats, a small pudding on a table, rain-streaked windows at right.'),
 'K5': ('create', None, 'The luggage van of the sleeper train at midnight, dim with a single warm overhead lamp above-left. Bramble stands in the aisle with his brass lantern raised, searching. Stacks of little leather suitcases, tied parcels without labels, one open round hat box on the floor. Deep blue darkness through a small window on the right.'),
 'sheet': ('create', None, 'Clean clay puppet character turnaround reference sheet on a plain neutral warm grey studio background. Two rows with three views each, generous spacing, no letters, no text, no labels. Upper row shows the same Bramble puppet front view, side view and back view, identical green uniform and cap and brass lantern. Lower row shows the same tiny yellow duckling puppet front, side and back. Clearly three views of each character, no extra characters. Soft lamp from upper left. The lower duckling row is much smaller than the upper badger row.'),
 'K1': ('edit', 'K0', 'Keep this exact sleeper corridor miniature set, the same badger identity, uniform, cap, lantern, lens and lighting. Bramble has stopped walking, his ears perked up and brows raised, in a medium full-body composition with his boots visible and his face readable. Add exactly one tiny yellow duckling immediately behind his heel on the carpet, partly hidden by his boot. No other ducklings. Keep compartment doors at left, rain windows at right.'),
 'K2': ('edit', 'K0', 'Keep this exact sleeper corridor miniature set and the same badger identity, uniform, cap and brass lantern. Bramble now looks down with wide surprised eyes at exactly one tiny yellow duckling standing between his two boots on the carpet. His face remains clearly visible tilted down, his whole body and both boots in the image. Frame lower in the same corridor with a gentle downward view, without changing the lens or lighting direction. Door panels remain at left and rainy blue windows at right.'),
 'K4': ('edit', 'K3', 'Keep the exact dining-car miniature set, warm lamps, wood and velvet, the same character identities and scale. Reframe closer to the tabletop: exactly one tiny yellow duckling stands beside a small round pudding on a plate on the table. Bramble crouches below the table with his face readable at the table edge and one paw reaching toward the duckling from below. His green cap is slightly crooked. The same hedgehog chef and mice remain softly visible in the background. Windows remain to the right.'),
 'K6': ('edit', 'K5', 'Keep the exact dim luggage van miniature set, stacked leather suitcases and parcels, the same Bramble puppet with identical uniform, cap and lantern. A closer view of Bramble gently lifting exactly one sleeping tiny yellow duckling in both cupped paws from an open round hat box. His face is clearly readable with a tender relieved expression. His brass lantern rests safely beside the box. Same warm overhead light from above-left and blue window at right.'),
 'K7': ('edit', 'K0', 'Keep the same miniature train design, wood finish, velvet curtains and warm light direction, and exactly the same badger puppet. The left sliding compartment door is open and the camera looks inside the dim sleeper compartment. A large white clay mother duck in a lace nightcap sleeps in a lower bunk, one empty dent in the pillow beside her. Bramble stands just inside holding exactly one sleeping tiny yellow duckling gently in his paws, his face readable. One soft amber lamp above-left, dark blue window on right.'),
 'K8': ('edit', 'K0', 'Keep this exact sleeper corridor miniature, same badger identity, green uniform, cap, lantern, same lens and warm lamp direction. Dawn now brings pale pink-blue light through the windows on the right. Bramble leans tired but content beside the right window, face visible in three-quarter view, brass lantern down at his side. Beyond the window the train crosses a miniature bridge above a quiet valley under a pink dawn sky. No ducklings in this corridor.'),
}
STYLE = 'A claymation stop-motion scene with handmade plasticine puppets on a miniature set, animated with stepped stop-motion movement, slightly staccato like real claymation at 12 frames per second.'
C2 = 'The camera holds at Bramble shoulder height in the gently rocking sleeper corridor, keeping his face and both boots in view. He turns slowly and searches behind him. The duckling quietly shuffles to stay hidden behind his leg. He waits a beat and frowns. He turns back. A tiny peep sounds. He freezes, eyes wide, then slowly lowers his eyes toward his boots. The lamps sway gently and rain beads on the windows to the right. Soft cloth rustles, boots scuff once, the duckling makes one tiny peep; no spoken words and no singing.'
C3 = 'The camera eases backward at Bramble shoulder height along the same sleeper corridor, keeping him and the duckling together in view. He looks down at the duckling and waits a beat. The duckling gives a happy squeak and takes a few small waddling steps forward. Bramble raises one finger gently to his lips and tiptoes after it. Rain beads on the blue windows to the right and warm lamps sway above-left. Tiny feet patter and his boots thud softly, with one quiet shushing breath; no spoken words and no singing.'
PILOTS = {
 'P1a_1': ('frames', 'K1', 'K2', STYLE + ' ' + C2),
 'P1a_2': ('opening', 'K2', None, STYLE + ' ' + C3),
 'P1b_1': ('opening', 'K1', None, STYLE + ' ' + C2),
 'P1b_2': ('opening', 'P1b_1_last', None, STYLE + ' ' + C3),
 'P1b_3': ('opening', 'P1b_2_last', None, STYLE + ' ' + C3),
 'P1c_2': ('closing', 'K2', None, STYLE + ' ' + C2),
 'P2_smooth': ('opening', 'K1', None, STYLE.replace('stepped stop-motion movement, slightly staccato like real claymation at 12 frames per second', 'smooth, fluid animation') + ' ' + C2),
 'P3a': ('text', None, None, 'The camera holds on a dark, empty sleeper-train corridor. Only sound: the steady rhythmic clack of wheels over rail joints, the soft creak of wood panels as the carriage rocks, rain on the windows, a faint distant whistle. No voices, no music.'),
 'P3b': ('text', None, None, 'The camera holds on a dark, empty sleeper-train corridor. Only sound: a gentle music-box waltz melody, slow and sleepy, solo celesta and soft pizzicato strings, no voices. A simple tender three-beat melody with a clear beginning and a gentle resolving cadence.'),
}

def submit_video(key):
    if (OUT / 'STOPPED.json').exists():
        raise SystemExit('Night Train was stopped by the user. Do not resume it.')
    data = read()
    if key in data['items']:
        raise SystemExit('Already journaled; inspect before submitting any new attempt.')
    mode, first, last, prompt = PILOTS[key]
    seed = 102351 if key in {'P1a_1','P1b_1','P1c_2','P2_smooth'} else 102352 + list(PILOTS).index(key)
    payload = {'prompt':prompt, 'mode':mode, 'duration':'5', 'engine':'ltx', 'steps':'8', 'aspect_ratio':'16:9', 'ltx_quality':'balanced', 'ltx_sharp_decode':'true', 'seed':str(seed), 'no_audio':'false'}
    s = session()
    data['items'][key] = {'kind':'video','payload':payload,'status':'submitting','submitted':time.time(),'source':first,'last_source':last}
    write(data)
    files, opened = [], []
    try:
        for field, image in ([('first_frame',first),('last_frame',last)] if mode == 'frames' else [('image',first)]):
            if not image: continue
            path = OUT / (image + '.png')
            if not path.is_file(): raise FileNotFoundError(path)
            f = path.open('rb'); opened.append(f)
            files.append((field,(path.name,f,'image/png')))
        # Force multipart even for text-only runs.
        files.extend((k,(None,v)) for k,v in payload.items())
        r = s.post(BASE + '/api/jobs', files=files, timeout=180)
        data['items'][key]['http_status'] = r.status_code
        result = r.json()
        data['items'][key]['response'] = result
        if r.ok:
            data['items'][key]['id'] = result['created'][0]
            data['items'][key]['status'] = 'queued'
        else: data['items'][key]['status'] = 'submission_failed'
        write(data)
        print(json.dumps(result,indent=2))
        r.raise_for_status()
    finally:
        for f in opened: f.close()

def read():
    return json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {'created': time.time(), 'items': {}}

def write(data):
    temp = JOURNAL.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(JOURNAL)

def session():
    s = requests.Session()
    r = s.get(BASE + '/api/session', timeout=30)
    r.raise_for_status()
    s.headers['x-csrf-token'] = r.json()['csrf_token']
    return s

def submit_still(key):
    if (OUT / 'STOPPED.json').exists():
        raise SystemExit('Night Train was stopped by the user. Do not resume it.')
    data = read()
    if key in data['items']:
        raise SystemExit('Already journaled; inspect before submitting any new attempt.')
    kind, master, scene = STILLS[key]
    workflow = 'krea_t2i_simplified_workflow.json' if kind == 'create' else 'qwen2509_i2i_1input.json'
    s = session()
    health = s.get(BASE + '/api/health', timeout=30).json()
    if health.get('active_job'):
        raise SystemExit('Bridge has an active video job.')
    comp = s.get(BASE + '/api/bot-images/compatibility', timeout=60).json()['workflows'][workflow]
    if not comp['ready']:
        raise SystemExit(json.dumps(comp))
    seed = 102300 + list(STILLS).index(key)
    prompt = LOOK + '. ' + BASELINE + BRAMBLE + ' ' + (DUCK if key in {'K1','K2','K4','K6','K7'} else '') + ' ' + scene
    if key == 'sheet':
        prompt = LOOK + '. ' + BRAMBLE + ' ' + DUCK + ' ' + scene
    payload = {'workflow': workflow, 'prompt': prompt, 'flags': {'seed': seed, 'res': [1600, 896]}, 'overrides': []}
    if kind == 'edit':
        # Use the app's exposed latent-size selector so its resolution fields
        # govern output, rather than the recipe's 1 MP source-image latent.
        payload['overrides'] = [{'node':'154','key':'boolean','value':True}]
    data['items'][key] = {'kind':'image', 'payload':payload, 'status':'submitting', 'submitted':time.time(), 'source':master}
    write(data)
    files = []
    opened = []
    try:
        if master:
            source = Path(data['items'][master]['path'])
            f = source.open('rb')
            opened.append(f)
            files.append(('images', (source.name, f, 'image/png')))
        # A multipart text part even for text-to-image.
        files.append(('payload', (None, json.dumps(payload))))
        r = s.post(BASE + '/api/bot-images/runs', files=files, timeout=180)
        data['items'][key]['http_status'] = r.status_code
        data['items'][key]['response'] = r.json()
        if r.ok:
            data['items'][key]['id'] = r.json()['id']
            data['items'][key]['status'] = r.json()['status']
        else:
            data['items'][key]['status'] = 'submission_failed'
        write(data)
        print(json.dumps(data['items'][key], indent=2))
        r.raise_for_status()
    finally:
        for f in opened:
            f.close()

def poll(key):
    data = read()
    item = data['items'][key]
    s = session()
    route = '/api/bot-images/runs/' + item['id'] if item['kind'] == 'image' else '/api/jobs?limit=200&include_library=false&include_sequences=false'
    r = s.get(BASE + route, timeout=30)
    r.raise_for_status()
    result = r.json()
    if item['kind'] == 'video':
        result = next(j for j in result['jobs'] if j['id'] == item['id'])
    item['response'] = result
    item['status'] = result['status']
    if result['status'] == 'completed' and not item.get('path'):
        dest = OUT / (key + ('.png' if item['kind'] == 'image' else '.mp4'))
        url = result['images'][0] if item['kind'] == 'image' else '/api/jobs/' + item['id'] + '/video'
        media = s.get(BASE + url, timeout=180)
        media.raise_for_status()
        dest.write_bytes(media.content)
        item['path'] = str(dest)
    write(data)
    print(json.dumps({'key':key, 'path':item.get('path'), 'result':result}, indent=2))

def still_batch():
    for key in ['K3','K5','sheet','K1','K2','K4','K6','K7','K8']:
        data = read()
        if key not in data['items']:
            submit_still(key)
        while True:
            poll(key)
            status = read()['items'][key]['status']
            if status == 'completed': break
            if status not in {'queued','running'}:
                raise SystemExit(f'{key}: {status}; no automatic retry')
            time.sleep(20)

def prepare():
    while True:
        poll('K0_exact')
        item = read()['items']['K0_exact']
        if item['status'] == 'completed': break
        if item['status'] not in {'queued','running'}:
            raise SystemExit('K0_exact did not complete; no automatic retry')
        time.sleep(20)
    data = read()
    data['items']['K0'] = copy.deepcopy(data['items']['K0_exact'])
    destination = OUT / 'K0.png'
    shutil.copy2(data['items']['K0']['path'], destination)
    data['items']['K0']['path'] = str(destination)
    data['items']['K0']['adopted_from'] = 'K0_exact'
    data['review_policy'] = 'User performs visual and listening review; no AGY or delegated agents. Basic technical file checks and pilot measurements only.'
    write(data)
    still_batch()

def pilots():
    def media(action, key=None):
        command=[os.environ['NIGHT_TRAIN_MEDIA_PYTHON'],str(Path(__file__).with_name('night_train_media.py')),action]
        if key: command.append(key)
        subprocess.run(command,check=True)
    media('board')
    for key in PILOTS:
        data=read()
        if key not in data['items']: submit_video(key)
        while True:
            poll(key)
            status=read()['items'][key]['status']
            if status=='completed': break
            if status not in {'queued','starting','running','verifying'}:
                raise SystemExit(f'{key}: {status}; no automatic retry')
            time.sleep(20)
        media('verify',key)
        media('seams')
    media('motion')
    media('previews')
    print('All pilot renders and file proofs complete. Publish results before production.', flush=True)

def pilots_when_ready():
    while True:
        data=read()
        if all(data['items'].get(f'K{i}',{}).get('status')=='completed' for i in range(9)) and data['items'].get('sheet',{}).get('status')=='completed':
            break
        time.sleep(20)
    pilots()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['still','video','poll','status','stills','prepare','pilots','pilots-when-ready'])
    parser.add_argument('key', nargs='?')
    args = parser.parse_args()
    if args.action == 'still': submit_still(args.key)
    elif args.action == 'video': submit_video(args.key)
    elif args.action == 'stills': still_batch()
    elif args.action == 'prepare': prepare()
    elif args.action == 'pilots': pilots()
    elif args.action == 'pilots-when-ready': pilots_when_ready()
    elif args.action == 'poll': poll(args.key)
    else: print(json.dumps(read(), indent=2))
