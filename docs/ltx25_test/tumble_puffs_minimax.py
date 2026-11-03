"""App-only MiniMax H3 sample with requested sparse attention and 1.5 MP."""
import json
import os
import subprocess
import time
from pathlib import Path
import tumble_puffs_execute as bridge

OUT=bridge.OUT
KEY='gag_02_pinwheel'
PROMPT='''For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Polished colourful 3D cartoon comedy. The opening preserves the two fluffy characters, their faces and body shapes, the planted pinwheel, flower garden and warm sunlight of <Picture 1>. Small coral Pip stays on the left with the curled top tuft, and broad lemon-yellow Momo stays on the right. The red, blue, yellow and pink paper pinwheel stands firmly between them. Over this eight-second single shot, the camera pushes in with small amplitude at slow speed, keeping both faces, their feet and the spinner in view. Momo (S1), with a low soft breathy nonverbal voice, leans toward the spinner, inflates the cheeks and gives one sustained playful puff from right to left. The pinwheel begins turning, then spins quickly while its wooden stem remains planted. The same breeze sweeps Pip's coral fur and curled tuft sideways to the left. Pip (S2), with a tiny high breathy giggle, squints into the breeze and leans back a little with both feet planted, little paws raised in surprise. Momo stops blowing. The spinner slows, Pip's tuft flops back into its curl, and Pip gives Momo one wide-eyed look. Momo's pleased expression turns sheepish; Pip breaks into a grin and both give a brief playful chuckle. Nearby leaves sway and one tiny butterfly drifts behind them. Preserve the short fluffy fur and the distinct coral and yellow colours throughout. No spoken words, singing or narration.

overall_soundscape: Soft garden birds and rustling leaves sit quietly under the action. Momo's rounded puff becomes a soft airy whoosh, with a light papery whir from the spinning pinwheel; the whoosh subsides when Momo stops. A little fur swish and Pip's surprised squeak lead to two short nonverbal chuckles, with no intelligible speech.

non_diegetic_music: N/A'''

def submit():
    data=bridge.read()
    if KEY in data['items']:raise SystemExit('Already journaled; never automatically retry a POST.')
    if (OUT/'STOPPED.json').exists():raise SystemExit('This series run is stopped.')
    source='opening_02_pinwheel_imagegen_v1';path=Path(data['items'][source]['path'])
    payload={'prompt':PROMPT,'mode':'opening','duration':'8','engine':'turbo','turbo_profile':'v1','steps':'6','encoder':'native','attention_mode':'sla','megapixels':'1.5','aspect_ratio':'16:9','seed':'1023610','no_audio':'false'}
    s=bridge.session();h=s.get(bridge.BASE+'/api/health',timeout=30);h.raise_for_status()
    if h.json().get('active_job'):raise SystemExit('The bridge has an active video job.')
    item={'kind':'video','status':'submitting','source':source,'submitted':time.time(),'payload':payload,'music_policy':'Original eight-second celesta-style and pizzicato underscore mixed in post over generated H3 foley.'}
    data['items'][KEY]=item;bridge.write(data)
    (OUT/'gag_02_h3_prompt.txt').write_text(PROMPT,encoding='utf-8')
    with path.open('rb') as f:
        parts=[(k,(None,v)) for k,v in payload.items()]+[('image',(path.name,f,'image/png'))]
        r=s.post(bridge.BASE+'/api/jobs',files=parts,timeout=180)
    item['http_status']=r.status_code;item['response']=r.json()
    if r.ok:item.update(id=r.json()['created'][0],status='queued')
    else:item['status']='submission_failed'
    bridge.write(data);r.raise_for_status();print(json.dumps({'key':KEY,'id':item['id'],'settings':payload}),flush=True)

def proof(path):
    result=subprocess.run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)],capture_output=True,check=True)
    data=json.loads(result.stdout);v=next(s for s in data['streams'] if s['codec_type']=='video');a=next(s for s in data['streams'] if s['codec_type']=='audio')
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True)
    info={'path':str(path),'width':v['width'],'height':v['height'],'fps':v['r_frame_rate'],'frames':v['nb_read_frames'],'duration':data['format']['duration'],'audio':a['codec_name'],'full_decode':'passed','visual_review':'user'}
    path.with_name(path.stem+'_proof.json').write_text(json.dumps(info,indent=2));print(json.dumps(info),flush=True)

def run():
    if KEY not in bridge.read()['items']:submit()
    bridge.wait(KEY)
    proof(OUT/(KEY+'.mp4'))
    subprocess.run([os.environ['TUMBLE_PUFFS_MEDIA_PYTHON'],str(Path(__file__).with_name('tumble_puffs_music.py'))],check=True)
    proof(OUT/(KEY+'_with_music.mp4'))
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(OUT/(KEY+'_with_music.mp4')),'-vf','fps=2,scale=480:-2,tile=5x4:padding=4:margin=4','-frames:v','1',str(OUT/(KEY+'_contact.png'))],check=True)
    print('MiniMax sample with music is complete.',flush=True)

if __name__=='__main__':run()
