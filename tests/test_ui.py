import threading
import os
from http.server import ThreadingHTTPServer
import pytest
from playwright.sync_api import sync_playwright
import app
from test_app import loader,NOW

def test_mobile_success_then_failed_refresh():
    server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, executable_path=os.environ.get("TENKI_CHROMIUM"))
        page=browser.new_page(viewport={'width':390,'height':844})
        payload=app.snapshot(33.84,132.77,loader=loader,now=NOW)
        page.route('**/api/rain?*',lambda route:route.fulfill(json=payload))
        page.goto(f'http://127.0.0.1:{server.server_port}')
        assert page.get_by_label('緯度').input_value()=='33.84'
        page.get_by_role('button',name='手動で更新').click()
        page.get_by_role('heading',name='20 ≤ 雨量 < 30 mm/h').wait_for()
        assert 'JST' in page.locator('#details').inner_text()
        assert page.locator('body').evaluate('(e)=>e.scrollWidth')<=390
        assert page.get_by_role('link',name='tenki.jp 雨雲レーダー ↗').get_attribute('target')=='_blank'
        page.unroute('**/api/rain?*')
        page.route('**/api/rain?*',lambda route:route.fulfill(status=503,json={'status':'error','error':'JMA unavailable'}))
        page.get_by_role('button',name='手動で更新').click()
        page.get_by_role('status').filter(has_text='更新失敗').wait_for()
        assert page.locator('#result').is_hidden()
        browser.close()
    server.shutdown();server.server_close()
