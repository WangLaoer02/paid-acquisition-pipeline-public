"""Verify a native A export against its approved reference and actual BGM source."""
from pathlib import Path
import argparse, hashlib, json, subprocess
import numpy as np
from PIL import Image, ImageDraw

def run(args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def pcm(path):
    data=run(['ffmpeg','-v','error','-i',str(path),'-vn','-ar','48000','-ac','2','-f','f32le','-'])
    return np.frombuffer(data,dtype='<f4').reshape(-1,2)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','reference','music','original','original-sha256','evidence'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args();e=Path(a.evidence);e.mkdir(parents=True,exist_ok=True)
    assert sha(a.original)==a.original_sha256,'Original project changed'
    probe=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',a.output]))
    (e/'export-probe.json').write_text(json.dumps(probe,indent=2))
    v=next(x for x in probe['streams'] if x['codec_type']=='video')
    audio_info=next(x for x in probe['streams'] if x['codec_type']=='audio')
    assert (v['width'],v['height'],v['avg_frame_rate'],int(v['nb_frames']))==(720,1280,'24/1',450)
    assert abs(float(v['duration'])-18.75)<1e-5
    assert audio_info['codec_name']=='aac' and audio_info['sample_rate']=='48000'
    run(['ffmpeg','-v','error','-xerror','-i',a.output,'-f','null','-'])
    audio=pcm(a.output);reference=pcm(a.reference);music=pcm(a.music)
    n=int(12.5*48000)
    candidates=[]
    for delay in (0,1024,2048):
        x=audio[delay:delay+n].ravel();y=music[:n].ravel()
        candidates.append((float(np.corrcoef(x,y)[0,1]),delay))
    correlation,delay=max(candidates)
    assert correlation>.99,'Exported music does not match its source'
    aligned=audio[delay:delay+n].ravel();bed=music[:n].ravel()
    ref_count=min(len(audio),len(reference))
    ref_corr=float(np.corrcoef(audio[:ref_count].ravel(),reference[:ref_count].ravel())[0,1])
    tail_corr=float(np.corrcoef(audio[14*48000:18*48000].ravel(),reference[14*48000:18*48000].ravel())[0,1])
    assert tail_corr>.98,'Dialogue/music tail differs from the adopted native reference'
    times=[0,4.5,7.833333,12.666667,12.75,14.4,16,17.7,18.708333]
    sheet=Image.new('RGB',(648,1224),(25,25,25));draw=ImageDraw.Draw(sheet)
    caption_comparisons=[]
    for i,t in enumerate(times):
        target=e/f'frame-{i}.png'
        run(['ffmpeg','-y','-v','error','-ss',str(t),'-i',a.output,'-frames:v','1',str(target)])
        im=Image.open(target).convert('RGB');thumb=im.copy();thumb.thumbnail((216,384))
        x=(i%3)*216;y=(i//3)*408;sheet.paste(thumb,(x,y));draw.text((x+5,y+387),f'{t:.3f}s',fill='white')
        if i>=5:
            old=e/f'reference-{i}.png'
            run(['ffmpeg','-y','-v','error','-ss',str(t),'-i',a.reference,'-frames:v','1',str(old)])
            old_im=Image.open(old).convert('RGB')
            crop=(0,760,720,1190)
            difference=float(np.mean(np.abs(np.asarray(im.crop(crop),dtype=float)-np.asarray(old_im.crop(crop),dtype=float))))
            caption_comparisons.append({'time':t,'caption_area_pixel_mae_vs_adopted_reference':difference})
    sheet.save(e/'contactsheet.jpg',quality=94)
    qa={'output':a.output,'output_sha256':sha(a.output),'original_sha256_unchanged':sha(a.original),
        'duration':18.75,'frames':450,'size':[720,1280],'fps':24,'full_decode_passed':True,
        'audio_peak_dbfs':float(20*np.log10(np.max(np.abs(audio)))),
        'music_alignment_delay_samples':delay,'music_first_12_5s_correlation':correlation,
        'music_gain':float(np.dot(aligned,bed)/np.dot(bed,bed)),
        'audio_correlation_vs_adopted_v005':ref_corr,'dialogue_and_music_tail_correlation':tail_corr,
        'caption_comparisons':caption_comparisons,'caption_visual_review':'pending',
        'complete_human_listening':'not claimed','user_adoption_of_new_test_export':'not requested'}
    (e/'export-qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2))
    assert sha(a.original)==a.original_sha256
    print(json.dumps(qa,ensure_ascii=False))

if __name__=='__main__':main()
