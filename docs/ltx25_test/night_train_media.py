"""CPU-only proof, exact decoded handoffs and pilot measurements.

Run with a Python that already provides Pillow and NumPy. Never installs packages.
"""
import argparse
import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'night_train'

def run(command):
    return subprocess.run(command, check=True, capture_output=True)

def verify(key):
    path = OUT / (key + '.mp4')
    info = json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)]).stdout)
    run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'])
    video = next(s for s in info['streams'] if s['codec_type']=='video')
    audio = next(s for s in info['streams'] if s['codec_type']=='audio')
    count = int(video['nb_read_frames'])
    for label, idx in [('first',0),('last',count-1)]:
        run(['ffmpeg','-v','error','-y','-i',str(path),'-vf',f'select=eq(n\\,{idx})','-frames:v','1',str(OUT / f'{key}_{label}.png')])
    run(['ffmpeg','-v','error','-y','-i',str(path),'-vn','-ac','1','-ar','16000',str(OUT / f'{key}.wav')])
    run(['ffmpeg','-v','error','-y','-i',str(path),'-vn','-ac','2','-ar','48000','-c:a','pcm_s16le',str(OUT / f'{key}_audio.wav')])
    rows=max(1,int(np.ceil(np.ceil(count/24*2)/5)))
    run(['ffmpeg','-v','error','-y','-i',str(path),'-vf',f'fps=2,scale=480:-2,tile=5x{rows}:padding=4:margin=4','-frames:v','1',str(OUT / f'{key}_contact.png')])
    proof={'key':key,'path':str(path),'width':video['width'],'height':video['height'],'fps':video['r_frame_rate'],'frames':count,'duration':info['format']['duration'],'audio':audio['codec_name'],'full_decode':'passed'}
    (OUT / f'{key}_proof.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(proof))

def board():
    canvas = Image.new('RGB',(3*640,3*384),(22,20,18))
    strip = Image.new('RGB',(9*640,384),(22,20,18))
    d = ImageDraw.Draw(canvas)
    sd = ImageDraw.Draw(strip)
    sizes = {}
    for n in range(9):
        p=OUT / f'K{n}.png'
        if not p.exists(): continue
        im=Image.open(p).convert('RGB'); im.thumbnail((632,354))
        sizes[f'K{n}'] = list(Image.open(p).size)
        x=(n%3)*640+4; y=(n//3)*384+26
        canvas.paste(im,(x,y)); d.text((x,y-21),f'K{n}  {Image.open(p).size}',fill='white')
        strip.paste(im,(n*640+4,26)); sd.text((n*640+4,5),f'K{n}',fill='white')
    canvas.save(OUT / 'keyframes_contact.png')
    strip.save(OUT / 'keyframes_strip.png')
    (OUT / 'keyframe_sizes.json').write_text(json.dumps(sizes,indent=2))
    print(OUT / 'keyframes_contact.png')

def mad(a,b):
    x=np.asarray(Image.open(OUT/a).convert('RGB'),dtype=np.float32)
    y=Image.open(OUT/b).convert('RGB')
    if y.size != (x.shape[1],x.shape[0]): y=y.resize((x.shape[1],x.shape[0]),Image.Resampling.LANCZOS)
    diff=np.abs(x-np.asarray(y,dtype=np.float32))
    return {'mad_0_255':float(diff.mean()),'percent_255':float(diff.mean()/255*100)}

def seams():
    pairs={'P1a_seam':('P1a_1_last.png','P1a_2_first.png'),'P1a_landing':('P1a_1_last.png','K2.png'),'P1b_seam_1':('P1b_1_last.png','P1b_2_first.png'),'P1b_seam_2':('P1b_2_last.png','P1b_3_first.png'),'P1c_seam':('P1b_1_last.png','P1c_2_first.png'),'P1b_landing':('P1b_1_last.png','K2.png')}
    result={k:mad(a,b) for k,(a,b) in pairs.items() if (OUT/a).exists() and (OUT/b).exists()}
    (OUT/'pilot_metrics.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

def motion():
    result={}
    for key in ['P1b_1','P2_smooth']:
        raw=run(['ffmpeg','-v','error','-i',str(OUT/f'{key}.mp4'),'-vf','scale=320:180,format=gray','-f','rawvideo','-']).stdout
        frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,180,320).astype(np.float32)
        delta=np.abs(np.diff(frames,axis=0)).mean(axis=(1,2))
        result[key]={'mean_frame_delta_0_255':float(delta.mean()),'p10':float(np.percentile(delta,10)),'p90':float(np.percentile(delta,90)),'low_motion_frame_fraction':float((delta<1.0).mean()),'note':'Numerical temporal differences only; handmade feel and jitter are for user review.'}
    (OUT/'motion_metrics.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

def previews():
    for name,keys in {'P1a_chain':['P1a_1','P1a_2'],'P1b_chain':['P1b_1','P1b_2','P1b_3'],'P1c_chain':['P1b_1','P1c_2']}.items():
        listing=OUT/f'{name}.ffconcat'
        listing.write_text('ffconcat version 1.0\n'+''.join(f"file '{k}.mp4'\n" for k in keys))
        run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(OUT/f'{name}.mp4')])
    # Five-second pilots yield a nine-second motif with a one-second overlap.
    # This is an edited motif, not an invented eight-second source phrase.
    for key,dest in [('P3a','location_loop_test'),('P3b','music_motif')]:
        source=OUT/f'{key}_audio.wav'
        args=['ffmpeg','-v','error','-y','-i',str(source),'-i',str(source)]
        if key=='P3a':
            args+=['-i',str(source),'-filter_complex','[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[x];[x][2:a]acrossfade=d=1:c1=tri:c2=tri,atrim=duration=10[a]']
        else:
            args+=['-filter_complex','[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[a]']
        run(args+['-map','[a]','-c:a','pcm_s16le',str(OUT/f'{dest}.wav')])
    metrics=json.loads((OUT/'pilot_metrics.json').read_text())
    scores={'P1a_chain':metrics['P1a_seam']['percent_255'],'P1b_chain':max(metrics['P1b_seam_1']['percent_255'],metrics['P1b_seam_2']['percent_255']),'P1c_chain':metrics['P1c_seam']['percent_255']}
    winning=min(scores,key=scores.get)
    run(['ffmpeg','-v','error','-y','-i',str(OUT/f'{winning}.mp4'),'-stream_loop','-1','-i',str(OUT/'location_loop_test.wav'),'-filter_complex','[1:a]volume=-14dB[b];[0:a][b]amix=inputs=2:duration=first:normalize=0[a]','-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-shortest',str(OUT/'P3c_mix_check.mp4')])
    print('Pilot comparison chains, loop test, motif and P3c mix saved.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['verify','board','seams','motion','previews']);p.add_argument('key',nargs='?');args=p.parse_args()
    if args.action=='verify': verify(args.key)
    elif args.action=='board': board()
    elif args.action=='seams': seams()
    elif args.action=='motion': motion()
    else: previews()
