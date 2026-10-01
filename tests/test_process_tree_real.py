"""Verify a real Windows child and grandchild terminate under the guard."""
import json,os,subprocess,sys,time
from pathlib import Path
import pytest
from jingxu.infrastructure.process_control import ProcessTreeGuard

@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object test')
def test_job_object_terminates_real_descendant_tree(tmp_path):
    import psutil
    marker=tmp_path/'grandchild-pid.txt'
    program="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);Path("+repr(str(marker))+").write_text(str(p.pid));time.sleep(30)"
    guard=ProcessTreeGuard()
    process=subprocess.Popen([sys.executable,'-c',program],**guard.spawn_kwargs())
    grandchild=None
    try:
        guard.attach(process)
        assert guard._job_handle
        deadline=time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert marker.exists()
        grandchild=psutil.Process(int(marker.read_text()))
        guard.terminate(process,timeout=3)
        assert process.poll() is not None
        _,alive=psutil.wait_procs([grandchild],timeout=3)
        assert not alive
    finally:
        if process.poll() is None:guard.terminate(process)
        guard.close()
        if grandchild is not None and grandchild.is_running():grandchild.kill()
