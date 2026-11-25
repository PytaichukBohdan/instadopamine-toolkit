#!/usr/bin/env node
/** Read an already-authorized Telegram channel into a PRIVATE corpus.
 * Runtime: Node 22+ and teleproto, supplied by an isolated private environment.
 * Credentials arrive only through TELEGRAM_API_ID, TELEGRAM_API_HASH and
 * TELEGRAM_SESSION. This script never logs in, joins, sends or marks read.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const iso = value => value ? new Date(value * 1000).toISOString() : null;
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
function save(file, value) {
  fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2) + '\n', {mode: 0o600});
  fs.renameSync(file + '.tmp', file);
}
function parseArgs(argv) {
  const args = {downloadAudio: false};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--download-audio') args.downloadAudio = true;
    else if (argv[i] === '--invite') args.invite = argv[++i];
    else if (argv[i] === '--output') args.output = argv[++i];
    else throw Error('Unknown argument');
  }
  if (!/^https:\/\/t\.me\/\+[A-Za-z0-9_-]+$/.test(args.invite || '') || !args.output) {
    throw Error('Use --invite https://t.me/+INVITE --output /private/corpus [--download-audio]');
  }
  return args;
}
function messageRecord(m, channelId) {
  const doc = m.media?.document;
  const audio = doc?.attributes?.find(a => a.className === 'DocumentAttributeAudio');
  const video = doc?.attributes?.find(a => a.className === 'DocumentAttributeVideo');
  const file = doc?.attributes?.find(a => a.className === 'DocumentAttributeFilename');
  return {
    id: m.id, source_url: `https://t.me/c/${channelId}/${m.id}`,
    published_at: iso(m.date), edited_at: iso(m.editDate), retrieved_at: new Date().toISOString(),
    text: m.message || '', post_author: m.postAuthor || null,
    grouped_id: m.groupedId?.toString() || null,
    forward: m.fwdFrom ? {date: iso(m.fwdFrom.date), from_name: m.fwdFrom.fromName || null,
      channel_post: m.fwdFrom.channelPost || null, imported: Boolean(m.fwdFrom.imported)} : null,
    reply_to: m.replyTo?.replyToMsgId || null,
    media_kind: m.media?.className || null,
    document: doc ? {id: doc.id?.toString(), mime_type: doc.mimeType, bytes: Number(doc.size),
      filename: file?.fileName || null, duration: audio?.duration ?? video?.duration ?? null,
      audio: Boolean(audio), voice: Boolean(audio?.voice), video: Boolean(video),
      round_video: Boolean(video?.roundMessage)} : null,
  };
}
async function collect(args, sdk) {
  process.umask(0o077);
  const {TelegramClient, Api, StringSession, Logger, LogLevel} = sdk;
  for (const key of ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_SESSION']) {
    if (!process.env[key]) throw Error(`Missing ${key}`);
  }
  const root = path.resolve(args.output);
  fs.mkdirSync(root, {recursive: true, mode: 0o700});
  const manifestFile = path.join(root, 'manifest.json');
  const messagesFile = path.join(root, 'messages.jsonl');
  let manifest = fs.existsSync(manifestFile) ? JSON.parse(fs.readFileSync(manifestFile, 'utf8')) : null;
  if (manifest && manifest.invite_sha256 !== hash(args.invite)) throw Error('Corpus belongs to another invite');
  const client = new TelegramClient(new StringSession(process.env.TELEGRAM_SESSION),
    Number(process.env.TELEGRAM_API_ID), process.env.TELEGRAM_API_HASH,
    {connectionRetries: 1, requestRetries: 2, autoReconnect: false, timeout: 12,
      floodSleepThreshold: 0, baseLogger: new Logger(LogLevel.NONE),
      deviceModel: 'InstaDopamine source reader', appVersion: '1.0'});
  try {
    await client.connect();
    const me = await client.getMe();
    if (me.bot || (process.env.TELEGRAM_EXPECTED_ACCOUNT_ID && me.id.toString() !== process.env.TELEGRAM_EXPECTED_ACCOUNT_ID)) {
      throw Error('Account identity mismatch');
    }
    const invite = await client.invoke(new Api.messages.CheckChatInvite({hash: args.invite.split('+')[1]}));
    if (!(invite instanceof Api.ChatInviteAlready)) throw Error('Existing account must already belong to the requested channel');
    const chat = invite.chat;
    if (!(chat instanceof Api.Channel)) throw Error('Requested source is not a channel');
    const channelId = chat.id.toString();
    if (manifest && manifest.channel_id !== channelId) throw Error('Channel identity changed');
    const peer = new Api.InputPeerChannel({channelId: chat.id, accessHash: chat.accessHash});
    if (!manifest) {
      const newest = await client.getMessages(peer, {limit: 1});
      manifest = {version: 1, source: 'telegram', channel_id: channelId, title: chat.title,
        invite_sha256: hash(args.invite), retrieved_at: new Date().toISOString(),
        snapshot_max_id: newest[0]?.id || 0, last_offset_id: 0, history_scan_exhausted: false,
        account_complete: false, collection_method: 'Existing user session; paginated channel history',
        limits: 'Accessible snapshot only; deletions, prior edits and inaccessible history cannot be recovered.',
        audio_downloads: []};
      save(manifestFile, manifest);
    }
    const records = new Map();
    if (fs.existsSync(messagesFile)) for (const line of fs.readFileSync(messagesFile, 'utf8').split('\n').filter(Boolean)) {
      const row = JSON.parse(line); records.set(row.id, row);
    }
    while (!manifest.history_scan_exhausted) {
      // teleproto takes max(offsetId, maxId). Passing the fixed snapshot maxId
      // on every page would therefore keep returning the newest page.
      const batch = await client.getMessages(peer, {limit: 100,
        offsetId: manifest.last_offset_id || manifest.snapshot_max_id + 1});
      if (!batch.length) {manifest.history_scan_exhausted = true; save(manifestFile, manifest); break;}
      const ids = batch.map(m => m.id).filter(id => Number.isInteger(id) && id > 0);
      const next = Math.min(...ids);
      if (!ids.length || (manifest.last_offset_id && next >= manifest.last_offset_id)) throw Error('History pagination stopped progressing');
      for (const m of batch) {
        if (!(m instanceof Api.Message) || records.has(m.id)) continue;
        const row = messageRecord(m, channelId);
        fs.appendFileSync(messagesFile, JSON.stringify(row) + '\n', {mode: 0o600}); records.set(row.id, row);
      }
      manifest.last_offset_id = next; manifest.messages_retrieved = records.size;
      save(manifestFile, manifest);
      console.log(JSON.stringify({stage: 'history',messages: records.size,oldest_id: next}));
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    const rows = [...records.values()];
    const audioRows = rows.filter(r => r.document?.audio && !r.document.video);
    const unique = new Map(audioRows.map(r => [r.document.id, r]));
    Object.assign(manifest, {messages_retrieved: rows.length,
      text_messages: rows.filter(r => r.text.trim()).length,
      forwarded_messages: rows.filter(r => r.forward).length,
      first_publication: rows.map(r => r.published_at).filter(Boolean).sort()[0] || null,
      last_publication: rows.map(r => r.published_at).filter(Boolean).sort().at(-1) || null,
      audio_messages: audioRows.length, unique_audio_documents: unique.size,
      unique_audio_seconds: [...unique.values()].reduce((n,r) => n + (r.document.duration || 0), 0),
      messages_sha256: fs.existsSync(messagesFile) ? hash(fs.readFileSync(messagesFile)) : null});
    save(manifestFile, manifest);
    if (args.downloadAudio) {
      fs.mkdirSync(path.join(root, 'audio'), {recursive: true, mode: 0o700});
      const completed = new Map(manifest.audio_downloads.map(r => [r.document_id, r]));
      for (const [documentId, row] of unique) {
        const old = completed.get(documentId);
        if (old?.status === 'downloaded' && fs.existsSync(path.join(root, old.path)) &&
          hash(fs.readFileSync(path.join(root, old.path))) === old.sha256) continue;
        const ext = {'audio/ogg': '.ogg', 'audio/mpeg': '.mp3', 'audio/mp4': '.m4a', 'audio/wav': '.wav'}[row.document.mime_type] || '.bin';
        const relative = `audio/${documentId}${ext}`;
        const destination = path.join(root, relative);
        const record = {message_id: row.id, document_id: documentId, path: relative};
        try {
          const [fresh] = await client.getMessages(peer, {ids: [row.id]});
          if (fresh?.media?.document?.id?.toString() !== documentId) throw Error('Document changed or disappeared');
          await client.downloadMedia(fresh, {outputFile: destination + '.part'});
          const bytes = fs.readFileSync(destination + '.part');
          if (bytes.length !== row.document.bytes) throw Error('Downloaded size does not match source metadata');
          fs.renameSync(destination + '.part', destination);
          Object.assign(record, {status: 'downloaded', bytes: bytes.length, sha256: hash(bytes), retrieved_at: new Date().toISOString()});
        } catch (error) {
          Object.assign(record, {status: 'failed', error: error.errorMessage || error.code || error.name});
          if (fs.existsSync(destination + '.part')) fs.unlinkSync(destination + '.part');
        }
        completed.set(documentId, record); manifest.audio_downloads = [...completed.values()]; save(manifestFile, manifest);
        console.log(JSON.stringify({stage: 'audio',message_id: row.id,status: record.status,finished: completed.size,total: unique.size}));
        if (record.error?.startsWith('FLOOD_WAIT')) break;
      }
    }
    manifest.finished_at = new Date().toISOString(); save(manifestFile, manifest);
    console.log(JSON.stringify({stage: 'complete',messages: rows.length,audio_documents: unique.size,
      audio_seconds: manifest.unique_audio_seconds,history_scan_exhausted: manifest.history_scan_exhausted}));
  } finally {await client.destroy();}
}

module.exports = {parseArgs, messageRecord, collect};
if (require.main === module) {
  const {TelegramClient, Api} = require('teleproto');
  const {StringSession} = require('teleproto/sessions/index.js');
  const {Logger, LogLevel} = require('teleproto/extensions/Logger.js');
  collect(parseArgs(process.argv.slice(2)), {TelegramClient, Api, StringSession, Logger, LogLevel})
    .catch(error => {console.error(JSON.stringify({error: error.errorMessage || error.code || error.message}));process.exitCode = 1;});
}
