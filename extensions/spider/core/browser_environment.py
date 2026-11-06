"""Owned disposable profiles; never delete or attach a user's browser profile."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from core.cookie_store import linked


DEFAULT_ROTATE_SECONDS = 300
DEFAULT_ROTATE_PAGES = 10


def default_session_directory():
    configured = os.environ.get("JINGXU_DATA_DIRECTORY")
    if configured:
        base = Path(configured)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "JingXu"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "JingXu"
    return base / "Spider/browser_profile"


def validate_session_directory(directory):
    directory = Path(directory).resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for relative in ("Google/Chrome/User Data", "Microsoft/Edge/User Data", "Chromium/User Data"):
            personal = (Path(local) / relative).resolve()
            if directory == personal or directory.is_relative_to(personal):
                raise ValueError("请使用软件独立数据目录，不能使用本机浏览器的个人资料目录。")
    if directory == directory.parent:
        raise ValueError("选品数据目录不能是磁盘根目录。")
    return directory


def create_environment(directory):
    directory = validate_session_directory(directory)
    environments = directory / "environments"
    if linked(environments):
        raise ValueError("浏览器环境目录不能是链接。")
    environments.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="env-", dir=environments)).resolve()
    if not path.is_relative_to(environments.resolve()):
        raise ValueError("浏览器环境目录超出独立数据目录。")
    token = uuid.uuid4().hex
    marker = {"schemaVersion": 1, "sessionDirectory": str(directory), "token": token,
              "ownerPid": os.getpid(), "createdAt": time.time()}
    (path / ".jingxu-environment.json").write_text(json.dumps(marker), encoding="utf-8")
    return path, token


def remove_environment(directory, path, token):
    """Delete only a marked, verified child after its browser has exited."""
    directory = validate_session_directory(directory)
    parent = directory / "environments"
    raw = Path(path)
    resolved = raw.resolve()
    if linked(parent) or linked(raw) or resolved == parent.resolve() or not resolved.is_relative_to(parent.resolve()):
        return False
    if not resolved.name.startswith("env-") or not resolved.is_dir():
        return False
    try:
        marker = json.loads((resolved / ".jingxu-environment.json").read_text(encoding="utf-8"))
        if marker.get("token") != token or Path(marker.get("sessionDirectory", "")).resolve() != directory:
            return False
        from core.profile_lock import profile_holder_state
        identity = (resolved.stat().st_dev, resolved.stat().st_ino)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not resolved.exists():
                return True
            # Retain ownership proof if a partial delete removed the marker,
            # while rejecting a replaced directory or a new reparse point.
            if linked(raw) or linked(parent) or not raw.resolve().is_relative_to(parent.resolve()):
                return False
            if (resolved.stat().st_dev, resolved.stat().st_ino) != identity:
                return False
            if profile_holder_state(resolved) == ():
                try:
                    # Verify the absolute scope before every recursive attempt.
                    shutil.rmtree(resolved)
                    return True
                except OSError:
                    pass
            time.sleep(0.1)
        return False
    except (OSError, ValueError, TypeError):
        return False


def active_environment(directory):
    root = Path(directory).resolve()
    file = root / "active-environment.json"
    if linked(file) or linked(root / "environments"):
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        path = Path(data["directory"]).resolve()
        if not path.is_relative_to((root / "environments").resolve()) or linked(Path(data["directory"])):
            return None
        marker = json.loads((path / ".jingxu-environment.json").read_text(encoding="utf-8"))
        if marker.get("token") != data.get("token") or Path(marker.get("sessionDirectory", "")).resolve() != root:
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None
