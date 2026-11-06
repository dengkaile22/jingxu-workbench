"""Learn a site's own profile-feed request so a fresh environment can resume it."""

import copy
import json
from urllib.parse import parse_qsl, urlencode, urlsplit


CURSOR_FIELDS = {"pcursor", "cursor", "pageCursor"}
USER_FIELDS = {"userId", "user_id", "userEid", "user_eid", "eid", "principalId"}


def _fields(node, names, path=(), depth=0):
    if depth > 6 or not isinstance(node, dict):
        return []
    result = []
    for key, value in node.items():
        if key in names:
            result.append((path + (key,), value))
        if isinstance(value, dict):
            result.extend(_fields(value, names, path + (key,), depth + 1))
    return result


def learn_kuaishou_feed_request(packet, user_id, previous=None):
    """Allow only the official profile feed and an explicit target-account field."""
    try:
        request = packet.request
        parsed = urlsplit(request.url)
        if parsed.hostname not in {"www.kuaishou.com", "kuaishou.com"} or parsed.path.rstrip("/") != "/rest/v/profile/feed":
            return None
        method = str(request.method).upper()
        if method not in {"GET", "POST"}:
            return None
        query = dict(parse_qsl(parsed.query))
        body = copy.deepcopy(request.postData) if method == "POST" else None
        encoding = "json"
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                body = dict(parse_qsl(body))
                encoding = "form"
        if method == "POST" and not isinstance(body, dict):
            return None
        candidate = body if method == "POST" else query
        if len(json.dumps(candidate, ensure_ascii=False)) > 65536:
            return None
        identities = _fields(candidate, USER_FIELDS)
        if not identities or any(str(value) != str(user_id) for _, value in identities):
            return None
        cursors = _fields(candidate, CURSOR_FIELDS)
        cursor_path = cursors[0][0] if cursors else None
        if cursor_path is None and previous is not None:
            cursor_path = tuple(previous.get("cursorPath") or ())
        if not cursor_path:
            return None
        return {"path": parsed.path, "method": method, "body": body, "query": query,
                "encoding": encoding, "cursorPath": list(cursor_path)}
    except (AttributeError, ValueError, TypeError):
        return None


def fetch_kuaishou_profile_feed(page, template, cursor):
    """Use fresh page credentials; never persist headers or request templates."""
    request = copy.deepcopy(template)
    container = request["body"] if request["method"] == "POST" else request["query"]
    path = request["cursorPath"]
    try:
        for key in path[:-1]:
            container = container[key]
        container[path[-1]] = str(cursor)
    except (KeyError, TypeError, IndexError):
        return None
    url = request["path"]
    if request["query"]:
        url += "?" + urlencode(request["query"])
    body = json.dumps(request["body"], ensure_ascii=False) if request["encoding"] == "json" else urlencode(request["body"] or {})
    script = f"""(async () => {{
        const pcursor = {json.dumps(str(cursor))};
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 10000);
        try {{
            const options = {{method: {json.dumps(request['method'])}, credentials: 'include', signal: controller.signal}};
            if (options.method === 'POST') {{
                options.headers = {{'content-type': {json.dumps('application/json' if request['encoding'] == 'json' else 'application/x-www-form-urlencoded')}}};
                options.body = {json.dumps(body)};
            }}
            const response = await window.fetch({json.dumps(url)}, options);
            return response.ok ? {{ok: true, data: await response.json()}} : {{ok: false}};
        }} catch (error) {{ return {{ok: false}}; }}
        finally {{ clearTimeout(timer); }}
    }})()"""
    try:
        result = page.run_js(script, as_expr=True)
        return result.get("data") if isinstance(result, dict) and result.get("ok") else None
    except Exception:
        return None
