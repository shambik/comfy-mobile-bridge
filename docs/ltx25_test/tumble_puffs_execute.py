"""Tumble Puffs cast and six-second gag. Every render uses the bridge app."""
import argparse
import json
import subprocess
import time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'tumble_puffs'
OUT.mkdir(parents=True,exist_ok=True)
JOURNAL=OUT/'execution.json'
BASE='http://127.0.0.1:8787'
STYLE=('Polished colourful 3D animated preschool comedy, beautifully groomed soft short fluffy fur with individual fine strands and soft fluffy silhouette edges, '
       'large expressive eyes, appealing rounded shapes, tiny simple mitten paws and broad little feet, bright sunny lighting, rich cheerful colours, clean readable silhouettes, cinematic animated-series quality. ')
CAST=(STYLE+'One single cast lineup image of exactly three original friendly imaginary fluff creatures, full bodies visible, standing separately with generous space between them on a clean pale sky-blue studio floor and a soft sky-blue background. '
      'Left: Pip, the smallest, a coral-red pear-shaped fluff creature with a small curled tuft on top, two tiny mitten paws and two broad little feet. Pip leans forward with an eager mischievous grin and bright curious eyes. '
      'Centre: Momo, the biggest and widest, a lemon-yellow rounded cushion-shaped fluff creature, a tiny top tuft, two small mitten paws and broad little feet. Momo has a soft gentle smile and a relaxed heavy stance. '
      'Right: Tiki, a taller slimmer mint-green jellybean-shaped fluff creature with two small fur tufts on the sides of the head, two mitten paws and broad little feet. Tiki stands carefully upright, with one raised eyebrow and a thoughtful amused expression. '
      'All three are furry all over with faces integrated into their soft bodies, expressive dark pupils and clearly different body silhouettes and heights. No clothing, no props, no text, no labels, no panels, no logo. Wide landscape composition with clear space above each head and below each foot.')
OPENING=(STYLE+'Use the coral pear-shaped creature on the left of the reference as the exact identity reference for Pip: preserve its coral colour, eye design, short soft fur, curled top tuft, little paws, broad feet and pear silhouette. '
         'Create one single finished animation opening shot in a sunny oversized garden clearing. Only Pip is present. Remove the yellow and mint characters from this shot. '
         'A single thick bright red round squishy cushion with a simple fabric surface lies flat on short green grass directly in front of Pip. Pip crouches beside the cushion on its left, leaning slightly forward, one little paw hovering just above the centre of the cushion, ready to press it. Both feet stay on the grass. '
         'Pip has a curious playful expression, face visible in three-quarter view, mouth relaxed, eyes looking at the cushion. The head is near enough above the cushion for a tiny spring-back to gently bop the underside of the chin. '
         'Medium-wide framing at Pip eye level, Pip and the whole cushion fill the central two thirds of the image, with clear space around them. Soft oversized rounded leaves and simple colourful flowers in the background, blue sky, sunny warm side light, soft contact shadows. '
         'The background is uncluttered and gently out of focus. The cushion is the only main prop. No text, no panels and no extra creatures.')
GAG=('A polished brightly coloured 3D preschool comedy animation, with soft fluffy fur, springy squash and stretch, expressive poses and clear comic timing. '
     'The camera holds a medium-wide view of Pip and the red cushion in the sunny garden. '
     'Pip slowly presses one little paw into the centre of the cushion and leans closer to examine it. The cushion squashes visibly beneath the paw. '
     'Pip lifts the paw away. The cushion springs back into its rounded shape and its soft edge gives Pip one gentle little bop under the chin. '
     'Pip freezes for a beat with wide surprised eyes, then looks at the cushion and breaks into a delighted grin and a tiny giggle. The cushion settles on the grass and Pip stays beside it. '
     'The tuft and soft fur follow the little head wobble naturally; the leaves move very gently in the sunshine. '
     'A soft cloth squeeze, one playful springy boing exactly on the bop, a tiny surprised squeak and a short happy giggle accompany the action, with a light playful pizzicato musical phrase underneath. No spoken words, no narration, no singing. One uninterrupted shot.')

def read():
    return json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {'created':time.time(),'items':{},'review_policy':'User performs visual review. No AGY or delegated agents; basic media validity checks only.'}

def write(data):
    temp=JOURNAL.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8');temp.replace(JOURNAL)

def session():
    s=requests.Session();r=s.get(BASE+'/api/session',timeout=30);r.raise_for_status();s.headers['x-csrf-token']=r.json()['csrf_token'];return s

def submit(key):
    if (OUT/'STOPPED.json').exists():raise SystemExit('This run was stopped. No submission made.')
    data=read()
    if key in data['items']:raise SystemExit('Already journaled. A POST is never retried automatically.')
    s=session();h=s.get(BASE+'/api/health',timeout=30);h.raise_for_status()
    if h.json().get('active_job'):raise SystemExit('A bridge video job is already active.')
    image=key!='gag_01'
    if image:
        raise SystemExit('User requested built-in ImageGen for stills. App image submissions are disabled for this series.')
    source='cast' if key=='opening_01' else 'opening_imagegen_v1' if key=='gag_01' else None
    if image:
        workflow='krea_t2i_simplified_workflow.json' if key=='cast' else 'qwen2509_i2i_1input.json'
        c=s.get(BASE+'/api/bot-images/compatibility',timeout=60);c.raise_for_status()
        if not c.json()['workflows'][workflow]['ready']:raise SystemExit('Selected image workflow is not ready.')
        payload={'workflow':workflow,'prompt':CAST if key=='cast' else OPENING,'flags':{'seed':1023601 if key=='cast' else 1023602,'res':[1600,896]},'overrides':[] if key=='cast' else [{'node':'154','key':'boolean','value':True}]}
        route='/api/bot-images/runs';parts=[('payload',(None,json.dumps(payload)))];field='images'
    else:
        payload={'prompt':GAG,'mode':'opening','duration':'6','engine':'ltx','steps':'8','aspect_ratio':'16:9','ltx_quality':'high','ltx_sharp_decode':'true','ltx_calm_sampler':'false','seed':'1023603','no_audio':'false'}
        route='/api/jobs';parts=[(k,(None,v)) for k,v in payload.items()];field='image'
    item={'kind':'image' if image else 'video','status':'submitting','source':source,'submitted':time.time(),'payload':payload}
    data['items'][key]=item;write(data)
    opened=None
    try:
        if source:
            p=Path(data['items'][source]['path']);opened=p.open('rb');parts.append((field,(p.name,opened,'image/png')))
        r=s.post(BASE+route,files=parts,timeout=180)
        item['http_status']=r.status_code;item['response']=r.json()
        if r.ok:item.update(id=r.json()['id'] if image else r.json()['created'][0],status='queued')
        else:item['status']='submission_failed'
        write(data);r.raise_for_status();print(json.dumps({'key':key,'id':item['id'],'status':item['status']}),flush=True)
    finally:
        if opened:opened.close()

def poll(key):
    data=read();item=data['items'][key];s=session()
    route='/api/bot-images/runs/'+item['id'] if item['kind']=='image' else '/api/jobs?limit=200&include_library=false&include_sequences=false'
    r=s.get(BASE+route,timeout=30);r.raise_for_status();result=r.json()
    if item['kind']=='video':result=next(j for j in result['jobs'] if j['id']==item['id'])
    item['response']=result;item['status']=result['status']
    if result['status']=='completed' and not item.get('path'):
        dest=OUT/(key+('.png' if item['kind']=='image' else '.mp4'))
        url=result['images'][0] if item['kind']=='image' else '/api/jobs/'+item['id']+'/video'
        media=s.get(BASE+url,timeout=180);media.raise_for_status();dest.write_bytes(media.content);item['path']=str(dest)
    write(data)
    brief={'key':key,'status':item['status'],'step':result.get('step'),'total_steps':result.get('total_steps'),'progress':result.get('progress'),'path':item.get('path'),'elapsed':round(time.time()-item['submitted'])}
    print(json.dumps(brief),flush=True);return item['status']

def wait(key):
    while True:
        status=poll(key)
        if status=='completed':return
        if status not in {'queued','starting','running','verifying'}:raise SystemExit(f'{key}: {status}; no automatic retry')
        time.sleep(20)

def verify():
    p=OUT/'gag_01.mp4'
    info=json.loads(subprocess.run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(p)],check=True,capture_output=True).stdout)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'],check=True)
    v=next(s for s in info['streams'] if s['codec_type']=='video');a=next(s for s in info['streams'] if s['codec_type']=='audio')
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(p),'-vf','fps=2,scale=480:-2,tile=4x4:padding=4:margin=4','-frames:v','1',str(OUT/'gag_01_contact.png')],check=True)
    proof={'path':str(p),'width':v['width'],'height':v['height'],'fps':v['r_frame_rate'],'decoded_frames':v['nb_read_frames'],'duration':info['format']['duration'],'audio':a['codec_name'],'full_decode':'passed','visual_review':'User'}
    (OUT/'gag_01_proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof),flush=True)

def run(key):
    if key!='gag_01':
        raise SystemExit('Stills use built-in ImageGen. This runner now executes only the LTX video sample.')
    if key not in read()['items']:submit(key)
    wait(key)
    if key=='gag_01':verify()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','poll','verify']);p.add_argument('key',nargs='?');a=p.parse_args()
    if a.action=='run':run(a.key)
    elif a.action=='poll':poll(a.key)
    else:verify()
