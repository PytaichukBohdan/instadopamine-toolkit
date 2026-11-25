// Pages serves static Range requests as 200. Native audio seeking needs 206.
// Only the small, explicitly published audio and video exports (under 25 MiB) use this bounded buffer path.
export async function audioRangeResponse(request, response) {
  if (!/^\/(audio\/[a-z0-9-]+\.(mp3|wav)|video\/[a-z0-9-]+\.mp4)$/.test(new URL(request.url).pathname)
      || response.status !== 200 || response.headers.has('Content-Encoding')) return response;
  const headers = new Headers(response.headers);
  headers.set('Accept-Ranges', 'bytes');
  const range = request.headers.get('Range');
  const validator = request.headers.get('If-Range');
  if (request.method !== 'GET' || !range || (validator
      && validator !== headers.get('ETag') && validator !== headers.get('Last-Modified'))) {
    return new Response(response.body, {status: response.status, headers});
  }
  // Multiple/malformed ranges may be ignored, as permitted by HTTP.
  const match = /^bytes=(\d*)-(\d*)$/.exec(range);
  const declaredSize = headers.get('Content-Length');
  if (!match || (!match[1] && !match[2]) || (declaredSize !== null
      && (!Number.isSafeInteger(Number(declaredSize)) || Number(declaredSize) <= 0
      || Number(declaredSize) >= 25 * 1024 * 1024))) {
    return new Response(response.body, {status: response.status, headers});
  }
  const data = await response.arrayBuffer();
  const length = data.byteLength;
  // ASSETS omits Content-Length inside Pages, even when the outer HTTP response
  // includes it. Published exports (and Pages assets) have a 25 MiB file limit.
  if (!length || length >= 25 * 1024 * 1024) {
    return new Response(data, {status: response.status, headers});
  }
  let start, end;
  if (!match[1]) {
    const suffix = Number(match[2]);
    start = length - Math.min(suffix, length);
    end = length - 1;
    if (!Number.isSafeInteger(suffix) || suffix <= 0) start = length;
  } else {
    start = Number(match[1]);
    end = match[2] ? Math.min(Number(match[2]), length - 1) : length - 1;
    if (match[2] && !Number.isSafeInteger(Number(match[2]))) start = length;
  }
  if (!Number.isSafeInteger(start) || start < 0 || start >= length || end < start) {
    headers.set('Content-Range', `bytes */${length}`);
    headers.set('Content-Length', '0');
    return new Response(null, {status: 416, headers});
  }
  headers.set('Content-Range', `bytes ${start}-${end}/${length}`);
  headers.set('Content-Length', String(end - start + 1));
  return new Response(data.slice(start, end + 1), {status: 206, headers});
}

// Explicit owner-selected public edition. The default build remains protected.
export default {
  async fetch(request, env) {
    const response = await audioRangeResponse(request, await env.ASSETS.fetch(request));
    const result = new Response(response.body, response);
    result.headers.set('X-Content-Type-Options', 'nosniff');
    result.headers.set('Referrer-Policy', 'no-referrer');
    result.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
    result.headers.set('Cache-Control', 'no-cache');
    result.headers.set('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
    return result;
  },
};
