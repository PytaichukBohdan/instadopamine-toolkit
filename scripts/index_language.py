"""Count disclosed lexical patterns in recovered captions and ASR, retaining locators."""
import argparse, json, re, hashlib
from pathlib import Path

PATTERNS = [
 ('not-hryvnias','не гривень / не грн',r'\bне\s+(?:гривень|грн)\b'),
 ('randoms','randoms / рандомс',r'\b(?:randoms|рандомс)\b'),
 ('lets-go','поїхали',r'\bпоїхали\b'),
 ('thanks','дякую',r'\bдякую\b'),
 ('friends','друзі',r'\bдрузі\b'),
 ('comments','коментар* / комментар*',r'\b(?:коментар|комментар)\w*'),
 ('i-think','я думаю',r'\bя\s+думаю\b'),
 ('i-say','я кажу',r'\bя\s+кажу\b'),
 ('well','ну',r'\bну\b'),
 ('just','просто',r'\bпросто\b'),
 ('anyway','коротше / короче',r'\b(?:коротше|короче)\b'),
 ('by-the-way','до речі',r'\bдо\s+речі\b'),
 ('how-much','скільки / сколько',r'\b(?:скільки|сколько)\b'),
 ('taking-off','заліта* / залета*',r'\b(?:заліта|залета)\w*'),
 ('content','контент*',r'\bконтент\w*'),
 ('algorithms','алгоритм*',r'\bалгоритм\w*'),
 ('shadowban','тіньовий бан / теневой бан',r'\b(?:тіньовий|теневой)\s+бан\b'),
 ('youtube','YouTube / ютуб* / ютьюб*',r'\b(?:youtube|ютуб\w*|ютьюб\w*)\b'),
 ('tiktok','TikTok / тікто* / тикто*',r'\b(?:tik\s?tok|тікто\w*|тикто\w*)\b'),
 ('reels','рілс* / рилс* / reels',r'\b(?:рілс\w*|рилс\w*|reels)\b'),
 ('direct','Дірект / директ',r'\b(?:дірект|директ)\b'),
 ('growth','підписник* / подписчик*',r'\b(?:підписник|подписчик)\w*'),
 ('gt3','GT3',r'\bgt3\b'),
 ('coca-cola','кока-кол* / Coca-Cola',r'\b(?:кока[ -]?кол\w*|coca[ -]?cola)\b'),
 ('norm-cringe','норм / стрьом / стрём',r'\b(?:норм|стрьом|стрём)\b'),
]

def build_index(root):
    rows=[]; inputs=[]; post_count=0; speech_count=0; owners={}
    for analysis in sorted(root.glob('posts/*/analysis.json')):
        code=analysis.parent.name;meta=analysis.parent/'media.json'; d=json.loads(meta.read_text());owner=d['owner']['username'];owners[code]=owner;post_count+=1
        cap=' '.join(e['node']['text'] for e in d.get('edge_media_to_caption',{}).get('edges',[]))
        rows.append({'shortcode':code,'owner':owner,'kind':'caption','text':cap})
        inputs.append({'shortcode':code,'kind':'metadata','sha256':hashlib.sha256(meta.read_bytes()).hexdigest()})
        for p in sorted(analysis.parent.glob('asset-*/transcript-openai.json')):
            speech_count+=1; t=json.loads(p.read_text()); asset=int(p.parent.name.removeprefix('asset-'))
            inputs.append({'shortcode':code,'kind':'whisper-1','asset_index':asset,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
            for seg in t.get('segments',[]):rows.append({'shortcode':code,'owner':owner,'kind':'speech','asset_index':asset,'start':seg['start'],'end':seg['end'],'text':seg['text']})
    terms=[]
    for ident,label,pattern in PATTERNS:
        matches=[]
        for row in rows:
            hits=list(re.finditer(pattern,row['text'],re.I))
            if hits:matches.append({**{k:v for k,v in row.items() if k!='text'},'occurrences':len(hits),'matched_forms':sorted(set(h.group(0) for h in hits))})
        terms.append({'id':ident,'label':label,'regex':pattern,'caption_posts':len({m['shortcode'] for m in matches if m['kind']=='caption'}),'speech_posts':len({m['shortcode'] for m in matches if m['kind']=='speech'}),'matches':matches})
    manifest=root/'manifest.json'
    username=json.loads(manifest.read_text())['username'] if manifest.exists() else None
    return {'version':1,'posts':post_count,'audio_transcripts':speech_count,'owner_posts':sum(v==username for v in owners.values()),'method':'Case-insensitive regex, no translation or automatic lemmatization; * in labels denotes the disclosed regex family. Counts are distinct post IDs per channel, never creator-only frequency or independent episode counts. Speech matches must fit inside one Whisper segment. Reposts may share a conversation.','terms':terms,'input_hashes':inputs}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    data=build_index(a.root);a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    for t in data['terms']:print(t['label'],t['caption_posts'],t['speech_posts'])
