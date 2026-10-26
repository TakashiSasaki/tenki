export const ORIGIN = 'https://www.jma.go.jp/bosai/jmatile/data/nowc';
export const PALETTE = [[242,242,255],[160,210,255],[33,140,255],[0,65,255],[250,245,0],[255,153,0],[255,40,0],[180,0,104]];
export const BOUNDS = [0,1,5,10,20,30,50,80,null];
export function utc(raw) {
  if (typeof raw !== 'string' || !/^\d{14}$/.test(raw)) throw Error('Invalid provider timestamp');
  const iso = `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}T${raw.slice(8,10)}:${raw.slice(10,12)}:${raw.slice(12,14)}Z`;
  const time = Date.parse(iso);
  if (!Number.isFinite(time) || new Date(time).toISOString().slice(0,19) !== iso.slice(0,19)) throw Error('Invalid provider timestamp');
  return time;
}
export function point(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 85.05112878) throw Error('Invalid Web Mercator coordinates');
  if (lon < -180 || lon >= 180) lon = ((lon + 180) % 360 + 360) % 360 - 180;
  if (lat < 33.65 || lat > 34.05 || lon < 132.55 || lon > 133) throw Error('Point outside supported Matsuyama area');
  const x = (lon + 180) / 360 * 1024;
  const y = (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * 1024;
  return {lat, lon, x:Math.floor(x), y:Math.floor(y), px:Math.floor((x % 1)*256), py:Math.floor((y % 1)*256)};
}
export function category(rgba) {
  const result = {lower:null, upper:null, unit:'mm/h'};
  if (rgba[3] === 0) return {...result, status:'transparent_unclassified'};
  const i = PALETTE.findIndex(rgb => rgb.every((c,j) => c === rgba[j]));
  if (i < 0 || rgba[3] !== 255) return {...result, status:'unknown_color', rgba:Array.from(rgba)};
  return {status:'classified', lower:BOUNDS[i], upper:BOUNDS[i+1], lower_inclusive:true, upper_inclusive:false, unit:'mm/h'};
}
export function selectEntry(rows, mode, lead, now = Date.now()) {
  if (!['analysis','forecast'].includes(mode) || !Number.isInteger(lead) || lead < 0 || lead > 60 || lead % 5) throw Error('Invalid mode/lead');
  if (!Array.isArray(rows) || rows.length > 1000) throw Error('Invalid JMA index');
  const valid = rows.filter(row => {
    if (!row || typeof row !== 'object' || !Array.isArray(row.elements)) throw Error('Invalid JMA entry');
    const b = utc(row.basetime), v = utc(row.validtime);
    return row.elements.includes('hrpns') && b <= now && v >= b && v-b <= 3600000 && (mode !== 'analysis' || v === b);
  });
  if (!valid.length) throw Error('No valid provider times');
  const newest = valid.reduce((a,r) => r.basetime > a ? r.basetime : a, '');
  const selected = valid.find(r => r.basetime === newest && utc(r.validtime)-utc(r.basetime) === (mode === 'analysis' ? 0 : lead*60000));
  if (!selected) throw Error('Requested forecast time missing from provider index');
  return selected;
}
export function freshness(row, now = Date.now()) {
  const age_seconds = (now - utc(row.basetime))/1000;
  return {age_seconds, stale:age_seconds > 900};
}

// One shared request slot, bounded memory, no automatic retries. Cache failures too.
export function createClient({fetcher = globalThis.fetch, clock = Date.now, timeout = 10000, ttl = 300000} = {}) {
  const cache = new Map();
  let tail = Promise.resolve();
  function read(path, type) {
    const run = async () => {
      const old = cache.get(path);
      if (old && clock()-old.at < ttl) {
        if (old.error) throw old.error;
        return {...old.value, cached:true};
      }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const response = await fetcher(ORIGIN+path, {mode:'cors', credentials:'omit', redirect:'error', signal:controller.signal});
        if (!response.ok || response.type === 'opaque' || response.headers.get('content-type')?.split(';')[0].trim() !== type) throw Error('Unexpected JMA HTTP status/content type');
        const declared = Number(response.headers.get('content-length'));
        if (declared > 2000000) throw Error('Upstream size limit');
        const reader = response.body.getReader();
        const chunks = []; let size = 0;
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 2000000) { await reader.cancel(); throw Error('Upstream size limit'); }
          chunks.push(value);
        }
        const bytes = new Uint8Array(size); let offset = 0;
        for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
        const value = {bytes, retrieved_at:new Date(clock()).toISOString(), cached:false};
        cache.set(path, {at:clock(), value});
        return value;
      } catch (cause) {
        const error = Error(`JMA retrieval failed (${cause.name}): ${cause.message}. CORS/network access may be unavailable.`);
        cache.set(path, {at:clock(), error});
        throw error;
      } finally {
        clearTimeout(timer);
        if (cache.size > 32) cache.delete(cache.keys().next().value);
      }
    };
    const pending = tail.then(run);
    tail = pending.catch(() => {});
    return pending;
  }
  return {read};
}
export async function decodePng(bytes) {
  if (![137,80,78,71,13,10,26,10].every((v,i) => bytes[i] === v)) throw Error('Invalid PNG signature');
  if (bytes.length < 24) throw Error('Truncated PNG');
  const header = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (header.getUint32(16) !== 256 || header.getUint32(20) !== 256) throw Error('Invalid tile dimensions');
  const blob = new Blob([bytes], {type:'image/png'});
  const bitmap = await createImageBitmap(blob);
  try {
    if (bitmap.width !== 256 || bitmap.height !== 256) throw Error('Invalid tile dimensions');
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d', {willReadFrequently:true});
    context.drawImage(bitmap,0,0);
    // SecurityError must propagate: a blocked canvas never becomes zero rainfall.
    const pixels = context.getImageData(0,0,256,256).data;
    return {pixels, blob};
  } finally { bitmap.close(); }
}
export async function snapshot(lat, lon, mode, lead, client, {now = Date.now(), decode = decodePng} = {}) {
  if (!['analysis','forecast'].includes(mode) || !Number.isInteger(lead) || lead < 0 || lead > 60 || lead % 5) throw Error('Invalid mode/lead');
  const p = point(lat,lon);
  const index = await client.read(`/targetTimes_${mode === 'analysis' ? 'N1' : 'N2'}.json`, 'application/json');
  let rows;
  try { rows = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(index.bytes)); }
  catch { throw Error('Malformed JMA JSON'); }
  const row = selectEntry(rows,mode,lead,now);
  const path = `/${row.basetime}/none/${row.validtime}/surf/hrpns/10/${p.x}/${p.y}.png`;
  const tile = await client.read(path,'image/png');
  const {pixels,blob} = await decode(tile.bytes);
  const offset = (p.py*256+p.px)*4;
  return {status:'ok', provider_status:'ok', location:{latitude:p.lat,longitude:p.lon}, mode, ...row, ...freshness(row,now), retrieved_at:tile.retrieved_at, index_retrieved_at:index.retrieved_at, cached:index.cached || tile.cached, pixel:{x:p.px,y:p.py}, tile:{z:10,x:p.x,y:p.y}, category:category(pixels.slice(offset,offset+4)), source_url:ORIGIN+path, blob};
}
