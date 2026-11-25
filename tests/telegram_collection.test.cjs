const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {collect, parseArgs} = require('../scripts/collect_telegram.cjs');

function fakeSDK({member = true, owner = '123'} = {}) {
  class Message {constructor(id) {this.id = id; this.date = 1700000000 + id; this.message = 'source ' + id;}}
  class Channel {constructor() {this.id = '777'; this.accessHash = 'private'; this.title = 'Test channel';}}
  class ChatInviteAlready {constructor() {this.chat = new Channel();}}
  const calls = [];
  const messages = [301, 201, 101, 1].map(id => new Message(id));
  class TelegramClient {
    async connect() {}
    async destroy() {}
    async getMe() {return {id: owner, bot: false};}
    async invoke() {return member ? new ChatInviteAlready() : {};}
    async getMessages(peer, options) {
      calls.push(options);
      if (!options.offsetId) return messages.slice(0, 1);
      // Match the SDK's maxId semantics to catch the repeated-page regression.
      const ceiling = Math.max(options.offsetId || 0, options.maxId || 0);
      return messages.filter(m => m.id < ceiling).slice(0, 2);
    }
  }
  return {calls, TelegramClient, Api: {Message, Channel, ChatInviteAlready,
    InputPeerChannel: class {}, messages: {CheckChatInvite: class {}}},
    StringSession: class {}, Logger: class {}, LogLevel: {NONE: 0}};
}

async function withCorpus(fn) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'telegram-test-'));
  const keys = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_SESSION', 'TELEGRAM_EXPECTED_ACCOUNT_ID'];
  const previous = Object.fromEntries(keys.map(k => [k, process.env[k]]));
  Object.assign(process.env, {TELEGRAM_API_ID: '1', TELEGRAM_API_HASH: 'fake', TELEGRAM_SESSION: 'fake', TELEGRAM_EXPECTED_ACCOUNT_ID: '123'});
  try {await fn(root);}
  finally {
    fs.rmSync(root, {recursive: true, force: true});
    for (const key of keys) if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
  }
}

test('paginated snapshot reaches older messages and resumes without another history scan', async () => {
  await withCorpus(async root => {
    const sdk = fakeSDK();
    const args = {invite: 'https://t.me/+example', output: root};
    await collect(args, sdk);
    const lines = fs.readFileSync(path.join(root, 'messages.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.deepEqual(lines.map(r => r.id), [301, 201, 101, 1]);
    assert.deepEqual(sdk.calls.map(c => c.offsetId).filter(Boolean), [302, 201, 1]);
    assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'))).account_complete, false);
    const count = sdk.calls.length;
    await collect(args, sdk);
    assert.equal(sdk.calls.length, count);
    assert.equal(fs.statSync(path.join(root, 'messages.jsonl')).mode & 0o777, 0o600);
  });
});

test('unjoined channels and mismatched accounts are refused before any history read', async () => {
  for (const options of [{member: false}, {owner: '456'}]) {
    await withCorpus(async root => {
      const sdk = fakeSDK(options);
      await assert.rejects(collect({invite: 'https://t.me/+example', output: root}, sdk));
      assert.equal(sdk.calls.length, 0);
      assert.equal(fs.existsSync(path.join(root, 'messages.jsonl')), false);
    });
  }
});

test('rejects unrelated URLs and unknown options', () => {
  assert.throws(() => parseArgs(['--invite', 'https://example.com/+abc', '--output', '/tmp/private']));
  assert.throws(() => parseArgs(['--join']));
});
