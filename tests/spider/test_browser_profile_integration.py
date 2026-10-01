"""Real Chromium restart proves automatic cache cleanup preserves login storage."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from core.browser_manager import BrowserManager, find_browser_path

pytestmark=pytest.mark.integration

def test_real_browser_cache_cleanup_preserves_cookie_and_local_storage(tmp_path):
    browser=find_browser_path()
    if not browser:
        pytest.skip('Chromium browser is required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args): pass
        def do_GET(self):
            body=b'<html><body>owned audit fixture</body></html>'
            self.send_response(200)
            self.send_header('Content-Type','text/html')
            self.send_header('Cache-Control','public, max-age=3600')
            if self.path=='/login':
                self.send_header('Set-Cookie','audit_cookie=synthetic-login; Max-Age=3600; Path=/; SameSite=Lax')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    profile=tmp_path/'isolated-browser-profile'
    url=f'http://127.0.0.1:{server.server_port}'
    manager=BrowserManager(headless=True,user_data_dir=str(profile),browser_path=browser)
    try:
        page=manager.get_page()
        page.get(url+'/login')
        assert 'audit_cookie=synthetic-login' in page.run_js('return document.cookie;')
        page.run_js("localStorage.setItem('login-sentinel','synthetic-state');")
        manager.close()
        marker=profile/'Default'/'Cache'/'audit-old-cache'
        marker.parent.mkdir(parents=True,exist_ok=True); marker.write_bytes(b'old-cache')
        second=manager.get_page()
        assert not marker.exists()
        second.get(url+'/check')
        assert 'audit_cookie=synthetic-login' in second.run_js('return document.cookie;')
        assert second.run_js("return localStorage.getItem('login-sentinel');")=='synthetic-state'
        assert (profile/'Default'/'Network'/'Cookies').exists() or (profile/'Default'/'Cookies').exists()
        # Simulate a browser disappearing outside BrowserManager.close().
        # The cached page must be rejected and the persistent profile reused.
        second.quit()
        third = manager.get_page()
        assert third is not second
        third.get(url+'/after-disconnect')
        assert 'audit_cookie=synthetic-login' in third.run_js('return document.cookie;')
        assert third.run_js("return localStorage.getItem('login-sentinel');")=='synthetic-state'
    finally:
        manager.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)
