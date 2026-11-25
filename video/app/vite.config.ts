import { defineConfig, normalizePath, type Plugin } from 'vite';
import { readFileSync } from 'node:fs';
import path from 'node:path';

// video/app → repository root. The edit's inputs (word timings, storyboard, voice, plates) stay where the
// repository keeps them; video/projects/<name>.json maps them to /data/* and /plates/* (read-only, never copied).
const repoRoot = path.resolve(import.meta.dirname, '..', '..');
// VIDEO_PROJECT selects video/projects/<name>.json (default: the current round).
const projectName = process.env.VIDEO_PROJECT ?? 'example';
const project = JSON.parse(readFileSync(path.resolve(import.meta.dirname, '..', 'projects', `${projectName}.json`), 'utf8')) as {
  data: Record<string, string>; plates: string; clips?: string;
};
// Video plates (image-to-video clips cut into frames by scripts/prepare_clips.py) live in private storage, outside the
// repository: an absolute path, or one relative to the repository root.
const clipsDir = process.env.VIDEO_CLIPS ? path.resolve(process.env.VIDEO_CLIPS) : project.clips ? path.resolve(repoRoot, project.clips) : null;

function projectAssets(): Plugin {
  const fsUrl = (rel: string) => `/@fs/${encodeURI(normalizePath(path.join(repoRoot, rel)))}`;
  return {
    name: 'project-assets',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = (req.url ?? '').split('?')[0]!;
        const data = /^\/data\/([\w.-]+)$/.exec(url);
        if (data && project.data[data[1]!]) req.url = fsUrl(project.data[data[1]!]!);
        const plate = /^\/plates\/([\w.-]+\.webp)$/.exec(url);
        if (plate) req.url = fsUrl(path.join(project.plates, plate[1]!));
        const clip = /^\/clips\/([\w-]+)\/([\w.-]+\.(?:jpg|json))$/.exec(url);
        if (clip && clipsDir) req.url = `/@fs/${encodeURI(normalizePath(path.join(clipsDir, clip[1]!, clip[2]!)))}`;
        next();
      });
    },
  };
}

export default defineConfig({
  root: '.',
  publicDir: 'public',
  plugins: [projectAssets()],
  // PDOOM_NO_HMR=1: no live reload (export renders must not reload mid-run when a file changes)
  server: { port: 5173, strictPort: false, hmr: process.env.PDOOM_NO_HMR ? false : undefined, fs: { allow: clipsDir ? [repoRoot, clipsDir] : [repoRoot] } },
  build: { target: 'esnext', assetsInlineLimit: 0 },
});
