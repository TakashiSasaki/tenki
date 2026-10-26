import test from 'node:test';
import assert from 'node:assert/strict';
import {point,utc,category,PALETTE,BOUNDS,selectEntry,freshness,createClient,snapshot,decodePng,ORIGIN} from '../static/core.js';
const NOW = Date.parse('2026-10-26T08:00:00Z');
const ROW = {basetime:'20261026075000',validtime:'20261026075000',elements:['hrpns','hrpns_nd']};
const response = (body='[]',type='application/json',status=200) => new Response(body,{status,headers:{'content-type':type}});
test('Matsuyama tile/pixel, longitude wrapping and boundaries', () => {
  assert.deepEqual(Object.values(point(33.84,132.77)).slice(2),[889,409,168,154]);
  assert.deepEqual(Object.values(point(33.84,492.77)).slice(2),Object.values(point(33.84,132.77)).slice(2));
  assert.ok(Math.abs(point(33.84,492.77).lon-132.77)<1e-10);
  const edge = point(33.84,890/1024*360-180);
  assert.equal(edge.x,890); assert.equal(edge.px,0);
  for (const lat of [33.65,34.05]) for (const lon of [132.55,133]) {
    const p=point(lat,lon); assert.ok(p.px>=0 && p.px<256 && p.py>=0 && p.py<256);
  }
  for (const [lat,lon] of [[90,132],[NaN,132],[33.84,0],[33.84,Infinity]]) assert.throws(()=>point(lat,lon));
});
test('all palette bounds and transparent/unknown/partial alpha states',()=>{
  PALETTE.forEach((rgb,i)=>{
    const c=category([...rgb,255]); assert.equal(c.lower,BOUNDS[i]); assert.equal(c.upper,BOUNDS[i+1]);
    assert.equal(c.lower_inclusive,true); assert.equal(c.upper_inclusive,false);
  });
  assert.equal(category([0,0,0,0]).status,'transparent_unclassified');
  assert.equal(category([255,245,0,255]).status,'unknown_color');
  assert.equal(category([250,245,0,127]).status,'unknown_color');
});
test('strict UTC timestamps including calendar validation',()=>{
  assert.equal(utc('20261026080000'),NOW);
  for (const raw of ['20260230000000','20261026','2026102607500x',null,'20261301000000']) assert.throws(()=>utc(raw));
});
test('indexes select actual latest entries; reject malformed/future/missing entries',()=>{
  assert.equal(selectEntry([ROW],'analysis',0,NOW),ROW);
  const forecast={...ROW,validtime:'20261026082000'};
  assert.equal(selectEntry([forecast],'forecast',30,NOW),forecast);
  for (const rows of [{},[null],[{...ROW,elements:4}],[{...ROW,basetime:'20261027000000',validtime:'20261027000000'}],[{...ROW,validtime:'20261026070000'}]]) assert.throws(()=>selectEntry(rows,'analysis',0,NOW));
  assert.throws(()=>selectEntry([forecast],'forecast',60,NOW));
  assert.throws(()=>selectEntry([ROW,{...ROW,basetime:'20261026075500',validtime:'20261026080000'}],'forecast',0,NOW));
  assert.equal(freshness(ROW,NOW).stale,false);
  assert.equal(freshness(ROW,NOW+3600000).stale,true);
});
test('anonymous simple CORS GET, cached success and 5-minute expiry',async()=>{
  let now=NOW,calls=0;
  const client=createClient({clock:()=>now,fetcher:async(url,options)=>{
    calls++; assert.equal(url,ORIGIN+'/targetTimes_N1.json');
    assert.equal(options.mode,'cors');assert.equal(options.credentials,'omit');
    assert.equal(options.headers,undefined); assert.equal(options.redirect,'error');
    return response();
  }});
  assert.equal((await client.read('/targetTimes_N1.json','application/json')).cached,false);
  assert.equal((await client.read('/targetTimes_N1.json','application/json')).cached,true);
  assert.equal(calls,1); now+=300001;
  assert.equal((await client.read('/targetTimes_N1.json','application/json')).cached,false); assert.equal(calls,2);
});
test('failed refresh replaces previous success; failures cached without silent fallback',async()=>{
  let now=NOW,calls=0;
  const client=createClient({clock:()=>now,fetcher:async()=>{if (++calls>1) throw TypeError('CORS rejected');return response();}});
  await client.read('/index','application/json'); now+=300001;
  await assert.rejects(client.read('/index','application/json'),/CORS/);
  await assert.rejects(client.read('/index','application/json'),/CORS/);assert.equal(calls,2);
});
test('HTTP errors, content type, response size and timeout',async()=>{
  for (const fetcher of [async()=>response('', 'application/json',404),async()=>response('bad','text/html'),async()=>response('x'.repeat(2000001)),async()=>new Response('bad',{headers:{'content-type':'application/json','content-length':'2000001'}})]) {
    await assert.rejects(createClient({fetcher}).read('/index','application/json'));
  }
  const fetcher=(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('timeout','AbortError'))));
  await assert.rejects(createClient({fetcher,timeout:5}).read('/index','application/json'),/AbortError/);
});
test('request concurrency is one and cache remains bounded',async()=>{
  let active=0,max=0;
  const client=createClient({fetcher:async()=>{active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,1));active--;return response();}});
  await Promise.all(Array.from({length:40},(_,i)=>client.read('/'+i,'application/json')));
  assert.equal(max,1);
});
test('snapshot uses selected index URL and does not fabricate forecast timestamps',async()=>{
  const forecast={...ROW,validtime:'20261026082000'};
  const paths=[];
  const client={read:async(path,type)=>{paths.push(path);return {bytes:new TextEncoder().encode(JSON.stringify([forecast])),retrieved_at:new Date(NOW).toISOString(),cached:false};}};
  const pixels=new Uint8ClampedArray(256*256*4); pixels.set([250,245,0,255],(154*256+168)*4);
  const d=await snapshot(33.84,132.77,'forecast',30,client,{now:NOW,decode:async()=>({pixels,blob:{}})});
  assert.equal(d.category.lower,20);assert.equal(d.validtime,forecast.validtime);
  assert.equal(paths[1],'/20261026075000/none/20261026082000/surf/hrpns/10/889/409.png');
  await assert.rejects(snapshot(33.84,132.77,'invalid',30,client));
  await assert.rejects(snapshot(33.84,132.77,'forecast',60,client,{now:NOW}));
});
test('malformed JSON, PNG signature and dimensions fail explicitly',async()=>{
  await assert.rejects(snapshot(33.84,132.77,'analysis',0,{read:async()=>({bytes:new TextEncoder().encode('bad')})}));
  await assert.rejects(decodePng(new Uint8Array([1,2,3])),/signature/);
  const header=new Uint8Array(24);header.set([137,80,78,71,13,10,26,10]);
  await assert.rejects(decodePng(header),/dimensions/);
});
