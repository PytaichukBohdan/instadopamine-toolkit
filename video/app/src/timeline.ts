// The edit: one timeline entry per storyboard shot. Shot windows and caption times are resolved here from
// word anchors ([line, word] in data/lyrics.json) through the Lyrics API, never hard-coded, so they follow
// the aligned voice. scripts/build_storyboard.py resolves the same anchors for the report; a mismatch is logged.
import type { TimelineEntry } from './engine/engine';
import type { SceneClass } from './engine/scene';
import type { Lyrics, Word } from './engine/lyrics';
import type { AudioData } from './engine/audio';

const modules = import.meta.glob<{ default: SceneClass }>('./scenes/*.ts');
const scene = (name: string) => () => {
  const m = modules[`./scenes/${name}.ts`];
  return m ? m() : Promise.reject(new Error(`scene module not found: scenes/${name}.ts`));
};

export type Anchor = [number, number];
/** A cut on a word start (minus lead), a montage cut `plus` seconds after the end of a word, or an absolute time
 * (`at`, written by scripts/align_cuts_to_music.py when cuts sit on the music's beats). */
export type Cut = Anchor | { after: Anchor; plus?: number } | { at: number; from?: unknown; snap?: string };
export interface BoardCaption { at: Anchor; to?: Anchor; text?: string; style: 'fp' | 'script' }
export interface BoardShot {
  id: string; type: string; title: string; cut: Cut | null; lead: number; camera?: string;
  caption_zone: string | null; caption_at?: string | null; captions: BoardCaption[]; start: number; end: number;
  frame?: { path: string } | null;
}
export interface Board { shots: BoardShot[]; format: { end_card: { start_after_line: number; gap_s: number; text: string } } }

/** A caption as the scenes draw it: display words with their sung start times. */
export interface Caption { text: string; style: 'fp' | 'script'; start: number; end: number; words: { w: string; start: number }[] }

const word = (ly: Lyrics, a: Anchor): Word => {
  const w = ly.lines[a[0]]?.words[a[1]];
  if (!w) throw new Error(`storyboard anchor not in lyrics: [${a.join(', ')}]`);
  return w;
};

/** Display form of a sung token: punctuation off (inner hyphens stay), Russian capitals for the serif voice. */
export function displayWord(w: string, style: 'fp' | 'script') {
  const bare = w.replace(/[«»"“”„.,:;!?…—–]/g, '').trim();
  return style === 'script' ? bare.toLocaleLowerCase('ru') : bare.toLocaleUpperCase('ru');
}

export function shotCaptions(ly: Lyrics, shot: BoardShot, start: number, end: number): Caption[] {
  const caps = shot.captions.map((c) => {
    const first = word(ly, c.at);
    const last = c.to ? word(ly, c.to) : first;
    const words = ly.words.slice(first.gi, last.gi + 1).map((w) => ({ w: displayWord(w.w, c.style), start: w.start }));
    return { text: c.text || words.map((w) => w.w).join(' '), style: c.style, start: first.start, end, words };
  });
  caps.forEach((c, i) => { c.end = i + 1 < caps.length ? caps[i + 1]!.start : end; });
  return caps.filter((c) => c.start < end && c.end > start);
}

export function makeTimeline(board: Board, ly: Lyrics, au: AudioData): TimelineEntry[] {
  const shots = board.shots.filter((s) => s.type !== 'anchor');
  const card = board.format.end_card;
  const cardStart = ly.lines[card.start_after_line]!.end + card.gap_s;
  const at = (c: Cut, lead: number) =>
    Array.isArray(c) ? word(ly, c).start - lead : 'at' in c ? c.at : word(ly, c.after).end + (c.plus ?? 0);
  const starts = shots.map((s, i) =>
    s.cut && !Array.isArray(s.cut) && 'at' in s.cut ? s.cut.at : i === 0 || !s.cut ? (s.type === 'card' ? cardStart : 0) : at(s.cut, s.lead));
  return shots.map((s, i) => {
    const start = starts[i]!;
    const end = s.type === 'card' ? au.duration : i + 1 < shots.length ? starts[i + 1]! : au.duration;
    if (Math.abs(start - s.start) > 0.002 || Math.abs(end - s.end) > 0.002)
      console.warn(`${s.id}: engine window ${start.toFixed(3)}–${end.toFixed(3)} differs from storyboard.json ${s.start}–${s.end}`);
    return {
      id: s.id, load: scene(s.type === 'card' ? 'card' : 'face'), start, end,
      params: { shot: s, captions: shotCaptions(ly, s, start, end), text: s.type === 'card' ? card.text : undefined },
    };
  });
}
