#!/usr/bin/env python3
"""
抖音视频 BGM 提取器
用法：
    python3 extract_bgm.py "https://v.douyin.com/xxxxx/"
    python3 extract_bgm.py "https://www.iesdouyin.com/share/video/7646365452029516468"
"""
from __future__ import annotations  # PEP 604 (T | None) for Python 3.9 compat

import json
import re
import sys
from typing import Any

import requests

# 移动端 UA 必加，桌面端会被 WAF 拦
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0 Mobile Safari/537.36"
}


def _first_url(value: str) -> str:
    """Return the first URL from normal Douyin share text without punctuation."""
    urls = re.findall(r"https?://[^\s]+", value)
    if not urls:
        raise ValueError("输入里没找到 http(s) 链接")
    return urls[0].rstrip("。！？；，,.!?)】》\"'")


def _video_id_from_url(value: str) -> str:
    match = re.search(r"/(?:video|note)/(\d{15,22})(?:[/?#]|$)", value)
    if not match:
        match = re.search(r"(?:modal_id|video_id)=(\d{15,22})", value)
    return match.group(1) if match else ""


def _router_data_from_html(html: str) -> dict[str, Any]:
    """Decode the router object without assuming a semicolon-free script tag.

    Douyin has used both ``{...}`` and ``{...};`` forms.  ``raw_decode`` reads
    exactly the first JSON object, so trailing JavaScript cannot break metadata
    extraction.
    """
    match = re.search(r"window\._ROUTER_DATA\s*=\s*", html)
    if not match:
        raise RuntimeError("页面里没找到 _ROUTER_DATA；可能被风控拦截或页面结构已变化")
    source = html[match.end() :].lstrip()
    try:
        data, _ = json.JSONDecoder().raw_decode(source)
    except json.JSONDecodeError as exc:
        raise RuntimeError("_ROUTER_DATA 不是可解析的 JSON；请走浏览器兜底") from exc
    if not isinstance(data, dict):
        raise RuntimeError("_ROUTER_DATA 结构异常")
    return data


def _item_from_router_data(router_data: dict[str, Any]) -> dict[str, Any]:
    loader_data = router_data.get("loaderData") or {}
    candidates = [loader_data.get("video_(id)/page"), loader_data.get("note_(id)/page")]
    candidates.extend(value for value in loader_data.values() if isinstance(value, dict))
    for page_data in candidates:
        if not isinstance(page_data, dict):
            continue
        video_info = page_data.get("videoInfoRes") or {}
        items = video_info.get("item_list") or video_info.get("itemList") or []
        if items and isinstance(items[0], dict):
            return items[0]
    raise RuntimeError("页面没有可用的视频元数据；链接可能是图集、已下架或页面结构已变化")


def extract_bgm(share_text_or_url: str, timeout: int = 20, session: requests.Session | None = None, *, allow_browser: bool = False) -> dict[str, Any]:
    """Extract embedded Douyin music metadata.

    This is deliberately a lightweight metadata route.  It reports that song
    information is unavailable rather than downloading audio or starting a
    long-running recognition job.
    """
    share_url = _first_url(share_text_or_url)
    client = session or requests.Session()
    share_response = client.get(share_url, headers=HEADERS, allow_redirects=True, timeout=timeout)
    share_response.raise_for_status()
    video_id = _video_id_from_url(share_response.url) or _video_id_from_url(share_text_or_url)
    if not video_id:
        raise RuntimeError(f"无法从跳转链接解析视频 ID: {share_response.url}")

    # Fast path: try the legacy iesdouyin /share/video/<id> page first. Many
    # shorter share URLs still serve a populated _ROUTER_DATA, and the
    # requests-only path is cheap.
    page_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    response = client.get(page_url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    metadata_source = "douyin-router-data"
    try:
        data = _item_from_router_data(_router_data_from_html(response.text))
    except RuntimeError:
        # Modern m.douyin.com share pages serve an empty _ROUTER_DATA
        # skeleton; the real item lives in the v2 /web/api/v2/aweme/post
        # XHR. Open the share page in a real browser to read it.
        if not allow_browser:
            raise RuntimeError("BGM元数据未取得；可沿现有授权页面读取。仅显式 --allow-browser 才启动独立浏览器。")
        data = _fetch_item_via_playwright(video_id)
        metadata_source = "douyin-browser-response"

    music = data.get("music") or {}
    author = data.get("author") or {}
    video = data.get("video") or {}
    play_addr = video.get("play_addr") or {}
    url_list = play_addr.get("url_list") or []
    duration_ms = video.get("duration") or 0

    return {
        "metadata_source": metadata_source,
        "video_id": video_id,
        "video_title": (data.get("desc") or "").strip(),
        "video_author": author.get("nickname", ""),
        "video_duration_sec": float(duration_ms) / 1000,
        "video_url": (url_list[0] if url_list else "").replace("playwm", "play"),
        "bgm_title": music.get("title", ""),
        "bgm_author": music.get("author", ""),
        "bgm_id": music.get("mid", ""),
        "bgm_duration_sec": music.get("duration", 0),
        "bgm_is_pgc": bool(music.get("is_pgc", False)),
        "bgm_is_original": bool(music.get("is_original_sound", False)),
    }


def _fetch_item_via_playwright(video_id: str) -> dict[str, Any]:
    """Open the share page in a real browser and read the matching aweme from
    the m.douyin.com /web/api/v2/aweme/post XHR. Used only as a fallback when
    the requests-only path returns an empty _ROUTER_DATA skeleton.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "iesdouyin 页面 _ROUTER_DATA 为空，且未安装 playwright。"
            "请运行: python3 -m pip install playwright && python3 -m playwright install chromium"
        ) from exc

    share_url = f"https://www.douyin.com/video/{video_id}"
    captured: list[dict] = []

    def _on_response(resp) -> None:
        try:
            u = resp.url
            if (
                "/web/api/v2/aweme/post" in u
                or "/web/api/v2/aweme/iteminfo" in u
                or "/aweme/v1/web/aweme/post" in u
                or "/aweme/v1/web/aweme/detail" in u
            ):
                body = resp.body()
                parsed = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    captured.append({"url": u, "data": parsed})
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            locale="zh-CN",
        )
        page = context.new_page()
        page.on("response", _on_response)
        try:
            page.goto(share_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            # Force a second pass if neither endpoint returned our item yet.
            page.wait_for_timeout(3500)
            matched = any(_has_target_aweme(c["data"], video_id) for c in captured)
            if not matched:
                page.goto(share_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5500)
        finally:
            context.close()
            browser.close()

    for entry in captured:
        for key in ("aweme_list", "awemeList", "aweme_detail", "item_list", "itemList"):
            bucket = entry["data"].get(key)
            if isinstance(bucket, list):
                for item in bucket:
                    if isinstance(item, dict) and str(item.get("aweme_id") or "") == video_id:
                        return item
            elif isinstance(bucket, dict) and str(bucket.get("aweme_id") or "") == video_id:
                return bucket
    raise RuntimeError("v2 兜底未匹配到目标视频")


def _has_target_aweme(payload, video_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("aweme_list", "awemeList", "aweme_detail", "item_list", "itemList"):
        bucket = payload.get(key)
        if isinstance(bucket, list):
            for item in bucket:
                if isinstance(item, dict) and str(item.get("aweme_id") or "") == video_id:
                    return True
        elif isinstance(bucket, dict) and str(bucket.get("aweme_id") or "") == video_id:
            return True
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 extract_bgm.py <抖音分享链接或分享文本>")
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("link")
    parser.add_argument("--allow-browser", action="store_true", help="Explicitly allow a separate headless browser fallback")
    args = parser.parse_args()
    info = extract_bgm(args.link, allow_browser=args.allow_browser)

    print("=" * 50)
    print("视频信息")
    print("=" * 50)
    print(f"  视频 ID:    {info['video_id']}")
    print(f"  标题:       {info['video_title']}")
    print(f"  作者:       {info['video_author']}")
    print(f"  时长:       {info['video_duration_sec']:.1f}s")
    print()
    print("=" * 50)
    print("BGM 信息")
    print("=" * 50)
    print(f"  歌名:       {info['bgm_title']}")
    print(f"  歌手:       {info['bgm_author']}")
    print(f"  音乐 ID:    {info['bgm_id']}")
    print(f"  时长:       {info['bgm_duration_sec']}s")
    print(f"  平台PGC标记（不是商用授权）:   {info['bgm_is_pgc']}")
    print(f"  是否原创:   {info['bgm_is_original']}")
