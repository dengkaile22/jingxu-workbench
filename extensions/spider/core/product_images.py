"""Bounded product-image retrieval; a missing image never aborts an export."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_IMAGE_BYTES = 4 * 1024 * 1024


def fetch_product_image(url: str) -> bytes:
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return b""
        request = Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"}
        )
        with urlopen(request, timeout=5) as response:
            if int(response.headers.get("Content-Length", "0") or 0) > MAX_IMAGE_BYTES:
                return b""
            data = response.read(MAX_IMAGE_BYTES + 1)
        return data if len(data) <= MAX_IMAGE_BYTES else b""
    except (OSError, ValueError, TypeError):
        return b""


def load_product_images(urls) -> dict[str, bytes]:
    unique = list(dict.fromkeys(url for url in urls if url))
    with ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="selection-images"
    ) as pool:
        return dict(zip(unique, pool.map(fetch_product_image, unique)))
