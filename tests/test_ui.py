"""Static artifact tests: mock JMA only; never contact live providers."""
import io
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
JMA='https://www.jma.go.jp/bosai/jmatile/data/nowc/'

class QuietStatic(SimpleHTTPRequestHandler):
    def log_message(self,*args):
        pass

@pytest.fixture
def static_site(tmp_path):
    # Serve the built artifact under /tenki/ to verify GitHub project subpaths.
    import shutil
    shutil.copytree(ROOT/'dist',tmp_path/'tenki')
    for item in (ROOT/'dist').iterdir():
        if item.is_dir(): shutil.copytree(item,tmp_path/item.name)
        else: shutil.copy2(item,tmp_path/item.name)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietStatic,directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}/tenki/'
    server.shutdown(); server.server_close()

@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TENKI_CHROMIUM'))
        yield browser
        browser.close()

def mock_jma(page,color=(250,245,0,255),stale=False):
    dt=datetime.now(timezone.utc)-timedelta(minutes=30 if stale else 5)
    raw=dt.strftime('%Y%m%d%H%M%S')
    row={'basetime':raw,'validtime':raw,'elements':['hrpns']}
    out=io.BytesIO();Image.new('RGBA',(256,256),color).save(out,format='PNG')
    requests=[]
    def route(r):
        requests.append(r.request)
        if r.request.url.endswith('.json'):
            r.fulfill(body=json.dumps([row]),content_type='application/json',headers={'Access-Control-Allow-Origin':'*'})
        else:
            r.fulfill(body=out.getvalue(),content_type='image/png',headers={'Access-Control-Allow-Origin':'*'})
    page.route(JMA+'**',route)
    return requests

@pytest.mark.parametrize('root_path',[False,True])
def test_mobile_static_success_cache_and_failed_refresh(browser,static_site,root_path):
    page=browser.new_page(viewport={'width':390,'height':844})
    requests=mock_jma(page)
    all_urls=[]
    page.on('request',lambda request:all_urls.append(request.url))
    page.clock.install()
    page.goto(static_site.removesuffix('tenki/') if root_path else static_site)
    assert page.get_by_label('緯度').input_value()=='33.84'
    page.get_by_role('button',name='手動で更新').click()
    page.get_by_role('heading',name='20 ≤ 雨量 < 30 mm/h').wait_for()
    assert 'JST' in page.locator('#details').inner_text()
    assert '新規取得' in page.locator('#details').inner_text()
    assert page.locator('body').evaluate('(e)=>e.scrollWidth')<=390
    assert page.get_by_role('link',name='tenki.jp 雨雲レーダー ↗').get_attribute('target')=='_blank'
    assert len(requests)==2
    assert not any('/api/' in url for url in all_urls)
    assert all(not r.headers.get('authorization') and not r.headers.get('cookie') for r in requests)
    page.get_by_role('button',name='手動で更新').click()
    page.get_by_role('status').filter(has_text='取得成功').wait_for()
    assert '5分キャッシュ' in page.locator('#details').inner_text()
    assert len(requests)==2
    # Expire cache in this same page; mock the next cross-origin fetch as failed.
    page.clock.fast_forward(301000)
    page.unroute(JMA+'**'); page.route(JMA+'**',lambda r:r.abort('accessdenied'))
    page.get_by_role('button',name='手動で更新').click()
    page.get_by_role('status').filter(has_text='更新失敗').wait_for()
    assert page.locator('#result').is_hidden()
    assert 'CORS' in page.get_by_role('status').inner_text()
    page.close()

@pytest.mark.parametrize('kind',['cors','canvas'])
def test_cors_and_tainted_canvas_fail_truthfully(browser,static_site,kind):
    page=browser.new_page()
    mock_jma(page)
    if kind=='cors':
        page.unroute(JMA+'**');page.route(JMA+'**',lambda r:r.abort('accessdenied'))
    else:
        page.add_init_script("CanvasRenderingContext2D.prototype.getImageData = function(){throw new DOMException('Canvas is tainted','SecurityError')}")
    page.goto(static_site)
    page.get_by_role('button',name='手動で更新').click()
    page.get_by_role('status').filter(has_text='更新失敗').wait_for()
    assert page.locator('#result').is_hidden()
    if kind=='canvas':assert 'SecurityError' in page.get_by_role('status').inner_text()
    page.close()

@pytest.mark.parametrize('color,label',[( (0,0,0,0),'透明・未分類'),((255,245,0,255),'未対応の色')])
def test_static_nonzero_states_and_staleness(browser,static_site,color,label):
    page=browser.new_page();mock_jma(page,color,stale=True)
    page.goto(static_site);page.get_by_role('button',name='手動で更新').click()
    page.get_by_role('heading').filter(has_text=label).wait_for()
    assert '古いデータ' in page.locator('#details').inner_text()
    page.close()


def test_pwa_assets_and_cache_free_worker(browser,static_site):
    page=browser.new_page()
    page.goto(static_site)
    assert page.locator('link[rel="manifest"]').get_attribute('href') == './manifest.webmanifest'
    result=page.evaluate("""async () => {
      const reg=await navigator.serviceWorker.ready;
      const manifest=await (await fetch('./manifest.webmanifest')).json();
      const icons=await Promise.all(manifest.icons.map(i=>fetch(i.src).then(r=>r.ok)));
      return {scope:reg.scope,icons,manifest,cacheKeys:await caches.keys()};
    }""")
    assert result['scope'].endswith('/tenki/')
    assert all(result['icons'])
    assert result['manifest']['display']=='standalone'
    assert result['cacheKeys']==[]
    assert page.request.get(static_site+'icons/social.png').ok
    page.close()

def test_pwa_icon_dimensions_and_manifest_references():
    manifest=json.loads((ROOT/'dist/manifest.webmanifest').read_text())
    expected={'icon-192.png':(192,192),'icon-512.png':(512,512),'icon-180.png':(180,180),'icon-32.png':(32,32),'social.png':(1200,630)}
    for name,dimensions in expected.items():
        with Image.open(ROOT/'dist/icons'/name) as img:
            assert img.size==dimensions and img.format=='PNG'
    for icon in manifest['icons']:
        assert (ROOT/'dist'/icon['src']).is_file()
        assert icon['purpose']=='any maskable'
