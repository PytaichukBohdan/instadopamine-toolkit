"""Minimal Gemini REST client for private media analysis (no SDK dependency).

The key comes only from GEMINI_API_KEY. Uploaded files are deleted after use;
responses stay in the private corpus with model and usage provenance.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import random
import time
from pathlib import Path

import requests

BASE = 'https://generativelanguage.googleapis.com'
RETRY = {408, 429, 500, 502, 503, 504}
# Requests are limited to 20 MB after base64 expansion.
INLINE_LIMIT = 14 * 1024 * 1024


def key():
    value = os.environ.get('GEMINI_API_KEY')
    if not value:
        raise ValueError('GEMINI_API_KEY is required for Gemini analysis')
    return value


def _request(method, url, *, attempts=6, **kwargs):
    for attempt in range(attempts):
        try:
            response = requests.request(method, url, headers={'x-goog-api-key': key(), **kwargs.pop('headers', {})}, **kwargs)
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt + random.random())
            continue
        if response.status_code in RETRY and attempt < attempts - 1:
            time.sleep(min(60, 3 * 2 ** attempt) + random.random() * 2)
            continue
        if not response.ok:
            message = response.text[:400]
            try:
                message = response.json().get('error', {}).get('message', message)[:400]
            except ValueError:
                pass
            raise RuntimeError(f'Gemini HTTP {response.status_code}: {message}')
        return response
    raise RuntimeError('Gemini request did not complete')


def upload(path: Path, mime_type: str | None = None, timeout=900):
    """Upload through the resumable Files API and wait until the file is ACTIVE."""
    mime_type = mime_type or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    size = path.stat().st_size
    start = _request('POST', f'{BASE}/upload/v1beta/files', timeout=(20, 60), headers={
        'X-Goog-Upload-Protocol': 'resumable', 'X-Goog-Upload-Command': 'start',
        'X-Goog-Upload-Header-Content-Length': str(size), 'X-Goog-Upload-Header-Content-Type': mime_type,
        'Content-Type': 'application/json'}, json={'file': {'display_name': path.name[:120]}})
    url = start.headers['X-Goog-Upload-URL']
    with path.open('rb') as data:
        done = _request('POST', url, timeout=(20, 600), data=data, headers={
            'Content-Length': str(size), 'X-Goog-Upload-Offset': '0', 'X-Goog-Upload-Command': 'upload, finalize'})
    file = done.json()['file']
    deadline = time.time() + timeout
    while file.get('state') == 'PROCESSING':
        if time.time() > deadline:
            delete(file['name'])
            raise RuntimeError('Gemini file processing timed out')
        time.sleep(4)
        file = _request('GET', f"{BASE}/v1beta/{file['name']}", timeout=(20, 60)).json()
    if file.get('state') != 'ACTIVE':
        delete(file['name'])
        raise RuntimeError(f"Gemini file is {file.get('state')}")
    return file


def delete(name):
    try:
        _request('DELETE', f'{BASE}/v1beta/{name}', timeout=(20, 60), attempts=2)
    except (RuntimeError, requests.RequestException):
        pass


def media_part(path: Path, mime_type: str | None = None):
    """Return (part, uploaded_file_or_None). Small files go inline; large files are uploaded."""
    mime_type = mime_type or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    if path.stat().st_size <= INLINE_LIMIT:
        return {'inline_data': {'mime_type': mime_type, 'data': base64.b64encode(path.read_bytes()).decode()}}, None
    file = upload(path, mime_type)
    return {'file_data': {'mime_type': mime_type, 'file_uri': file['uri']}}, file


def generate(model, parts, *, system=None, json_output=True, temperature=0.2, max_output_tokens=32768, timeout=900, attempts=2, thinking=None):
    """Call generateContent; a malformed JSON reply is retried once before failing.

    `thinking` ('low'/'high') sets Gemini 3 thinking level; thinking tokens count against max_output_tokens."""
    for attempt in range(attempts):
        try:
            return _generate(model, parts, system, json_output, temperature, max_output_tokens, timeout, thinking)
        except json.JSONDecodeError:
            if attempt == attempts - 1:
                raise


def _generate(model, parts, system, json_output, temperature, max_output_tokens, timeout, thinking=None):
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'temperature': temperature, 'maxOutputTokens': max_output_tokens}}
    if thinking:
        body['generationConfig']['thinkingConfig'] = {'thinkingLevel': thinking}
    if json_output:
        body['generationConfig']['responseMimeType'] = 'application/json'
    if system:
        body['systemInstruction'] = {'parts': [{'text': system}]}
    response = _request('POST', f'{BASE}/v1beta/models/{model}:generateContent', json=body, timeout=(20, timeout))
    payload = response.json()
    candidates = payload.get('candidates') or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidate: {json.dumps(payload.get('promptFeedback', {}))[:300]}")
    candidate = candidates[0]
    text = ''.join(p.get('text', '') for p in candidate.get('content', {}).get('parts', []) if not p.get('thought'))
    if candidate.get('finishReason') not in (None, 'STOP'):
        raise RuntimeError(f"Gemini finished with {candidate.get('finishReason')}")
    meta = {'model': payload.get('modelVersion', model), 'response_id': payload.get('responseId'),
            'usage': payload.get('usageMetadata'), 'finish_reason': candidate.get('finishReason')}
    return (json.loads(text) if json_output else text), meta
