import {createClient, snapshot, freshness} from './core.js';
const client = createClient();
const form = document.querySelector('#controls');
const status = document.querySelector('#status');
const result = document.querySelector('#result');
let current = null, imageUrl = null;
function jst(raw) {
  const iso = /^\d{14}$/.test(raw) ? `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}T${raw.slice(8,10)}:${raw.slice(10,12)}:${raw.slice(12,14)}Z` : raw;
  return new Date(iso).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'})+' JST';
}
function updateFreshness() {
  if (!current) return;
  const fresh = freshness(current);
  document.querySelector('#age').textContent = `${Math.floor(fresh.age_seconds/60)}分 / ${fresh.stale ? '古いデータ' : '鮮度範囲内'}`;
  status.textContent = fresh.stale ? '取得成功。ただし解析時刻が15分以上前です。' : '取得成功';
}
// Local freshness calculation only; this timer makes no network requests.
setInterval(updateFreshness, 30000);
form.addEventListener('submit', async event => {
  event.preventDefault();
  status.textContent = '取得中…'; result.hidden = true; current = null;
  form.querySelector('button').disabled = true;
  if (imageUrl) { URL.revokeObjectURL(imageUrl); imageUrl = null; }
  try {
    const values = new FormData(form);
    const d = await snapshot(Number(values.get('lat')),Number(values.get('lon')),values.get('mode'),Number(values.get('lead')),client);
    const c = d.category;
    document.querySelector('#bin').textContent = c.status === 'classified'
      ? (c.upper === null ? `${c.lower} mm/h 以上` : `${c.lower} ≤ 雨量 < ${c.upper} mm/h`)
      : ({transparent_unclassified:'透明・未分類（ゼロとは判定できません）',unknown_color:'未対応の色（区分不明）'}[c.status] || 'データなし');
    const dl = document.querySelector('#details'); dl.replaceChildren();
    const details = {'選択地点':`${d.location.latitude}, ${d.location.longitude}`,'解析基準時刻':jst(d.basetime),'対象時刻':jst(d.validtime),'元の UTC 時刻':`${d.basetime} / ${d.validtime}`,'取得時刻':jst(d.retrieved_at),'経過':'','タイル':`z10 / ${d.tile.x}/${d.tile.y} ・ pixel ${d.pixel.x},${d.pixel.y}`,'提供元状態':`${d.provider_status} / ${d.cached ? '5分キャッシュ' : '新規取得'}`};
    for (const [key,value] of Object.entries(details)) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = key; dd.textContent = value;
      if (key === '経過') dd.id = 'age';
      dl.append(dt,dd);
    }
    imageUrl = URL.createObjectURL(d.blob); document.querySelector('#rain').src = imageUrl;
    const marker = document.querySelector('#marker');
    marker.style.left = (d.pixel.x+.5)/256*100+'%'; marker.style.top = (d.pixel.y+.5)/256*100+'%';
    document.querySelector('#source').href = d.source_url;
    current = d; result.hidden = false; updateFreshness();
  } catch (error) {
    status.textContent = `更新失敗：${error.name}: ${error.message}。前回の表示は非表示にしました。通信失敗は5分間キャッシュされます。`;
  } finally { form.querySelector('button').disabled = false; }
});
document.querySelector('#zoom').addEventListener('input', event => {
  document.querySelector('#tile').style.width = 256*2**(Number(event.target.value)-10)+'px';
});
