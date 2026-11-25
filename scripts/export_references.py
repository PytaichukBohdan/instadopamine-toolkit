"""Reproduce an existing editorial reference manifest from the private source corpus."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from PIL import Image, ImageOps
from instadna.collect import shortcode

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--root',type=Path,required=True)
p.add_argument('--wiki',type=Path,required=True)
a=p.parse_args();manifest=a.wiki/'visual-atlas.json';d=json.loads(manifest.read_text())
for row in d['references']:
    code=shortcode(row['source_url']);index=row['asset_index']
    if code != row['shortcode']:raise ValueError('Source URL and shortcode disagree')
    if not isinstance(index,int) or index<0:raise ValueError('Invalid asset index')
    prepared=json.loads((a.root/'posts'/code/f'asset-{index:02d}'/'frames.json').read_text())
    src=a.root/prepared['asset']
    if not src.resolve().is_relative_to(a.root.resolve()):raise ValueError('Source outside corpus')
    if hashlib.sha256(src.read_bytes()).hexdigest()!=row['source_asset_sha256']:raise ValueError('Original source hash mismatch')
    for field in ['image','thumbnail']:
        path=a.wiki/row[field]
        if not path.resolve().is_relative_to((a.wiki/'references').resolve()) or path.is_symlink():raise ValueError('Output outside references')
        path.parent.mkdir(parents=True,exist_ok=True)
    dest=a.wiki/row['image'];t=row['time_seconds']
    if prepared['kind']=='video':
        if t is None or not 0<=t<prepared['duration']:raise ValueError('Invalid video time')
        subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(t),'-i',str(src),'-frames:v','1','-y',str(dest)],check=True)
    else:
        if t is not None:raise ValueError('Still image cannot have time')
        with Image.open(src) as img:ImageOps.exif_transpose(img).convert('RGB').save(dest)
    with Image.open(dest) as img:
        row['width'],row['height']=img.size
        ImageOps.contain(img.convert('RGB'),(540,720)).save(a.wiki/row['thumbnail'],quality=85)
    row['sha256']=hashlib.sha256(dest.read_bytes()).hexdigest()
    row['thumbnail_sha256']=hashlib.sha256((a.wiki/row['thumbnail']).read_bytes()).hexdigest()
manifest.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print(f"Prepared {len(d['references'])} selected references")
