import io
import json
from datetime import datetime, timezone
import pytest
from PIL import Image
import app

NOW=datetime(2026,10,26,8,tzinfo=timezone.utc)
ROW={'basetime':'20261026075000','validtime':'20261026075000','elements':['hrpns','hrpns_nd']}
def png(color=(250,245,0,255)):
    out=io.BytesIO(); Image.new('RGBA',(256,256),color).save(out,format='PNG'); return out.getvalue()
def loader(path,kind):
    return {'bytes':json.dumps([ROW]).encode() if kind=='application/json' else png(),'retrieved_at':NOW.isoformat()},False

def test_matsuyama_pixel_and_wrapping():
    assert app.point(33.84,132.77)==(889,409,168,154)
    assert app.point(33.84,492.77)==(889,409,168,154)
    for lat,lon in [(90,132),(float('nan'),132),(33.84,0),(33.84,float('inf'))]:
        with pytest.raises(app.DataError): app.point(lat,lon)
    x,y,px,py=app.point(33.65,132.55)
    assert 0<=px<256 and 0<=py<256

def test_all_bins_and_non_bins():
    for i,color in enumerate(app.PALETTE):
        c=app.category((*color,255)); assert c['lower']==app.BOUNDS[i] and c['upper']==app.BOUNDS[i+1]
    assert app.category((0,0,0,0))['status']=='transparent_unclassified'
    assert app.category((255,245,0,255))['status']=='unknown_color'
    assert app.category((250,245,0,127))['status']=='unknown_color'

@pytest.mark.parametrize('value',['20260230000000','20261026','2026102607500x',None])
def test_invalid_times(value):
    with pytest.raises(app.DataError): app.utc(value)

def test_index_future_stale_and_missing():
    for rows in [b'{}',b'bad',json.dumps([{**ROW,'basetime':'20261027000000','validtime':'20261027000000'}]).encode()]:
        with pytest.raises(app.DataError): app.entries(rows,'analysis',NOW)
    d=app.snapshot(33.84,132.77,loader=loader,now=NOW)
    assert d['category']['lower']==20 and not d['stale']
    assert app.snapshot(33.84,132.77,loader=loader,now=NOW.replace(hour=9))['stale']
    with pytest.raises(app.DataError): app.snapshot(33.84,132.77,'forecast',60,loader,NOW)

def test_bad_png():
    def bad(path,kind):
        r,c=loader(path,kind)
        if kind=='image/png':r['bytes']=b'bad'
        return r,c
    with pytest.raises(app.DataError):app.snapshot(33.84,132.77,loader=bad,now=NOW)

def test_cache_errors_and_success(monkeypatch):
    app.CACHE.clear(); calls=[]
    def fail(*args,**kwargs):calls.append(1);raise OSError('offline')
    monkeypatch.setattr(app,'urlopen',fail)
    for _ in range(2):
        with pytest.raises(app.DataError):app.fetch('/targetTimes_N1.json','application/json')
    assert len(calls)==1
    app.CACHE.clear()

def test_synthetic_palette_fixture():
    with Image.open(io.BytesIO(png())) as im:
        assert im.size==(256,256)
        assert app.category(im.getpixel((168,154)))['lower']==20

def test_forecast_uses_actual_index_entry():
    row={**ROW,'validtime':'20261026082000'}
    def forecast(path,kind):
        r,c=loader(path,kind)
        if kind=='application/json':r['bytes']=json.dumps([row]).encode()
        else:assert '/20261026075000/none/20261026082000/' in path
        return r,c
    d=app.snapshot(33.84,132.77,'forecast',30,forecast,NOW)
    assert d['validtime']==row['validtime']

@pytest.mark.parametrize('status,kind,data',[(404,'image/png',b''),(200,'text/html',b'bad'),(200,'image/png',b'x'*2_000_001)])
def test_http_validation(monkeypatch,status,kind,data):
    class Headers:
        def get_content_type(self):return kind
    class Response:
        headers=Headers()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return data[:n]
    response=Response();response.status=status
    monkeypatch.setattr(app,'urlopen',lambda *args,**kwargs:response)
    app.CACHE.clear()
    with pytest.raises(app.DataError):app.fetch('/test.png','image/png')
    app.CACHE.clear()

def test_pixel_edges_and_success_cache(monkeypatch):
    lon=890/1024*360-180
    assert app.point(33.84,lon)[0:3:2]==(890,0)
    app.CACHE.clear()
    class Headers:
        def get_content_type(self):return 'application/json'
    class Response:
        status=200;headers=Headers()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b'[]'
    calls=[]
    def get(*args,**kwargs):calls.append(1);return Response()
    monkeypatch.setattr(app,'urlopen',get)
    assert app.fetch('/index','application/json')[1] is False
    assert app.fetch('/index','application/json')[1] is True
    assert len(calls)==1
    app.CACHE.clear()
