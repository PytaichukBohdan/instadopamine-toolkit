#!/usr/bin/env node
/** Fetch selected media from a PUBLIC Telegram channel by message ID into a PRIVATE directory.
 * Use it for files the t.me web preview does not expose (large videos, documents).
 * Runtime: Node 22+ and teleproto. Credentials arrive only through TELEGRAM_API_ID,
 * TELEGRAM_API_HASH and TELEGRAM_SESSION. Read-only: resolves the public username and
 * reads the requested messages. It never logs in, joins, sends or marks anything read.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const hash = value => crypto.createHash('sha256').update(value).digest('hex');
function save(file, value) {
  fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2) + '\n', {mode: 0o600});
  fs.renameSync(file + '.tmp', file);
}
function parseArgs(argv) {
  const args = {kinds: ['video', 'document'], maxBytes: 300 * 1024 * 1024};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--channel') args.channel = argv[++i];
    else if (argv[i] === '--ids') args.ids = argv[++i].split(',').map(Number);
    else if (argv[i] === '--output') args.output = argv[++i];
    else if (argv[i] === '--kinds') args.kinds = argv[++i].split(',');
    else if (argv[i] === '--max-mb') args.maxBytes = Number(argv[++i]) * 1024 * 1024;
    else throw Error('Unknown argument');
  }
  if (!/^[A-Za-z0-9_]{4,32}$/.test(args.channel || '') || !args.output || !args.ids?.length
      || args.ids.some(id => !Number.isSafeInteger(id) || id <= 0)) {
    throw Error('Use --channel USERNAME --ids 1,2,3 --output /private/dir [--kinds video,document] [--max-mb 300]');
  }
  return args;
}
function describe(m) {
  const doc = m.media?.document;
  if (!doc) return null;
  const attr = name => doc.attributes?.find(a => a.className === name);
  const video = attr('DocumentAttributeVideo');
  const audio = attr('DocumentAttributeAudio');
  return {document_id: doc.id.toString(), mime_type: doc.mimeType, bytes: Number(doc.size),
    filename: attr('DocumentAttributeFilename')?.fileName || null,
    duration: video?.duration ?? audio?.duration ?? null, kind: video ? (video.roundMessage ? 'round_video' : 'video') : audio ? 'audio' : 'document'};
}
async function fetchMedia(args, sdk) {
  process.umask(0o077);
  const {TelegramClient, Api, StringSession, Logger, LogLevel} = sdk;
  for (const key of ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_SESSION']) {
    if (!process.env[key]) throw Error(`Missing ${key}`);
  }
  const root = path.resolve(args.output);
  fs.mkdirSync(path.join(root, 'files'), {recursive: true, mode: 0o700});
  const manifestFile = path.join(root, 'manifest.json');
  const manifest = fs.existsSync(manifestFile) ? JSON.parse(fs.readFileSync(manifestFile, 'utf8'))
    : {version: 1, channel: args.channel, method: 'existing user session; public username resolved; messages read by ID', files: {}};
  if (manifest.channel !== args.channel) throw Error('Output belongs to another channel');
  const client = new TelegramClient(new StringSession(process.env.TELEGRAM_SESSION),
    Number(process.env.TELEGRAM_API_ID), process.env.TELEGRAM_API_HASH,
    {connectionRetries: 1, requestRetries: 2, autoReconnect: false, timeout: 30, floodSleepThreshold: 0,
      baseLogger: new Logger(LogLevel.NONE), deviceModel: 'InstaDopamine source reader', appVersion: '1.0'});
  try {
    await client.connect();
    const me = await client.getMe();
    if (me.bot || (process.env.TELEGRAM_EXPECTED_ACCOUNT_ID && me.id.toString() !== process.env.TELEGRAM_EXPECTED_ACCOUNT_ID)) {
      throw Error('Account identity mismatch');
    }
    const resolved = await client.invoke(new Api.contacts.ResolveUsername({username: args.channel}));
    const chat = resolved.chats.find(c => c instanceof Api.Channel && c.username?.toLowerCase() === args.channel.toLowerCase());
    if (!chat) throw Error('Username is not a public channel');
    manifest.channel_id = chat.id.toString();
    const peer = new Api.InputPeerChannel({channelId: chat.id, accessHash: chat.accessHash});
    for (let i = 0; i < args.ids.length; i += 50) {
      const batch = await client.getMessages(peer, {ids: args.ids.slice(i, i + 50)});
      for (const m of batch) {
        if (!m || !(m instanceof Api.Message)) continue;
        const info = describe(m);
        const key = String(m.id);
        if (!info || !args.kinds.includes(info.kind === 'round_video' ? 'video' : info.kind)) {
          manifest.files[key] = {message_id: m.id, status: 'skipped_kind', ...(info || {})};
          continue;
        }
        const old = manifest.files[key];
        if (old?.status === 'downloaded' && fs.existsSync(path.join(root, old.path))) continue;
        if (info.bytes > args.maxBytes) {
          manifest.files[key] = {message_id: m.id, status: 'skipped_size', ...info};
          continue;
        }
        const ext = path.extname(info.filename || '') || {'video/mp4': '.mp4', 'application/pdf': '.pdf'}[info.mime_type] || '.bin';
        const relative = `files/${m.id}-${info.document_id}${ext.toLowerCase()}`;
        const destination = path.join(root, relative);
        try {
          await client.downloadMedia(m, {outputFile: destination + '.part'});
          const bytes = fs.readFileSync(destination + '.part');
          if (bytes.length !== info.bytes) throw Error('Downloaded size does not match source metadata');
          fs.renameSync(destination + '.part', destination);
          manifest.files[key] = {message_id: m.id, status: 'downloaded', path: relative, sha256: hash(bytes),
            published_at: new Date(m.date * 1000).toISOString(), retrieved_at: new Date().toISOString(), ...info};
        } catch (error) {
          if (fs.existsSync(destination + '.part')) fs.unlinkSync(destination + '.part');
          manifest.files[key] = {message_id: m.id, status: 'failed', error: error.errorMessage || error.code || error.name, ...info};
          if (String(manifest.files[key].error).startsWith('FLOOD_WAIT')) {save(manifestFile, manifest); throw error;}
        }
        save(manifestFile, manifest);
        console.log(JSON.stringify({message_id: m.id, kind: info.kind, status: manifest.files[key].status, bytes: info.bytes}));
      }
    }
    manifest.finished_at = new Date().toISOString();
    save(manifestFile, manifest);
  } finally {await client.destroy();}
}

module.exports = {parseArgs, describe, fetchMedia};
if (require.main === module) {
  const {TelegramClient, Api} = require('teleproto');
  const {StringSession} = require('teleproto/sessions/index.js');
  const {Logger, LogLevel} = require('teleproto/extensions/Logger.js');
  fetchMedia(parseArgs(process.argv.slice(2)), {TelegramClient, Api, StringSession, Logger, LogLevel})
    .catch(error => {console.error(JSON.stringify({error: error.errorMessage || error.code || error.message}));process.exitCode = 1;});
}
