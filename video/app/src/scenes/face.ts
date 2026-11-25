// One storyboard shot: its start frame (a "plate") with a slow camera move, and the caption words synced
// to the voice. Caption grammar of the reference-reel reels: one key word at a time, serif capitals in red,
// placed in the shot's calm zone, appearing exactly on the sung word (never ahead of the voice). Her own
// caption styles (atlas A008 bold white block, A015 yellow script) are the other two `?captions=` options.
// With a video plate (clips/<shot>/index.json plus numbered JPEG frames, see scripts/prepare_clips.py), the shot
// plays its image-to-video clip instead of the still; a shot cut on a music hit lands with a short flash, a zoom
// recoil and a little shake.
import * as THREE from 'three';
import { Scene, type Frame } from '../engine/scene';
import { FSPass, Layer2D, W, H } from '../engine/gl';
import { F, font, layout, fitSize } from '../engine/type';
import { HEX } from '../engine/palette';
import { clamp, ease, lerp } from '../engine/util';
import type { BoardShot, Caption } from '../timeline';

type Mode = 'fp' | 'block' | 'mix';
const MODE: Mode = ((): Mode => {
  const m = typeof location === 'undefined' ? null : new URLSearchParams(location.search).get('captions');
  return m === 'block' || m === 'mix' ? m : 'fp';
})();

/** Caption baseline per calm zone (logical px), title-safe and clear of the reel UI at the bottom. */
const ZONE_Y: Record<string, number> = { top: 0.118 * H, 'upper third': 0.255 * H, 'middle third': 0.505 * H, 'lower third': 0.705 * H };
const SAFE = 96;
const MAX_W = W - 2 * SAFE;

export default class Face extends Scene {
  private shot = this.ctx.params.shot as BoardShot;
  private caps = this.ctx.params.captions as Caption[];
  private plate: THREE.Texture | null = null;
  private plateAspect = 9 / 16;
  private clip: { fps: number; frames: number } | null = null;
  private clipFrame = -1;
  private bg = new FSPass(/* glsl */ `
    uniform sampler2D tex; uniform vec4 xf; uniform float has;
    void main() {
      vec2 uv = (vUv - 0.5) * xf.xy + 0.5 + xf.zw;
      vec3 c = has > 0.5 ? texture(tex, uv).rgb : mix(C_INK, C_INK2, vUv.y);
      fragColor = vec4(c, 1.0);
    }`, { tex: { value: null }, xf: { value: new THREE.Vector4(1, 1, 0, 0) }, has: { value: 0 } });
  private text = new Layer2D();

  override async init() {
    try {
      const r = await fetch(`clips/${this.shot.id}/index.json`);
      this.clip = r.ok ? ((await r.json()) as { fps: number; frames: number }) : null;
    } catch {
      this.clip = null;
    }
    if (this.clip) return this.prepare(this.ctx.start);
    try {
      const tex = await new THREE.TextureLoader().loadAsync(`plates/${this.shot.id}.webp`);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.anisotropy = 4;
      this.plate = tex;
      const img = tex.image as { width: number; height: number };
      this.plateAspect = img.width / img.height;
    } catch {
      this.plate = null; // not generated yet: a dark placeholder with the shot label
    }
  }

  /** The clip frame for song time t (frame-exact, so a render is a pure function of t). */
  override async prepare(t: number) {
    if (!this.clip) return;
    const k = Math.min(this.clip.frames - 1, Math.max(0, Math.floor((t - this.ctx.start) * this.clip.fps + 1e-6)));
    if (k === this.clipFrame) return;
    const img = new Image();
    img.src = `clips/${this.shot.id}/${String(k).padStart(4, '0')}.jpg`;
    await img.decode();
    if (!this.plate) {
      this.plate = new THREE.Texture(img);
      this.plate.colorSpace = THREE.SRGBColorSpace;
      this.plate.minFilter = THREE.LinearFilter; // a new image every frame: no mipmaps
      this.plate.generateMipmaps = false;
    } else {
      this.plate.image = img;
    }
    this.plate.needsUpdate = true;
    this.plateAspect = img.naturalWidth / img.naturalHeight;
    this.clipFrame = k;
  }

  /** True when this shot's cut sits on a music hit (scripts/align_cuts_to_music.py). */
  private get onHit() {
    const c = this.shot.cut as { snap?: string } | null;
    return !!c && !Array.isArray(c) && c.snap === 'hit';
  }

  /** Deterministic camera move over the shot window (zoom >= 1 so the frame stays covered). */
  private camera(f: Frame): [number, number, number] {
    if (this.clip) return this.onHit ? [lerp(1.08, 1.0, ease.outExpo(clamp(f.lt / 0.3))), 0, 0] : [1.0, 0, 0];
    const s = ease.inOutQuad(clamp(f.p));
    switch (this.shot.camera ?? 'push') {
      case 'pull': return [lerp(1.07, 1.0, s), 0, 0];
      case 'left': return [1.07, lerp(0.022, -0.022, s), 0];
      case 'right': return [1.07, lerp(-0.022, 0.022, s), 0];
      case 'up': return [1.07, 0, lerp(-0.026, 0.026, s)];
      case 'down': return [1.07, 0, lerp(0.026, -0.026, s)];
      case 'punch': return [1 + 0.075 * ease.outExpo(clamp(f.lt / 0.35)), 0, 0];
      case 'static': return [1.02, 0, 0];
      default: return [lerp(1.0, 1.06, s), 0, 0];
    }
  }

  render(f: Frame, out: THREE.WebGLRenderTarget) {
    const { renderer, comp } = this.ctx;
    const [z, ox, oy] = this.camera(f);
    const frame = W / H;
    const sx = this.plateAspect > frame ? frame / this.plateAspect : 1;
    const sy = this.plateAspect > frame ? 1 : this.plateAspect / frame;
    (this.bg.u.xf!.value as THREE.Vector4).set(sx / z, sy / z, ox, oy);
    this.bg.u.tex!.value = this.plate;
    this.bg.u.has!.value = this.plate ? 1 : 0;
    this.bg.render(renderer, out);

    const c = this.text.ctx;
    this.text.clear();
    if (!this.plate) this.placeholder(c);
    const cap = this.caps.find((x) => f.t >= x.start && f.t < x.end);
    if (cap) {
      if (MODE === 'fp' || cap.style === 'script') this.drawKeyWord(c, cap, f.t);
      else this.drawBlock(c, f.t, MODE === 'mix' ? cap : null);
    }
    comp.draw(renderer, this.text.upload(), out);
    // photographic plates: no highlight shoulder, no glow on the type, only a little grain and vignette
    const post = { shoulder: 0, bloom: 0.06, bloomThreshold: 1.6, halation: 0, ca: 0.25, grain: 0.032, vignette: 0.16, hud: 0 };
    if (this.clip && (this.onHit || this.ctx.start === 0) && f.lt < 0.3) {
      const k = 1 - clamp(f.lt / 0.3);
      const flash = this.onHit ? 0.3 * Math.pow(1 - clamp(f.lt / 0.12), 2) : 0;
      const amp = 6 * k * k;
      return { ...post, flash, shake: [amp * Math.sin(f.lt * 97), amp * Math.cos(f.lt * 83)] as [number, number], ca: 0.25 + 1.5 * k };
    }
    return post;
  }

  private y() { const z = this.shot.caption_at ?? this.shot.caption_zone ?? 'middle third'; return ZONE_Y[z] ?? ZONE_Y['middle third']!; }

  /** reference-reel voice: the caption unit as serif capitals; each word appears on its sung start. */
  private drawKeyWord(c: CanvasRenderingContext2D, cap: Caption, t: number) {
    const script = cap.style === 'script';
    const family = script ? F.script() : F.serif(600);
    const tracking = script ? 0 : 3;
    const size = Math.min(script ? 230 : 168, fitSize(cap.text, family, MAX_W, script ? 230 : 168, tracking));
    const lay = layout(cap.text, family, size, tracking);
    const x0 = (W - lay.width) / 2, y = this.y();
    // word boundaries inside the unit, so later words stay hidden until they are sung: display words map
    // one-to-one to sung words when the counts match ('10 ЛЕТ' = десять лет), otherwise appear on the first
    const words = cap.text.split(' ');
    const oneToOne = words.length === cap.words.length;
    let gi = 0;
    words.forEach((wtext, k) => {
      const sung = cap.words[oneToOne ? k : 0]!.start;
      const chars = Array.from(wtext).length;
      const first = lay.glyphs[gi]!;
      gi += chars + 1;
      const age = t - sung;
      if (age < 0) return;
      const a = clamp(age / 0.05), s = lerp(1.06, 1, ease.outExpo(clamp(age / 0.18)));
      const wx = x0 + first.x, ww = layoutWidth(wtext, family, size, tracking);
      c.save();
      c.globalAlpha = a;
      c.translate(wx + ww / 2, y - size * 0.3);
      c.scale(s, s);
      c.translate(-(wx + ww / 2), -(y - size * 0.3));
      c.font = font(family, size);
      c.letterSpacing = `${tracking}px`;
      c.textBaseline = 'alphabetic';
      if (script) { c.shadowColor = 'rgba(246,229,42,0.85)'; c.shadowBlur = 26; }
      c.fillStyle = script ? HEX.script : HEX.fp;
      c.fillText(wtext, wx, y);
      c.restore();
    });
  }

  /** Her own block (A008): the line's sung words in bold white lower case; `key` adds the A015 script word. */
  private drawBlock(c: CanvasRenderingContext2D, t: number, key: Caption | null) {
    const line = this.ctx.lyrics.lastLine(t);
    if (!line) return;
    const sung = line.words.filter((w) => w.start <= t).slice(-6).map((w) => w.w.replace(/[«»"“”.,:;!?…—–]/g, '').toLocaleLowerCase('ru')).filter(Boolean);
    if (key) {
      const keyText = key.text.toLocaleLowerCase('ru');
      const rest = sung.filter((w) => !keyText.split(' ').includes(w)).slice(-4);
      const y = this.y();
      c.save();
      c.font = font(F.script(), 150); c.fillStyle = HEX.script; c.shadowColor = 'rgba(246,229,42,0.8)'; c.shadowBlur = 22;
      c.fillText(keyText, SAFE, y - 70);
      c.restore();
      c.font = font(F.sans(600), 64); c.fillStyle = HEX.white; c.shadowColor = 'rgba(0,0,0,0.45)'; c.shadowBlur = 14;
      wrap(c, rest.join(' '), MAX_W).forEach((l, i) => c.fillText(l, SAFE, y + 10 + i * 72));
      c.shadowBlur = 0;
      return;
    }
    c.font = font(F.sans(800), 92); c.fillStyle = HEX.white; c.shadowColor = 'rgba(0,0,0,0.45)'; c.shadowBlur = 16;
    const lines = wrap(c, sung.join(' '), MAX_W).slice(-3);
    const y0 = this.y() - (lines.length - 1) * 92;
    lines.forEach((l, i) => c.fillText(l, SAFE, y0 + i * 98));
    c.shadowBlur = 0;
  }

  private placeholder(c: CanvasRenderingContext2D) {
    c.font = font(F.mono(500), 30); c.fillStyle = 'rgba(238,233,223,0.55)';
    c.fillText(`${this.shot.id} · ${this.shot.title}`, SAFE, 150, MAX_W);
    c.fillText('frame not generated yet', SAFE, 196);
  }
}

function layoutWidth(text: string, family: string, size: number, tracking: number) {
  return layout(text, family, size, tracking).width;
}

function wrap(c: CanvasRenderingContext2D, text: string, max: number) {
  const out: string[] = [];
  let cur = '';
  for (const w of text.split(' ')) {
    const next = cur ? `${cur} ${w}` : w;
    if (c.measureText(next).width > max && cur) { out.push(cur); cur = w; } else cur = next;
  }
  if (cur) out.push(cur);
  return out;
}
