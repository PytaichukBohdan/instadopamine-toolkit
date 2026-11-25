// End card, as in the reference reels: a black frame with one small line of red serif capitals.
// Her name stands where their brand stands.
import * as THREE from 'three';
import { Scene, type Frame } from '../engine/scene';
import { Layer2D, W, H, clearRT } from '../engine/gl';
import { F, font, layout } from '../engine/type';
import { HEX } from '../engine/palette';
import { clamp } from '../engine/util';

export default class Card extends Scene {
  private text = new Layer2D();
  private label = String(this.ctx.params.text ?? '');

  render(f: Frame, out: THREE.WebGLRenderTarget) {
    clearRT(this.ctx.renderer, out, [0, 0, 0]);
    const c = this.text.ctx;
    this.text.clear();
    const size = 46, tracking = 5;
    const lay = layout(this.label, F.serif(600), size, tracking);
    c.globalAlpha = clamp(f.lt / 0.25);
    c.font = font(F.serif(600), size);
    c.letterSpacing = `${tracking}px`;
    c.fillStyle = HEX.fp;
    c.fillText(this.label, (W - lay.width) / 2, H * 0.5 + size * 0.3);
    this.ctx.comp.draw(this.ctx.renderer, this.text.upload(), out);
    return { shoulder: 0, bloom: 0, halation: 0, ca: 0, grain: 0.02, vignette: 0, hud: 0 };
  }
}
