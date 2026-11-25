#!/usr/bin/env python3
"""Reference-conditioned Ukrainian synthesis. Heavy model dependencies are optional.

Outputs are private working artifacts, not a Pages publication directory.
Review stress bases before running. A preflight proves coverage, not correctness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instadna.pronunciation import check_text, make_ledger, validate_ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['styletts2', 'omnivoice'], required=True)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--bases', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--reference-text', type=Path, help='Exact transcript of the reference clip; required for OmniVoice')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, help='OmniVoice target duration; actual duration must be checked')
    parser.add_argument('--seed', type=int, default=872)
    parser.add_argument('--steps', type=int, default=24)
    parser.add_argument('--speed', type=float, default=1.0)
    args = parser.parse_args()
    if args.speed <= 0 or args.steps <= 0 or (args.duration is not None and args.duration <= 0):
        parser.error('Speed, steps and duration must be positive')
    if args.engine == 'omnivoice' and not args.reference_text:
        parser.error('OmniVoice needs the exact reference transcript')
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        parser.error('Use an empty private output directory')
    script = json.loads(args.script.read_text())
    texts = [line['marked_text'] for line in script['lines']]
    for line in script['lines']:
        errors = check_text(line['marked_text'], line['text'])
        if errors:
            parser.error('; '.join(errors))
    bases = json.loads(args.bases.read_text())
    model_id = ('patriotyk/styletts2_ukrainian_multispeaker_hifigan'
                if args.engine == 'styletts2' else 'k2-fsa/OmniVoice')
    request = dict(engine=args.engine, model=model_id, seed=args.seed, steps=args.steps,
                   speed=args.speed, duration=args.duration, sections=texts,
                   reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                   reference_text=args.reference_text.read_text().strip() if args.reference_text else None,
                   styletts_alpha=0, styletts_beta=0,
                   note='Directions are editorial metadata; these backends use audio conditioning, not the direction prose.')
    raw = json.dumps(request, ensure_ascii=False, indent=2).encode()
    ledger = make_ledger(raw, texts, bases, 'Supplied per-occurrence contextual review bases')
    validate_ledger(raw, texts, ledger)
    (args.output / 'request.json').write_bytes(raw)
    (args.output / 'pronunciation-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    import numpy as np
    import soundfile as sf
    import torch
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    if args.engine == 'styletts2':
        from ipa_uk import ipa
        from styletts2_inference.models import StyleTTS2
        model = StyleTTS2(hf_path=model_id, device='cpu')
        model.eval()
        pieces, timeline, cursor = [], [], 0
        with torch.inference_mode():
            style = model.predict_style_multi(str(args.reference), model.tokenizer.encode(ipa(texts[0])),
                                              alpha=0, beta=0, diffusion_steps=10)
            torch.save(style, args.output / 'private-voice-profile.pt')
            for index, text in enumerate(texts):
                wav = model(model.tokenizer.encode(ipa(text)), speed=args.speed, s_prev=style).cpu().numpy()
                sf.write(args.output / f'phrase-{index:02}.wav', wav, 24000)
                timeline.append(dict(index=index, start=cursor, end=cursor + len(wav)/24000))
                pieces.extend([wav, np.zeros(8400)])
                cursor += len(wav)/24000 + .35
        wav, rate = np.concatenate(pieces), 24000
        (args.output / 'source-timeline.json').write_text(json.dumps(timeline, indent=2))
    else:
        from omnivoice import OmniVoice
        model = OmniVoice.from_pretrained(model_id, device_map='cpu', dtype=torch.float32)
        prompt = model.create_voice_clone_prompt(str(args.reference), ref_text=request['reference_text'], preprocess_prompt=False)
        prompt.save(str(args.output / 'private-voice-profile.pt'))
        wav = model.generate(text='\n\n'.join(texts), language='uk', voice_clone_prompt=prompt,
                             duration=args.duration, speed=args.speed, num_step=args.steps)[0]
        rate = model.sampling_rate
    path = args.output / 'voice.wav'
    sf.write(path, wav, rate)
    receipt = dict(duration_s=len(wav)/rate, sample_rate=rate,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   model_license='MIT' if args.engine == 'styletts2' else 'CC-BY-NC-4.0; non-commercial research')
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
