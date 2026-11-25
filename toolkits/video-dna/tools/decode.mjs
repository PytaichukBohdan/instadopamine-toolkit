// Decode a Higgsfield blog content blob (Yjs update of a Lexical editor doc) into a JSON tree.
// Usage: node decode.mjs <file.bin>  -> JSON on stdout
import * as Y from 'yjs';
import fs from 'fs';

const doc = new Y.Doc();
Y.applyUpdate(doc, new Uint8Array(fs.readFileSync(process.argv[2])));

function walk(node) {
  if (node instanceof Y.XmlText) {
    const kids = node.toDelta().map(d => typeof d.insert === 'string' ? { text: d.insert } : walk(d.insert));
    return { kind: 'xmltext', attrs: node.getAttributes(), kids };
  }
  if (node instanceof Y.XmlElement) {
    return { kind: 'xmlel', name: node.nodeName, attrs: node.getAttributes(), kids: node.toArray().map(walk) };
  }
  if (node instanceof Y.Map) return { kind: 'map', data: node.toJSON() };
  if (node instanceof Y.Array) return { kind: 'array', data: node.toJSON() };
  return { kind: 'other', v: String(node) };
}

console.log(JSON.stringify({ tree: walk(doc.get('root', Y.XmlText)) }));
