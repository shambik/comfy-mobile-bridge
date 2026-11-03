"""FFmpeg final assembly, continuous bed/motif, titles and loudness proof."""
import argparse
import json
import math
import os
import re
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from night_train_media import mad, verify

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'night_train'

def command(args,log=None):
    result=subprocess.run(args,capture_output=True)
    if log:(OUT/log).write_bytes(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace')[-5000:])
    return result

def duration(path):
    r=command(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=duration,nb_frames,r_frame_rate','-of','json',str(path)])
    v=json.loads(r.stdout)['streams'][0]
    return int(v['nb_frames'])/24

def title_images(width,height):
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    large=ImageFont.truetype(str(fonts/'georgiab.ttf'),int(height*.115))
    small=ImageFont.truetype(str(fonts/'georgia.ttf'),int(height*.042))
    for name,heading,subheading in [('title','Night Train','Episode 1 · The Stowaway'),('end','The End','A little kindness before dawn')]:
        im=Image.new('RGB',(width,height),(15,25,37));draw=ImageDraw.Draw(im)
        draw.rounded_rectangle((width*.07,height*.13,width*.93,height*.87),radius=24,outline=(135,104,55),width=3)
        draw.text((width/2,height*.43),heading,font=large,fill=(248,223,170),anchor='mm')
        draw.text((width/2,height*.61),subheading,font=small,fill=(204,188,156),anchor='mm')
        im.save(OUT/f'{name}.png')

def loop_bed(length):
    source=OUT/'P3a_audio.wav'
    count=max(2,math.ceil((length-1)/4)+1)
    args=['ffmpeg','-v','error','-y']
    for _ in range(count):args+=['-i',str(source)]
    filters=['[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[b1]']
    current='b1'
    for n in range(2,count):
        label=f'b{n}';filters.append(f'[{current}][{n}:a]acrossfade=d=1:c1=tri:c2=tri[{label}]');current=label
    filters.append(f'[{current}]atrim=duration={length:.9f},asetpts=PTS-STARTPTS[bed]')
    command(args+['-filter_complex',';'.join(filters),'-map','[bed]','-c:a','pcm_s16le',str(OUT/'continuous_bed.wav')],'bed-loop.log')

def volume(path):
    r=command(['ffmpeg','-hide_banner','-i',str(path),'-af','volumedetect','-f','null','-'])
    return float(re.findall(r'mean_volume: ([\-\d.]+) dB',r.stderr.decode(errors='replace'))[-1])

def assemble():
    keys=[f'C{i}' for i in range(1,9)]
    lengths=[duration(OUT/f'{k}.mp4') for k in keys]
    probe=json.loads(command(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(OUT/'C1.mp4')]).stdout)['streams'][0]
    width,height=probe['width'],probe['height'];title_images(width,height)
    seams={f'{keys[i]}→{keys[i+1]}':mad(f'{keys[i]}_last.png',f'{keys[i+1]}_first.png') for i in range(7)}
    (OUT/'production_seams.json').write_text(json.dumps(seams,indent=2,ensure_ascii=False))
    # True picture dissolves only where the numerical seam exceeds 3%.
    overlaps=[0.125 if seams[f'{keys[i]}→{keys[i+1]}']['percent_255']>=3 and i not in {2,4} else 0 for i in range(7)]
    args=['ffmpeg','-v','error','-y']
    for k in keys:args+=['-i',str(OUT/f'{k}.mp4')]
    filters=[]
    for i,length in enumerate(lengths):
        filt=f'[{i}:v]fps=24,setsar=1,settb=AVTB,setpts=PTS-STARTPTS'
        if i in {3,5}:filt+=',fade=t=in:st=0:d=0.25'
        if i in {2,4}:filt+=f',fade=t=out:st={length-.25:.9f}:d=0.25'
        filters.append(filt+f'[v{i}]')
        filters.append(f'[{i}:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={length:.9f},asetpts=PTS-STARTPTS[a{i}]')
    cv,ca='v0','a0';elapsed=lengths[0]
    joins=[]
    for i in range(1,8):
        nv,na=f'jv{i}',f'ja{i}';overlap=overlaps[i-1]
        if overlap:
            filters.append(f'[{cv}][v{i}]xfade=transition=fade:duration={overlap}:offset={elapsed-overlap:.9f}[{nv}]')
            filters.append(f'[{ca}][a{i}]acrossfade=d={overlap}:c1=tri:c2=tri[{na}]')
        else:
            filters.append(f'[{cv}][v{i}]concat=n=2:v=1:a=0[{nv}]')
            filters.append(f'[{ca}][a{i}]concat=n=2:v=0:a=1[{na}]')
        joins.append(2+elapsed-overlap);elapsed+=lengths[i]-overlap;cv,ca=nv,na
    filters.append(f'[{cv}]format=yuv420p[v]')
    filters.append(f'[{ca}]anull[a]')
    script=OUT/'assembly-filter.txt';script.write_text(';\n'.join(filters))
    command(args+['-filter_complex_script',str(script),'-map','[v]','-map','[a]','-c:v','libx264','-preset','fast','-crf','17','-c:a','pcm_s16le',str(OUT/'story.mkv')],'story-assembly.log')
    total=elapsed+4
    # Add two-second cards, one grade and uniform grain over the complete film.
    filt=(f'[0:v]scale={width}:{height},fps=24,setsar=1,trim=duration=2,setpts=PTS-STARTPTS[t];'
          '[1:v]setsar=1,setpts=PTS-STARTPTS[s];'
          f'[2:v]scale={width}:{height},fps=24,setsar=1,trim=duration=2,setpts=PTS-STARTPTS[e];'
          '[t][s][e]concat=n=3:v=1:a=0,eq=contrast=1.02:brightness=-0.005:saturation=0.96,noise=alls=5:allf=t,format=yuv420p[v]')
    command(['ffmpeg','-v','error','-y','-loop','1','-framerate','24','-i',str(OUT/'title.png'),'-i',str(OUT/'story.mkv'),'-loop','1','-framerate','24','-i',str(OUT/'end.png'),'-filter_complex',filt,'-map','[v]','-an','-t',str(total),'-c:v','libx264','-preset','fast','-crf','18',str(OUT/'picture.mp4')],'picture.log')
    command(['ffmpeg','-v','error','-y','-i',str(OUT/'story.mkv'),'-vn','-af',f'adelay=2000|2000,apad,atrim=duration={total:.9f}','-c:a','pcm_s16le',str(OUT/'foley.wav')])
    loop_bed(total)
    bed_gain=volume(OUT/'foley.wav')-14-volume(OUT/'continuous_bed.wav')
    dining_start=joins[2];dining_end=joins[4];luggage_start=joins[4];luggage_end=joins[5]
    find_time=2+sum(lengths[:5])-sum(overlaps[:5])+4.5
    motif_len=9.0
    motif_level=-12
    af=(f'[0:a]anull[f];[1:a]volume={bed_gain:.4f}dB,'
        f"treble=g=2:enable='between(t,{dining_start:.6f},{dining_end:.6f})',"
        f"lowpass=f=1800:enable='between(t,{luggage_start:.6f},{luggage_end:.6f})'[b];"
        f'[2:a]asplit=3[m0][m1][m2];'
        f'[m0]volume={motif_level}dB,afade=t=in:d=0.25,afade=t=out:st=7.5:d=1.5[x0];'
        f'[m1]volume={motif_level-5}dB,afade=t=in:d=0.5,afade=t=out:st=7.5:d=1.5,adelay={int(find_time*1000)}|{int(find_time*1000)}[x1];'
        f'[m2]volume={motif_level}dB,afade=t=in:d=0.5,afade=t=out:st=8:d=1,adelay={int((total-motif_len)*1000)}|{int((total-motif_len)*1000)}[x2];'
        f'[f][b][x0][x1][x2]amix=inputs=5:normalize=0:duration=longest,atrim=duration={total:.9f}[mix]')
    command(['ffmpeg','-v','error','-y','-i',str(OUT/'foley.wav'),'-i',str(OUT/'continuous_bed.wav'),'-i',str(OUT/'music_motif.wav'),'-filter_complex',af,'-map','[mix]','-c:a','pcm_s24le',str(OUT/'mix_unmastered.wav')],'mix.log')
    norm=command(['ffmpeg','-hide_banner','-i',str(OUT/'mix_unmastered.wav'),'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'])
    normtext=norm.stderr.decode(errors='replace');loud=json.loads(normtext[normtext.rfind('{'):])
    (OUT/'loudness-pass1.json').write_text(json.dumps(loud,indent=2))
    normfilter=f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={loud['input_i']}:measured_TP={loud['input_tp']}:measured_LRA={loud['input_lra']}:measured_thresh={loud['input_thresh']}:offset={loud['target_offset']}:linear=true:print_format=json"
    command(['ffmpeg','-hide_banner','-y','-i',str(OUT/'picture.mp4'),'-i',str(OUT/'mix_unmastered.wav'),'-map','0:v','-map','1:a','-c:v','copy','-af',normfilter,'-ar','48000','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(OUT/'Night_Train_E01_The_Stowaway.mp4')],'final-master.log')
    verify('Night_Train_E01_The_Stowaway')
    command(['ffmpeg','-hide_banner','-i',str(OUT/'Night_Train_E01_The_Stowaway.mp4'),'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],'loudness-final.log')
    report={'duration_seconds':total,'story_seconds':elapsed,'clip_durations':dict(zip(keys,lengths)),'dissolve_seconds':overlaps,'joins_seconds':joins,'bed_relative_foley_db':-14,'bed_gain_db':bed_gain,'grade':'eq=contrast=1.02:brightness=-0.005:saturation=0.96','grain':'noise=alls=5:allf=t','review':'User performs visual and listening review; no AGY used.'}
    (OUT/'assembly_report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.parse_args();assemble()
