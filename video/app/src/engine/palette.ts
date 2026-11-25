import { hexToLinear } from './util';

// The whole video lives in a restrained palette: ink, bone, and one signal colour.
// One rare accent (acid, the shrooms moment) — see docs/TREATMENT.md.
export const HEX = {
  ink: '#0A0A0B', // background black (slightly warm)
  ink2: '#151517', // raised black (panels, paper-in-the-dark)
  graphite: '#5E5B57', // dim lines, secondary text
  ash: '#9C978F', // mid grey
  bone: '#EEE9DF', // paper white, primary text
  signal: '#FF4D12', // hazard orange: the spark, the fuse, P(doom)
  ember: '#FF8A3D', // hotter, lighter orange for cores/highlights
  blood: '#C21D0B', // deep red-orange for shadows of signal
  acid: '#D8FF3C', // acid: only for the shrooms moment
  // Caption colours: the reference-reel caption red, plus white and script colours for the person's own styles
  fp: '#ED1410', // caption red sampled from the two reference reels (median of caption pixels: 237,20,13 and 242,0,11)
  white: '#FFFFFF', // her big white bold caption block (atlas A008)
  script: '#F6E52A', // her yellow neon script word (atlas A015)
} as const;

export type PaletteKey = keyof typeof HEX;

/** Linear RGB triplets for GL uniforms. */
export const LIN: Record<PaletteKey, [number, number, number]> = Object.fromEntries(
  Object.entries(HEX).map(([k, v]) => [k, hexToLinear(v)]),
) as Record<PaletteKey, [number, number, number]>;

/** CSS rgba() for Canvas2D. */
export function rgba(key: PaletteKey | string, a = 1): string {
  const hex = (HEX as Record<string, string>)[key] ?? key;
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
