from __future__ import annotations
import json, math, subprocess, hashlib, os, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw

ROOT=Path.cwd(); WORK=ROOT/'render'; RELEASE=ROOT/'release'; REVIEW=ROOT/'donk-review'
for p in [WORK,RELEASE,REVIEW,WORK/'shots']:p.mkdir(parents=True,exist_ok=True)
FPS=30; SR=48000; W=1920; H=1080

def run(cmd,timeout=600):
    p=subprocess.run([str(x) for x in cmd],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError(' '.join(str(x) for x in cmd)+'\n'+p.stdout[-7000:])
    return p.stdout

def probe(path):return json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',path],40))

def source(alias):
    kind,name=alias.split(':',1)
    folder={'main':ROOT/'source/main/media','supp':ROOT/'source/supp/media','photo':ROOT/'source/discovery/photos'}[kind]
    return folder/(name if '.' in name else name+'.mp4')

def render_shot(pair):
    i,s=pair;p=source(s['file']);assert p.is_file(),p
    out=WORK/'shots'/f'{i:03d}.mp4';frames=int(s['frames']);dur=frames/FPS;speed=float(s.get('speed',1));start=float(s.get('in',0))
    still=p.suffix.lower() in ['.jpg','.jpeg','.png','.webp'];pr=probe(p);v=next(x for x in pr['streams'] if x['codec_type']=='video');iw,ih=v['width'],v['height']
    if not still:assert start+dur*speed<=float(pr['format']['duration'])+0.08,(s,pr['format']['duration'])
    args=['ffmpeg','-v','error','-y','-filter_complex_threads','1']
    args+=['-loop','1','-framerate',str(FPS),'-i',p] if still else ['-ss',f'{start:.6f}','-i',p]
    pre=f'setpts=(PTS-STARTPTS)/{speed},fps={FPS},setsar=1'
    if s.get('crop'):
        a=s['crop'];pre+=f',crop=iw*{a[0]}:ih*{a[1]}:iw*{a[2]}:ih*{a[3]}';iw*=a[0];ih*=a[1]
    mode=s.get('frame','auto');fc=[]
    if mode=='portrait' or (iw/ih<1.3 and mode!='fill'):
        fc=[f'[0:v]{pre},split=2[a][b]',f'[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.16:saturation=0.45[bg]',f'[b]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg]',f'[bg][fg]overlay=(W-w)/2:(H-h)/2[fr]']
    else:
        zoom=float(s.get('zoom',1.035 if still else 1));sw=math.ceil(W*zoom/2)*2;sh=math.ceil(H*zoom/2)*2
        cx=float(s.get('cx',.5));cy=float(s.get('cy',.5));px=float(s.get('pan_x',.06 if still else 0));py=float(s.get('pan_y',0))
        fc=[f'[0:v]{pre},scale={sw}:{sh}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={W}:{H}:x=\'(iw-ow)*({cx}+{px}*t/{dur})\':y=\'(ih-oh)*({cy}+{py}*t/{dur})\'[fr]']
    grade=s.get('grade','neutral')
    g={'neutral':'eq=contrast=1.035:saturation=0.94:brightness=-0.007','warm':'eq=contrast=1.035:saturation=0.99,colorbalance=rs=0.015:bs=-0.008','memory':'eq=contrast=1.025:saturation=0.63:brightness=-0.009','loss':'eq=contrast=1.045:saturation=0.45:brightness=-0.026','game':'eq=contrast=1.015:saturation=0.98'}[grade]
    if s.get('fade_in'):g+=f",fade=t=in:st=0:d={s['fade_in']}"
    if s.get('fade_out'):g+=f",fade=t=out:st={dur-s['fade_out']}:d={s['fade_out']}"
    fc.append(f'[fr]{g},format=yuv420p,settb=1/90000[out]')
    args+=['-filter_complex',';'.join(fc),'-map','[out]','-frames:v',str(frames),'-an','-c:v','libx264','-preset','fast','-crf','19','-threads','2','-video_track_timescale','90000','-movflags','+faststart',out]
    run(args,600);n=probe(out);actual=next(x for x in n['streams'] if x['codec_type']=='video');assert int(actual.get('nb_frames',frames))==frames
    print('SHOT',i,s['file'],start,dur,flush=True);return out

def ass_time(t):
    cs=round(float(t)*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100);return f'{h}:{m:02d}:{s:02d}.{cs:02d}'

def make_subs(captions):
    head='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Story,Noto Serif CJK SC,54,&H00F8F6F1,&H00F8F6F1,&H80100808,&HB0000000,0,0,0,0,100,100,1.6,0,1,2.4,1.2,1,112,112,112,1
Style: Title,Noto Serif CJK SC,120,&H00FAF7F0,&H00FAF7F0,&HA0151010,&HD0000000,-1,0,0,0,100,100,8,0,1,1.5,1.2,1,112,112,172,1
Style: Label,Noto Sans CJK SC,27,&H00D9D4CC,&H00D9D4CC,&H70000000,&HD0000000,0,0,0,0,100,100,3,0,1,1.4,1,7,112,112,84,1
Style: Event,Noto Sans CJK SC,37,&H00F8F6F1,&H00F8F6F1,&H70000000,&HC0000000,-1,0,0,0,100,100,1,0,1,1.7,1,7,112,112,124,1
Style: Credit,Noto Sans CJK SC,23,&H00D8D4D0,&H00D8D4D0,&H60000000,&HC0000000,0,0,0,0,100,100,0.4,0,1,1.2,0.7,1,112,112,62,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[head]
    for c in captions:
        text=c['text'].replace('{','').replace('}','').replace('\n',r'\N');fade=c.get('fade',[220,280]);tags=f'\\fad({fade[0]},{fade[1]})'
        if c.get('pos'):tags+='\\pos('+','.join(str(x) for x in c['pos'])+')'
        if c.get('align'):tags+=f"\\an{c['align']}"
        if c.get('size'):tags+=f"\\fs{c['size']}"
        if c.get('spacing'):tags+=f"\\fsp{c['spacing']}"
        lines.append(f"Dialogue: {c.get('layer',0)},{ass_time(c['start'])},{ass_time(c['end'])},{c.get('style','Story')},,0,0,0,,{{{tags}}}{text}\n")
    path=WORK/'titles.ass';path.write_text(''.join(lines),encoding='utf-8-sig');return path

def get_audio(path,start,dur,target,name,speed=1):
    out=WORK/(name+'.wav');af=f'aresample={SR},aformat=channel_layouts=stereo'
    if speed!=1:af+=f',atempo={speed}'
    af+=f',atrim=0:{dur},loudnorm=I={target}:TP=-2:LRA=11,aresample={SR}'
    run(['ffmpeg','-v','error','-y','-ss',start,'-i',path,'-t',dur*speed,'-vn','-af',af,'-ar',SR,'-ac','2','-c:a','pcm_f32le',out],180)
    y,sr=sf.read(out,dtype='float32',always_2d=True);assert sr==SR;return y

def envelope(n,fade_in=.08,fade_out=.25):
    e=np.ones(n,np.float32);a=min(round(fade_in*SR),n//2);b=min(round(fade_out*SR),n//2)
    if a:e[:a]=np.linspace(0,1,a,dtype=np.float32)
    if b:e[-b:]=np.linspace(1,0,b,dtype=np.float32)
    return e

def mix_audio(plan,duration):
    count=round(duration*SR);src=ROOT/plan['music']['file'];music=get_audio(src,plan['music']['in'],duration,-16,'music')
    assert len(music)>=count-1024,(len(music),count)
    bed=np.zeros((count,2),np.float32);bed[:min(count,len(music))]=music[:count]
    duck=np.ones(count,np.float32);live=np.zeros_like(bed)
    for i,e in enumerate(plan.get('audio',[])):
        d=float(e['duration']);part=get_audio(source(e['file']),e['in'],d,e.get('lufs',-23),'live_'+str(i),float(e.get('speed',1)))
        start=round(e['start']*SR);n=min(len(part),round(d*SR),count-start);assert start>=0 and n>0
        env=envelope(n,.10,.3);live[start:start+n]+=part[:n]*env[:,None]*float(e.get('gain',1))
        lo=max(0,start-round(.18*SR));hi=min(count,start+n+round(.45*SR));de=np.ones(hi-lo,np.float32)*float(e.get('duck',.74));a=start-lo;b=hi-(start+n)
        if a:de[:a]=np.linspace(1,e.get('duck',.74),a)
        if b:de[-b:]=np.linspace(e.get('duck',.74),1,b)
        duck[lo:hi]=np.minimum(duck[lo:hi],de)
    bed*=duck[:,None];out=(bed+live)*envelope(count,.4,3.5)[:,None]
    peak=float(np.abs(out).max());ceiling=10**(-1/20)
    gain=min(1.,ceiling/max(peak,1e-8));out*=gain
    path=WORK/'mix.wav';sf.write(path,out,SR,subtype='PCM_24')
    return path,{'sample_rate':SR,'sample_count':count,'peak_before_limit':peak,'final_peak_dbfs':float(20*np.log10(max(np.abs(out).max(),1e-8))),'master_gain':gain,'continuous_source_window':[plan['music']['in'],plan['music']['in']+duration]}

def main():
    plan=json.loads(Path('donk-project/plan.json').read_text());t=0
    for s in plan['shots']:
        s['frames']=round(s.pop('duration')*FPS) if 'duration' in s else int(s['frames']);s['timeline_in']=t/FPS;t+=s['frames'];s['timeline_out']=t/FPS
    duration=t/FPS;assert duration>100
    (WORK/'resolved_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    with ThreadPoolExecutor(max_workers=2) as pool:paths=list(pool.map(render_shot,enumerate(plan['shots'])))
    concat=WORK/'concat.txt';concat.write_text(''.join("file '"+str(p)+"'\n" for p in paths))
    picture=WORK/'picture.mp4';run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',concat,'-c','copy',picture])
    titles=make_subs(plan['captions']);mix,audioqc=mix_audio(plan,duration)
    final=RELEASE/'DONK_留住所有人_1080p.mp4'
    run(['ffmpeg','-v','error','-y','-filter_threads','2','-i',picture,'-i',mix,'-map','0:v:0','-map','1:a:0','-vf',f'ass={titles}','-frames:v',t,'-c:v','libx264','-preset','medium','-crf','20','-maxrate','9M','-bufsize','18M','-threads','4','-c:a','aac','-b:a','256k','-ar',SR,'-movflags','+faststart','-video_track_timescale','90000','-metadata','title=留住所有人 | DONK · 兄弟CS','-metadata','comment=主题创作，非选手原话。使用有来源记录的比赛与战队影像。',final],1200)
    qc={'duration':duration,'frames_expected':t,'shots':len(plan['shots']),'audio':audioqc,'probe':probe(final),'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'file':final.name,'size_bytes':final.stat().st_size,'manual_visual_review':False}
    video=next(s for s in qc['probe']['streams'] if s['codec_type']=='video');assert int(video['nb_frames'])==t;assert (video['width'],video['height'])==(W,H);assert any(s['codec_type']=='audio' for s in qc['probe']['streams'])
    run(['ffmpeg','-v','error','-xerror','-i',final,'-f','null','-'],500);qc['full_decode']='passed'
    loud=run(['ffmpeg','-hide_banner','-i',final,'-af','loudnorm=I=-16:TP=-1:LRA=11:print_format=json','-vn','-f','null','-'],180)
    (REVIEW/'audio_measurement.txt').write_text(loud[-1500:])
    # Exact final frames, evenly spaced through each chapter; these are review aids, not synthetic scenes.
    pages=[]
    for page in range(math.ceil(duration/40)):
        sheet=Image.new('RGB',(1280,816),(16,16,16));dr=ImageDraw.Draw(sheet)
        for j in range(16):
            ts=page*40+j*2.5+.3
            if ts>=duration:continue
            f=WORK/f'qc_{page}_{j}.jpg';run(['ffmpeg','-v','error','-y','-ss',ts,'-i',final,'-frames:v','1','-vf','scale=320:180',f],30)
            sheet.paste(Image.open(f),(j%4*320,j//4*204));dr.text((j%4*320+5,j//4*204+184),f'{ts:.2f}s',fill='white')
        dst=REVIEW/f'film_contact_{page+1}.jpg';sheet.save(dst,quality=88);pages.append(dst.name)
    qc['contact_sheets']=pages;(REVIEW/'render_qc.json').write_text(json.dumps(qc,ensure_ascii=False,indent=2))
    shutil.copy(WORK/'resolved_plan.json',REVIEW/'resolved_plan.json')
    readme='留住所有人｜DONK · 兄弟CS\n\n成片：'+final.name+f'\n规格：1920×1080，30fps，H.264 / AAC，时长{duration:.2f}秒。\n配乐：《不谓侠》于春洋（DJ版），使用同一音源的连续时间窗口，没有循环拼歌。\n\n片中主题文字为创作表达，不是 donk 或队友的原话。阵容变化与比赛日期依据赛事和战队记录；档案影像清晰度各有差异。\n\n已完成：全片解码、帧数、音视频流、音乐连续性和峰值检查。\n限制：交互式图像预览环境故障，最后的人工逐帧视觉复核未完成。\n\n主要资料：\nhttps://www.hltv.org/news/36594/spirit-announce-new-roster-with-academy-trio-including-donk\nhttps://www.hltv.org/news/40565/spirit-defeat-faze-2-1-to-win-shanghai-major\nhttps://www.hltv.org/news/43475/magixx-and-zont1x-return-to-spirit-roster-as-chopper-and-zweih-are-benched\nhttps://www.hltv.org/events/8249/blast-open-porto-2026\n\n视频来源：Team Spirit、HLTV、ESL / IEM、赛事 Twitch 公开片段。音乐音源：\nhttps://www.facebook.com/jeff.primus.9/videos/9315192298569572/\n\nSHA256：'+qc['sha256']+'\n'
    (RELEASE/'成片说明.txt').write_text(readme,encoding='utf-8-sig')
    print(json.dumps(qc,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
