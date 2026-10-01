"""Cancellation must retain an atomic partial result, not only a status string."""
import json
import subprocess
import sys
import threading
from pathlib import Path
from jingxu.infrastructure import spider as service
from jingxu.infrastructure.spider import SpiderAccount,SpiderConfig,SpiderEnvironment,SpiderRunner

def test_cancel_recovers_checkpoint_from_real_child(tmp_path,monkeypatch):
    child=tmp_path/'cli.py'
    child.write_text('''import argparse,json,time
p=argparse.ArgumentParser();p.add_argument('--json-out');p.add_argument('--cancel-file');a,_=p.parse_known_args()
data={'retained_products':[{'商品名称':'演示商品','示例视频链接':'https://www.douyin.com/video/test-1'}],
      'all_items':[{'商品原始名称':'演示商品','视频链接':'https://www.douyin.com/video/test-1'}],
      'crawl_complete':False}
with open(a.json_out,'w',encoding='utf-8') as f:json.dump(data,f)
print('checkpoint-ready',flush=True)
time.sleep(30)
''',encoding='utf-8')
    monkeypatch.setattr(service,'check_environment',lambda:SpiderEnvironment(True,'ready',tmp_path,sys.executable))
    monkeypatch.setattr(service,'profile_directory',lambda:tmp_path/'profile')
    monkeypatch.setattr(service,'exports_directory',lambda:tmp_path/'exports')
    monkeypatch.setattr(service,'probe_holder_pids',lambda *_args,**_kwargs:())
    monkeypatch.setattr(service,'_terminate_profile_holders',lambda *_args,**_kwargs:())
    cancel=threading.Event()
    result=SpiderRunner(timeout=15).run(SpiderConfig(accounts=(SpiderAccount('douyin','test'),)),
        cancel_event=cancel,on_log=lambda line:cancel.set() if line=='checkpoint-ready' else None)
    assert not result.success and not result.crawl_complete
    assert '取消' in result.message and len(result.items)==len(result.retained)==1
    assert Path(result.json_path).is_file()
    assert json.loads(Path(result.json_path).read_text(encoding='utf-8'))['all_items']
