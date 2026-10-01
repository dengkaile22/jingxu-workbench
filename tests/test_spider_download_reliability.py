import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from jingxu.infrastructure.downloader import DownloadQueue, DownloadState, download_direct
from jingxu.infrastructure.downloader import download_with_yt_dlp

def test_parallel_same_name_direct_transfers_preserve_all_files(tmp_path,monkeypatch):
    barrier=threading.Barrier(4)
    data=b'synthetic-media'
    class Response(io.BytesIO):
        headers={'Content-Length':str(len(data))}
        def __enter__(self): barrier.wait(timeout=5); return self
        def __exit__(self,*_args): self.close()
    monkeypatch.setattr('urllib.request.urlopen',lambda *_args,**_kwargs:Response(data))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(download_direct,'https://example.test/video.mp4',tmp_path,
                             lambda *_args:None,threading.Event(),'same-name') for _ in range(4)]
        paths=[f.result(timeout=10) for f in futures]
    assert len(set(paths))==4
    assert all(p.read_bytes()==data for p in paths)
    assert not list(tmp_path.glob('*.part')) and not list(tmp_path.glob('.*.part'))

def test_lowering_concurrency_limits_next_jobs_without_cancelling_active(tmp_path):
    release=threading.Event(); active=0; peak=0; lock=threading.Lock(); stage_two=False
    def download(url,directory,on_progress,cancel_event,filename=''):
        nonlocal active,peak
        with lock:
            active+=1
            if stage_two: peak=max(peak,active)
        if not stage_two: release.wait(timeout=5)
        else: time.sleep(.02)
        path=Path(directory)/(url+'.mp4'); path.write_bytes(b'media')
        with lock: active-=1
        return path
    queue=DownloadQueue(tmp_path,downloader=download,concurrency=4)
    try:
        queue.enqueue([str(i) for i in range(4)])
        deadline=time.monotonic()+3
        while active<4 and time.monotonic()<deadline: time.sleep(.01)
        assert active==4
        queue.set_concurrency(1)
        release.set()
        while queue.active_count and time.monotonic()<deadline: time.sleep(.01)
        assert queue.active_count==0
        stage_two=True
        queue.enqueue([str(i) for i in range(4,12)])
        deadline=time.monotonic()+3
        while queue.active_count and time.monotonic()<deadline: time.sleep(.01)
        assert peak==1 and all(job.state==DownloadState.COMPLETED for job in queue.jobs)
    finally:
        release.set(); queue.stop()


def test_parallel_ytdlp_transfers_use_private_staging_and_preserve_outputs(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    barrier=threading.Barrier(4); stages=[]
    class YoutubeDL:
        def __init__(self,options): self.directory=Path(options['outtmpl']).parent; stages.append(self.directory)
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def extract_info(self,url,download=True):
            path=self.directory/'same.mp4'; path.write_bytes(url.encode())
            barrier.wait(timeout=5)
            return {'title':'same','requested_downloads':[{'filepath':str(path)}]}
    monkeypatch.setitem(sys.modules,'yt_dlp',SimpleNamespace(YoutubeDL=YoutubeDL))
    previous=tmp_path/'same.mp4'; previous.write_bytes(b'keep previous download')
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(download_with_yt_dlp,f'https://example.test/{i}',tmp_path,
                             lambda *_args:None,threading.Event(),'same') for i in range(4)]
        paths=[f.result(timeout=10) for f in futures]
    assert len(set(paths))==len(set(stages))==4
    assert {p.read_bytes() for p in paths}=={f'https://example.test/{i}'.encode() for i in range(4)}
    assert previous.read_bytes()==b'keep previous download'
    assert all(not stage.exists() for stage in stages)
