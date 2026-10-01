import hashlib
import json
from types import SimpleNamespace
from core.cookie_import import normalize_cookies, import_cookie_file

def cookie(**kwargs):
    return {'name':'sessionid','value':'synthetic-secret','domain':'.douyin.com','path':'/',
            'secure':True,'httpOnly':True,'expirationDate':2000000000,**kwargs}

def test_normalizer_rejects_other_destinations_and_expired_credentials():
    entries=[cookie(),cookie(domain='.douyin.com.evil.test'),cookie(expirationDate=1),
             cookie(name='unsafe\r\nname'),cookie(value='unsafe\nvalue'),cookie(expirationDate=float('nan'))]
    result=normalize_cookies(entries,now=1900000000)
    assert len(result)==1 and result[0]['value']=='synthetic-secret'
    assert result[0]['httpOnly'] is True and result[0]['secure'] is True

def test_browser_cookie_editor_fields_are_supported():
    result=normalize_cookies([cookie(hostOnly=True,domain='www.douyin.com',sameSite='no_restriction',storeId=None)],now=1)
    assert result[0]['url']=='https://www.douyin.com/'
    assert result[0]['sameSite']=='None'
    assert 'storeId' not in result[0]

def test_unchanged_import_does_not_overwrite_newer_browser_login(tmp_path):
    profile=tmp_path/'browser-profile'; profile.mkdir()
    source=tmp_path/'cookies-import.json'; source.write_text(json.dumps([cookie()]),encoding='utf-8')
    calls=[]; page=SimpleNamespace(run_cdp=lambda name,**params:calls.append((name,params)))
    assert import_cookie_file(page,profile,source)==1
    assert import_cookie_file(page,profile,source)==0
    marker=json.loads((profile/'.jingxu-cookie-import.json').read_text(encoding='utf-8'))
    assert marker['sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert 'synthetic-secret' not in str(marker)
    assert len(calls)==1
    source.write_text(json.dumps([cookie(value='updated-synthetic-secret')]),encoding='utf-8')
    assert import_cookie_file(page,profile,source)==1 and len(calls)==2
