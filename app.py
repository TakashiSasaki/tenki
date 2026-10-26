"""Bounded JMA display-category viewer. No arbitrary upstream URLs."""
import io
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from PIL import Image

ORIGIN = 'https://www.jma.go.jp/bosai/jmatile/data/nowc'
AREA = (33.65, 34.05, 132.55, 133.0)
PALETTE = [(242,242,255),(160,210,255),(33,140,255),(0,65,255),(250,245,0),(255,153,0),(255,40,0),(180,0,104)]
BOUNDS = [0,1,5,10,20,30,50,80,None]
CACHE = {}
LOCK = threading.RLock()

class DataError(Exception):
    pass

def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{14}', value):
        raise DataError('Invalid provider timestamp')
    try:
        return datetime.strptime(value, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DataError('Invalid provider timestamp') from exc

def point(lat, lon):
    if not math.isfinite(lat) or not math.isfinite(lon) or not -85.05112878 <= lat <= 85.05112878:
        raise DataError('Invalid Web Mercator coordinates')
    lon = (lon + 180) % 360 - 180
    if not (AREA[0] <= lat <= AREA[1] and AREA[2] <= lon <= AREA[3]):
        raise DataError('Point outside supported Matsuyama area')
    x = (lon + 180) / 360 * 1024
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 1024
    return math.floor(x), math.floor(y), math.floor((x % 1)*256), math.floor((y % 1)*256)

def category(rgba):
    if rgba[3] == 0:
        return {'status':'transparent_unclassified', 'lower':None, 'upper':None, 'unit':'mm/h'}
    rgb = tuple(rgba[:3])
    if rgba[3] != 255 or rgb not in PALETTE:
        return {'status':'unknown_color', 'rgba':list(rgba), 'lower':None, 'upper':None, 'unit':'mm/h'}
    i = PALETTE.index(rgb)
    return {'status':'classified', 'lower':BOUNDS[i], 'upper':BOUNDS[i+1], 'lower_inclusive':True, 'upper_inclusive':False, 'unit':'mm/h'}

def fetch(path, kind):
    """Cache attempts as well as successes; failed refresh never becomes success."""
    with LOCK:
        if len(CACHE) >= 128 and path not in CACHE:
            CACHE.pop(next(iter(CACHE)))
        old = CACHE.get(path)
        if old and time.monotonic()-old[0] < 300:
            if isinstance(old[1], Exception):
                raise old[1]
            return old[1], True
        try:
            with urlopen(ORIGIN + path, timeout=10) as r:
                if r.status != 200 or r.headers.get_content_type() != kind:
                    raise DataError('Unexpected upstream HTTP status/content type')
                data = r.read(2_000_001)
            if len(data)>2_000_000:
                raise DataError('Upstream size limit')
            value = {'bytes':data, 'retrieved_at':datetime.now(timezone.utc).isoformat()}
            CACHE[path] = (time.monotonic(), value)
            return value, False
        except Exception as exc:
            error = DataError('JMA retrieval failed: '+type(exc).__name__)
            CACHE[path] = (time.monotonic(), error)
            raise error from exc

def entries(data, mode, now):
    try:
        rows = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise DataError('Malformed JMA JSON') from exc
    if not isinstance(rows,list) or len(rows)>1000:
        raise DataError('Invalid JMA index')
    valid=[]
    for row in rows:
        if not isinstance(row,dict):
            raise DataError('Invalid JMA entry')
        b,v=utc(row.get('basetime')),utc(row.get('validtime'))
        if not isinstance(row.get('elements'),list):
            raise DataError('Invalid JMA elements')
        if 'hrpns' not in row['elements']:
            continue
        if b>now or v<b or (mode=='analysis' and v!=b) or (v-b).total_seconds()>3600:
            continue
        valid.append(row)
    if not valid:
        raise DataError('No valid provider times')
    newest=max(r['basetime'] for r in valid)
    return sorted([r for r in valid if r['basetime']==newest],key=lambda r:r['validtime'])

def snapshot(lat,lon,mode='analysis',lead=0, loader=fetch, now=None):
    now=now or datetime.now(timezone.utc)
    x,y,px,py=point(lat,lon)
    if mode not in ('analysis','forecast') or lead not in range(0,61,5):
        raise DataError('Invalid mode or forecast lead')
    index, cached=loader('/targetTimes_'+('N1' if mode=='analysis' else 'N2')+'.json','application/json')
    rows=entries(index['bytes'],mode,now)
    # Select only an actual returned entry matching the requested lead.
    matches=[r for r in rows if (utc(r['validtime'])-utc(r['basetime'])).total_seconds()==(lead*60 if mode=='forecast' else 0)]
    if not matches:
        raise DataError('Requested forecast time missing from provider index')
    row=matches[-1]
    path=f"/{row['basetime']}/none/{row['validtime']}/surf/hrpns/10/{x}/{y}.png"
    tile, tile_cached=loader(path,'image/png')
    data=tile['bytes']
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise DataError('Invalid PNG signature')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format!='PNG' or im.size!=(256,256):
                raise DataError('Invalid tile dimensions')
            rgba=im.convert('RGBA')
            result=category(rgba.getpixel((px,py)))
            out=io.BytesIO(); rgba.save(out,format='PNG')
    except (OSError, ValueError) as exc:
        raise DataError('Unreadable PNG') from exc
    age=(now-utc(row['basetime'])).total_seconds()
    import base64
    return {'status':'ok','provider_status':'ok','location':{'latitude':lat,'longitude':(lon+180)%360-180},'mode':mode,'basetime':row['basetime'],'validtime':row['validtime'],'observed_at':utc(row['basetime']).isoformat(),'age_seconds':age,'stale':age>900,'retrieved_at':tile['retrieved_at'],'index_retrieved_at':index['retrieved_at'],'cached':cached or tile_cached,'pixel':{'x':px,'y':py},'tile':{'z':10,'x':x,'y':y},'category':result,'source_url':ORIGIN+path,'image':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlsplit,parse_qs
        u=urlsplit(self.path)
        if u.path=='/api/rain':
            try:
                q=parse_qs(u.query,strict_parsing=True)
                if set(q)-{'lat','lon','mode','lead'} or any(len(v)!=1 for v in q.values()):
                    raise DataError('Invalid query')
                result=snapshot(float(q.get('lat',['33.84'])[0]),float(q.get('lon',['132.77'])[0]),q.get('mode',['analysis'])[0],int(q.get('lead',['0'])[0]))
                self.send_json(200,result)
            except (DataError,ValueError) as exc:
                self.send_json(503,{'status':'error','provider_status':'unavailable','error':str(exc),'checked_at':datetime.now(timezone.utc).isoformat()})
            return
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        if u.path not in files:
            self.send_error(404); return
        name,kind=files[u.path]
        self.respond(200,(Path(__file__).parent/'static'/name).read_bytes(),kind)
    def respond(self,status,data,kind):
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(data)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"}.items():
            self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def send_json(self,status,result):
        self.respond(status,json.dumps(result,ensure_ascii=False).encode(),'application/json; charset=utf-8')
    def log_message(self,*args):
        pass

if __name__=='__main__':
    print('tenki: http://127.0.0.1:8000',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8000),Handler).serve_forever()
