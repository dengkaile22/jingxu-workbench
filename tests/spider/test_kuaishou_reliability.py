"""Completeness, account scope, metadata enrichment and cancellation regressions."""
import json
from types import SimpleNamespace
import pytest
from core.kuaishou_crawler import KuaishouCrawler, resolve_kuaishou_url_or_userid
from core.models import AccountTarget, TimeFilterConfig

USER='target-user'
def photo(identity='video-1', *, owner=USER, timestamp=1710000000, goods=True):
    data={'id':identity,'timestamp':timestamp,'author':{'id':owner},'caption':'演示作品'}
    if goods: data['goodsInfo']={'productId':'p1','title':'天然茶籽洗衣液','price':'39.90'}
    return data
def payload(photos=(), *, more=False, cursor='nomore', result=1):
    return {'data':{'visionProfilePhotoList':{'result':result,'feeds':[{'photo':p} for p in photos],
                                             'hasMore':more,'pcursor':cursor}}}
class Page:
    def __init__(self, api=(), packets=(), ssr=(), url=None):
        self.api=list(api); self.packets=list(packets); self.ssr=list(ssr)
        self.url=url or f'https://www.kuaishou.com/profile/{USER}'
        self.listen=SimpleNamespace(start=lambda _targets:None,wait=self.wait)
        self.api_calls=0
    def get(self,*_args,**_kwargs): pass
    def ele(self,*_args,**_kwargs): return None
    def eles(self,*_args,**_kwargs): return []
    def wait(self,**_kwargs): return self.packets.pop(0) if self.packets else None
    def run_js(self,script,**_kwargs):
        if "window.fetch" in script:
            self.api_calls+=1
            value=self.api.pop(0) if self.api else None
            return {'ok':True,'data':value} if value is not None else None
        if '__APOLLO_STATE__' in script:
            return json.dumps({'defaultClient':{f'Photo:{p["id"]}':p for p in self.ssr}})
        return ''
def crawl(page, *, max_scrolls=3, filters=None, stop=None):
    crawler=KuaishouCrawler(SimpleNamespace(get_page=lambda:page),stop_check=stop)
    target=AccountTarget('kuaishou',USER)
    items=crawler.crawl_account(target,filters or TimeFilterConfig(mode='all'),max_scrolls=max_scrolls)
    return crawler,target,items
@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr('core.kuaishou_crawler.time.sleep',lambda _duration:None)
    monkeypatch.setattr('requests.get',lambda *_args,**_kwargs:pytest.fail('no real network in this test'))

def test_twenty_items_and_failure_never_imply_completion():
    crawler,target,items=crawl(Page(api=[payload([photo(str(i)) for i in range(20)],more=True,cursor='next')]))
    assert target.status=='部分完成'
    assert target.scraped_videos==target.found_products==len(items)==20
    assert crawler.response_issues
@pytest.mark.parametrize('body',[None,{},payload(result=8)])
def test_empty_or_failed_data_is_not_reported_complete(body):
    _,target,items=crawl(Page(api=[body]),max_scrolls=1)
    assert target.status=='部分完成' and items==[]
def test_confirmed_empty_account_is_complete():
    _,target,items=crawl(Page(api=[payload()]))
    assert target.status=='已完成' and items==[]
def test_limit_preserves_partial_items():
    _,target,items=crawl(Page(api=[payload([photo()],more=True,cursor='next')]),max_scrolls=1)
    assert target.status=='部分完成' and len(items)==1
def test_ssr_summary_can_be_enriched_by_full_api_response():
    crawler,target,items=crawl(Page(ssr=[photo(goods=False)],api=[payload([photo()])]))
    assert target.status=='已完成' and len(items)==1
    assert len(crawler.diagnostics)==1 and crawler.diagnostics[0].extracted==1
def test_unknown_date_summary_can_be_enriched_later():
    _,target,items=crawl(Page(ssr=[photo(timestamp=0)],api=[payload([photo()])]),
                         filters=TimeFilterConfig(mode='range',start_date='2024-01-01',end_date='2024-12-31'))
    assert target.status=='已完成' and len(items)==1
def test_unknown_date_never_bypasses_date_filter():
    _,target,items=crawl(Page(api=[payload([photo(timestamp=0)])]),filters=TimeFilterConfig(mode='days'))
    assert target.status.startswith('部分完成') and items==[]
def test_wrong_author_is_rejected_and_not_marked_complete():
    _,target,items=crawl(Page(api=[payload([photo(owner='someone-else')])]))
    assert target.status.startswith('部分完成') and items==[]
def test_redirect_to_other_profile_cannot_crawl():
    page=Page(api=[payload([photo()])],url='https://www.kuaishou.com/profile/other-user')
    _,target,items=crawl(page)
    assert target.status=='主页身份未确认' and items==[] and page.api_calls==0
def test_unscoped_ssr_photos_are_not_trusted():
    _,target,items=crawl(Page(ssr=[photo(owner='')],api=[payload()]))
    assert target.scraped_videos==0 and items==[]
def test_pinned_old_videos_do_not_stop_current_video_scan():
    photos=[dict(photo(str(i),timestamp=1600000000),isTop=True) for i in range(4)] + [photo('new')]
    _,target,items=crawl(Page(api=[payload(photos)]),filters=TimeFilterConfig(mode='range',start_date='2024-01-01'))
    assert target.status=='已完成' and [p.video_id for p in items]==['new']
def test_cancel_from_fallback_updates_statistics():
    stopped=[False]
    page=Page(ssr=[photo()])
    def stop_during_wait(**_kwargs): stopped[0]=True; return None
    page.listen.wait=stop_during_wait
    _,target,items=crawl(page,stop=lambda:stopped[0],max_scrolls=2)
    assert target.status=='已停止' and target.scraped_videos==target.found_products==len(items)==1
@pytest.mark.parametrize('raw',['https://evil.test/profile/target-user','https://www.kuaishou.com.evil.test/profile/target-user',
                              'https://www.kuaishou.com/short-video/not-a-user','a nickname with spaces',
                              'https://www.kuaishou.com/profile/a?userId=b'])
def test_rejects_ambiguous_or_wrong_account_input(raw):
    assert resolve_kuaishou_url_or_userid(raw)==''

def test_current_rest_profile_feed_is_parsed():
    record={'photoId':'modern-1','caption':'好物','timestamp':1710000000000,
            'goodsInfo':{'goodsId':'goods-1','title':'天然茶籽洗衣液'}}
    body={'result':1,'feeds':[{'photo':record,'user':{'id':USER}}],'pcursor':'no_more'}
    packet=SimpleNamespace(response=SimpleNamespace(body=body))
    _,target,items=crawl(Page(packets=[packet]))
    assert target.status=='已完成' and items[0].video_id=='modern-1'
    assert items[0].publish_time==1710000000

def test_current_rest_login_response_stops_immediately():
    packet=SimpleNamespace(response=SimpleNamespace(body={'result':109,'loginUrl':'https://www.kuaishou.com/'}))
    crawler,target,items=crawl(Page(packets=[packet]),max_scrolls=25)
    assert target.status=='需要登录或验证' and items==[]
    assert crawler.response_issues[0]['code']=='kuaishou_login_required'

def test_modern_client_does_not_issue_obsolete_graphql_queries():
    packet=SimpleNamespace(response=SimpleNamespace(body={'result':1,'feeds':[],'pcursor':'no_more'}))
    page=Page(packets=[packet]); previous=page.run_js
    page.run_js=lambda script,**kwargs:True if '/ks-web/' in script else previous(script,**kwargs)
    _,target,_=crawl(page)
    assert target.status=='已完成' and page.api_calls==0
