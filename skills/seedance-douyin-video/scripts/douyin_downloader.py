#!/usr/bin/env python3
"""
抖音无水印视频下载和文案提取工具

功能:
1. 从抖音分享链接获取无水印视频下载链接
2. 下载视频并提取音频
3. 使用硅基流动 API 或本地 Whisper 从音频中提取文本
4. 自动保存文案到文件 (一个视频一个文件夹)

环境变量:
- API_KEY / DOUYIN_API_KEY / SILICONFLOW_API_KEY: 硅基流动 API 密钥 (优先用于文案提取功能)
- DOUYIN_WHISPER_MODEL: Python whisper 兜底模型名，默认 tiny
- DOUYIN_WHISPER_LANGUAGE: 本地 whisper 语言，默认 zh
- WHISPER_CPP_BIN / WHISPER_CPP_MODEL: 优先使用 whisper.cpp 快速本地转写

使用示例:
  # 获取下载链接 (无需 API 密钥)
  python douyin_downloader.py --link "抖音分享链接" --action info

  # 下载视频
  python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

  # 提取文案并保存到文件 (优先 API；无密钥时自动尝试本地 whisper)
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output
"""

import os
import re
import sys
import json
import hashlib
import argparse
import tempfile
import shutil
import subprocess
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional
from datetime import datetime


def check_dependencies():
    """Check only dependencies needed to parse and download a video.

    ``ffmpeg-python`` is required solely by the legacy transcript action.  It
    must not prevent the fast ``info`` and ``download`` paths from running.
    """
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print(f"请运行: pip install {' '.join(missing)}")
        sys.exit(1)


check_dependencies()

import requests

try:
    import ffmpeg
except ImportError:
    ffmpeg = None

# 请求头，模拟移动端访问
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}

PC_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}



# 硅基流动 API 配置
DEFAULT_API_BASE_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"


class DouyinProcessor:
    """抖音视频处理器"""

    def __init__(self, api_key: str = "", api_base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.api_base_url = api_base_url or DEFAULT_API_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.temp_dir = Path(tempfile.mkdtemp())
        self.deadline = time.monotonic() + 30

    def __del__(self):
        """清理临时目录"""
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _first_share_url(self, share_text: str) -> str:
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)
        if not urls:
            raise ValueError("未找到有效的分享链接")
        return urls[0]

    def _extract_video_id(self, text: str) -> Optional[str]:
        for pattern in (
            r"/video/(\d{15,20})",
            r"/note/(\d{15,20})",
            r"modal_id=(\d{15,20})",
            r"video_id=(\d{15,20})",
            r"\b(\d{15,20})\b",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _remaining(self, limit=8):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError("DOUYIN_INTAKE_TIMEOUT")
        return min(limit, remaining)

    def _resolve_video_id(self, share_text):
        url = self._first_share_url(share_text)
        video_id = self._extract_video_id(url)
        if not video_id and getattr(self, "_resolved_share_url", None) == url:
            video_id = getattr(self, "_resolved_video_id", None)
        if not video_id:
            response = requests.get(url, headers=HEADERS, timeout=self._remaining())
            response.raise_for_status()
            video_id = self._extract_video_id(response.url)
            response.close()
        if not video_id: raise ValueError("SHARE_VIDEO_ID_UNAVAILABLE")
        self._resolved_share_url, self._resolved_video_id = url, video_id
        return video_id

    def _check_local_video(self, path, registered=None):
        if not path.is_file() or path.stat().st_size == 0: return False
        if registered is not None:
            return path.stat().st_size == registered.get("size") and hashlib.sha256(path.read_bytes()).hexdigest() == registered.get("sha256")
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)], capture_output=True, text=True, timeout=self._remaining(5))
            data = json.loads(probe.stdout)
            if probe.returncode or not any(x.get("codec_type") == "video" for x in data.get("streams", [])) or float(data.get("format", {}).get("duration", 0)) <= 0: return False
            decode = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"], capture_output=True, timeout=self._remaining(8))
            return decode.returncode == 0 and not decode.stderr.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired): return False

    def _remember_local(self, video_id, path):
        path = path.resolve()
        self._cache["links"][self._cache_share] = video_id
        self._cache["sources"][video_id] = {"path": str(path), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self._cache_path.parent, delete=False) as tmp:
            json.dump(self._cache, tmp, ensure_ascii=False); temporary = tmp.name
        os.replace(temporary, self._cache_path)

    def _reuse_local(self, share_text, output_dir):
        output_dir = Path(output_dir).resolve()
        intake = Path.cwd()/"outputs"/"intake"
        indexes = [output_dir/".douyin-cache.json"]
        if intake.is_dir(): indexes.append(intake/".douyin-cache.json")
        self._cache = {"links": {}, "sources": {}}
        for index in indexes:
            try:
                old = json.loads(index.read_text())
                if not isinstance(old, dict): continue
                for key in self._cache:
                    if isinstance(old.get(key), dict): self._cache[key].update(old[key])
            except (OSError, ValueError, TypeError): pass
        self._cache_path = indexes[-1]; self._cache_share = self._first_share_url(share_text)
        video_id = self._extract_video_id(self._cache_share) or self._cache["links"].get(self._cache_share)
        if not video_id: video_id = self._resolve_video_id(share_text)
        self._resolved_share_url, self._resolved_video_id = self._cache_share, video_id
        registered = self._cache["sources"].get(video_id)
        if registered and self._check_local_video(Path(registered["path"]), registered):
            if self._cache["links"].get(self._cache_share) != video_id:
                self._remember_local(video_id, Path(registered["path"]))
            return Path(registered["path"])
        candidates = []
        for name in (video_id+".mp4", video_id+"_原片.mp4", video_id+"_完整原片.mp4"):
            candidates.append(output_dir/name)
            if intake.is_dir(): candidates.extend(intake.glob("*/"+name))
        for path in candidates:
            if registered and path.resolve() == Path(registered["path"]).resolve(): continue
            if self._check_local_video(path):
                self._remember_local(video_id, path); return path.resolve()
        return None

    def _router_data_from_html(self, html: str) -> dict:
        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(html)

        if not find_res or not find_res.group(1):
            raise ValueError("从HTML中解析视频信息失败")

        return json.loads(find_res.group(1).strip())

    def _video_info_from_router_data(self, json_data: dict, video_id: str) -> dict:
        loader_data = json_data.get("loaderData") or {}
        original_video_info = None

        for page_key in ("video_(id)/page", "note_(id)/page"):
            page_data = loader_data.get(page_key)
            if isinstance(page_data, dict) and page_data.get("videoInfoRes"):
                original_video_info = page_data["videoInfoRes"]
                break

        if original_video_info is None:
            for page_data in loader_data.values():
                if isinstance(page_data, dict) and page_data.get("videoInfoRes"):
                    original_video_info = page_data["videoInfoRes"]
                    break

        if original_video_info is None:
            raise ValueError("SSR_MEDIA_ABSENT: public page contains no media payload for " + video_id)

        data = original_video_info["item_list"][0]

        video = data.get("video") or {}
        play_addr = video.get("play_addr") or {}
        raw_urls = list(play_addr.get("url_list") or [])
        for bit_rate in video.get("bit_rate") or []:
            for candidate in (bit_rate.get("play_addr") or {}).get("url_list") or []:
                raw_urls.append(candidate)

        url_list = []
        seen = set()
        for url in raw_urls:
            clean_url = url.replace("playwm", "play")
            if clean_url and clean_url not in seen:
                seen.add(clean_url)
                url_list.append(clean_url)

        if not url_list:
            raise Exception("无法从JSON中解析下载地址")

        desc = data.get("desc", "").strip() or f"douyin_{video_id}"

        # 替换文件名中的非法字符
        desc = re.sub(r'[\\/:*?"<>|]', '_', desc)

        return {
            "url": url_list[0],
            "url_list": url_list,
            "title": desc,
            "video_id": video_id
        }

    def _parse_share_url_requests(self, share_text: str) -> dict:
        video_id = self._resolve_video_id(share_text)
        video_page_url = f'https://www.iesdouyin.com/share/video/{video_id}'
        response = requests.get(video_page_url, headers=HEADERS, timeout=self._remaining())
        response.raise_for_status()

        json_data = self._router_data_from_html(response.text)
        return self._video_info_from_router_data(json_data, video_id)

    def _parse_share_url_playwright(self, share_text: str, previous_error: Optional[Exception] = None) -> dict:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "requests 解析失败，且未安装 playwright，无法启用真实浏览器兜底。"
                "请运行: python3 -m pip install playwright && python3 -m playwright install chromium"
            ) from previous_error or exc

        share_url = self._first_share_url(share_text)
        # Capture the CDN URL while the page is actively playing the video.
        # The m.douyin.com/aweme/v1/play URL is a per-session signed token; it
        # 302-redirects to the real CDN URL, but the token expires as soon as
        # the page stops needing it, so we must grab the Location header
        # during the initial page load.
        captured_cdn_urls: list[str] = []

        def _on_response(resp) -> None:
            try:
                u = resp.url
                if "aweme/v1/play" in u and 300 <= resp.status < 400:
                    loc = (resp.headers.get("location")
                           or resp.headers.get("Location")
                           or resp.headers.get("LOCATION"))
                    if loc and "douyinvod.com" in loc:
                        captured_cdn_urls.append(loc)
                if "douyinvod.com" in u and resp.status in (200, 206):
                    captured_cdn_urls.append(u)
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
                video_id = self._extract_video_id(page.url) or self._extract_video_id(page.content())
                if not video_id:
                    raise ValueError(f"Playwright 无法解析视频ID: {page.url}")

                # The mobile share page embeds a <video> element with the play URL
                # directly on the DOM. Read it instead of fighting the v1/v2 JSON
                # endpoints (whose PC paths are now behind iesdouyin 风控 and
                # whose mobile v2 list endpoint drops the play_addr payload).
                # The m.douyin.com/aweme/v1/playwm URL is a 302-redirector
                # that only resolves with the page's session cookies; follow
                # it via ctx.request so download_video can stream the real CDN
                # URL with plain requests.
                page.wait_for_timeout(3500)
                # The page only embeds the play URL on the DOM but does not
                # actually fire the video XHR until the user (or us) triggers
                # the player. Force a load so the 302-redirect resolves to
                # the real CDN URL while the signed token is still fresh.
                if not captured_cdn_urls:
                    try:
                        page.evaluate("""() => {
                            const v = document.querySelector('video');
                            if (v) { v.muted = true; v.load(); v.play().catch(()=>{}); }
                        }""")
                        page.wait_for_timeout(3500)
                    except Exception:
                        pass
                if captured_cdn_urls:
                    cdn_url = captured_cdn_urls[0]
                else:
                    dom_url = self._read_video_src(page)
                    no_wm = (dom_url or "").replace("playwm", "play")
                    cdn_url = no_wm
                title = self._read_video_title(page) or f"douyin_{video_id}"
                title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or f"douyin_{video_id}"
                if cdn_url:
                    return {
                        "url": cdn_url,
                        "url_list": [cdn_url],
                        "title": title,
                        "video_id": video_id,
                    }

                # Fall back to a router-data parse if no <video> src appeared.
                router_json = page.evaluate("() => window._ROUTER_DATA ? JSON.stringify(window._ROUTER_DATA) : null")
                if router_json:
                    json_data = json.loads(router_json)
                else:
                    json_data = self._router_data_from_html(page.content())
                return self._video_info_from_router_data(json_data, video_id)
            finally:
                context.close()
                browser.close()

    @staticmethod
    def _read_video_src(page) -> Optional[str]:
        try:
            return page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (!v) return null;
                    return v.currentSrc || v.src || (v.querySelector('source') && v.querySelector('source').src) || null;
                }"""
            )
        except Exception:
            return None

    @staticmethod
    def _read_video_title(page) -> str:
        try:
            return page.evaluate(
                """() => {
                    const m = document.querySelector('meta[property="og:title"]');
                    if (m && m.content) return m.content;
                    const t = document.querySelector('title');
                    return t ? t.textContent || '' : '';
                }"""
            ) or ""
        except Exception:
            return ""

    @staticmethod
    def _existing_cdp_url() -> str:
        explicit = os.getenv("DOUYIN_CDP_URL")
        if explicit:
            parsed = urlparse(explicit)
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not parsed.port:
                raise ValueError("EXISTING_CHROME_CDP_URL_INVALID")
            return explicit
        # Discover only this user's already-running Google Chrome listeners.
        found = subprocess.run(["lsof", "-nP", "-a", "-u", str(os.getuid()),
                                "-c", "Google Chrome", "-iTCP", "-sTCP:LISTEN", "-Fpn"],
                               capture_output=True, text=True, timeout=2)
        ports = list(dict.fromkeys(re.findall(r"^n(?:127\.0\.0\.1|\[::1\]|\*):(\d+)$", found.stdout, re.M)))
        session = requests.Session(); session.trust_env = False
        end = time.monotonic() + 2
        for port in ports[:8]:
            if time.monotonic() >= end: break
            base = "http://127.0.0.1:" + port
            try:
                data = session.get(base + "/json/version", timeout=min(.5, max(.05, end-time.monotonic()))).json()
                if str(data.get("Browser", "")).startswith("Chrome/") and data.get("webSocketDebuggerUrl"):
                    return base
            except (requests.RequestException, ValueError):
                pass
        raise ValueError("EXISTING_CHROME_CDP_UNAVAILABLE")

    def _parse_share_url_existing_chrome(self, share_text: str, video_id: Optional[str] = None) -> dict:
        from playwright.sync_api import sync_playwright
        self._remaining()
        cdp_url = self._existing_cdp_url()
        if not video_id: video_id = self._resolve_video_id(share_text)
        if not video_id: raise ValueError("SHARE_VIDEO_ID_UNAVAILABLE")
        candidates = []
        def observed(response):
            try:
                if ("douyinvod.com" in (urlparse(response.url).hostname or "") and
                    response.status in (200, 206) and
                    response.headers.get("content-type", "").lower().startswith("video/")):
                    if response.url not in candidates: candidates.append(response.url)
            except Exception:
                pass
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url, timeout=self._remaining(12)*1000, no_defaults=True)
            if not browser.contexts: raise ValueError("EXISTING_CHROME_CONTEXT_UNAVAILABLE")
            page = browser.contexts[0].new_page()
            page.on("response", observed)
            try:
                page.goto("https://www.douyin.com/video/" + video_id, wait_until="domcontentloaded", timeout=self._remaining(12)*1000)
                if self._extract_video_id(page.url) != video_id: raise ValueError("EXISTING_PAGE_VIDEO_MISMATCH")
                end = min(time.monotonic() + 3, self.deadline)
                active = None
                while time.monotonic() < end:
                    videos = page.evaluate("""() => [...document.querySelectorAll('video')].map(v => {
                        const r=v.getBoundingClientRect();
                        return {src:v.currentSrc||v.src||'', duration:Number.isFinite(v.duration)?v.duration:null,
                                area:Math.max(0,r.width)*Math.max(0,r.height),ready:v.readyState};
                    }).filter(v=>v.area>0&&v.ready>0).sort((a,b)=>b.area-a.area)""")
                    active = videos[0] if videos else None
                    if candidates and active: break
                    page.wait_for_timeout(100)
                active_url = active.get("src", "") if active else ""
                matched = [u for u in candidates if u == active_url]
                if matched: media = matched[0]
                elif len(candidates) == 1 and active: media = candidates[0]
                else: raise ValueError("EXISTING_PAGE_MEDIA_UNAVAILABLE" if not candidates else "EXISTING_PAGE_MEDIA_AMBIGUOUS")
                title = self._read_video_title(page) or "douyin_" + video_id
                title = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
                return {"url":media,"url_list":[media],"title":title,"video_id":video_id,
                        "observed_duration":active.get("duration"),"transport":"existing_chrome"}
            finally:
                page.close()

    def parse_share_url(self, share_text: str) -> dict:
        """Public payload first, then reuse existing Chrome; new browser is explicit only."""
        if os.getenv("DOUYIN_FORCE_PLAYWRIGHT") == "1":
            return self._parse_share_url_playwright(share_text)
        try:
            return self._parse_share_url_requests(share_text)
        except TimeoutError:
            raise
        except Exception:
            self._remaining()
            return self._parse_share_url_existing_chrome(share_text)

    def download_video(self, video_info: dict, output_dir: Optional[Path] = None, show_progress: bool = True) -> Path:
        output_dir = Path(output_dir) if output_dir is not None else self.temp_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        video_id = video_info["video_id"]
        share = getattr(self, "_cache_share", "https://www.douyin.com/video/"+video_id)
        cached = self._reuse_local(share, output_dir)
        if cached: return cached
        filepath = output_dir/(video_id+".mp4")
        if filepath.exists(): filepath = output_dir/(video_id+"_recovered_"+str(time.time_ns())+".mp4")
        for attempt in range(2):
            self._remaining()
            if attempt: video_info = self._parse_share_url_existing_chrome("https://www.douyin.com/video/"+video_id, video_id)
            temp_path = None
            try:
                with requests.get(video_info["url"], headers={**PC_HEADERS, "Referer": "https://www.douyin.com/"}, stream=True, timeout=self._remaining()) as response:
                    if response.status_code != 200: raise ValueError("MEDIA_HTTP_"+str(response.status_code))
                    with tempfile.NamedTemporaryFile(dir=output_dir, prefix="."+video_id+"-", suffix=".part", delete=False) as target:
                        temp_path = Path(target.name)
                        for chunk in response.iter_content(chunk_size=64*1024):
                            self._remaining()
                            if chunk: target.write(chunk)
                    if not self._check_local_video(temp_path): raise ValueError("DOWNLOADED_MEDIA_INVALID")
                    self._remaining()
                    os.link(temp_path, filepath); temp_path.unlink(); temp_path = None
                    self._remember_local(video_id, filepath)
                    if show_progress: print("视频已保存到: "+str(filepath))
                    return filepath
            except TimeoutError: raise
            except (requests.RequestException, ValueError, OSError):
                if attempt: raise RuntimeError("MEDIA_DOWNLOAD_FAILED_AFTER_REFRESH") from None
            finally:
                if temp_path is not None: temp_path.unlink(missing_ok=True)
        raise RuntimeError("MEDIA_DOWNLOAD_FAILED")

    def extract_audio(self, video_path: Path, show_progress: bool = True) -> Path:
        """从视频文件中提取音频"""
        if ffmpeg is None:
            raise RuntimeError(
                "文案提取需要 ffmpeg-python；仅下载视频时不需要它。"
                "请安装: pip install ffmpeg-python"
            )
        audio_path = video_path.with_suffix('.mp3')

        if show_progress:
            print("正在提取音频...")
        try:
            (
                ffmpeg
                .input(str(video_path))
                .output(str(audio_path), acodec='libmp3lame', q=0)
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            if show_progress:
                print(f"音频提取完成: {audio_path}")
            return audio_path
        except Exception as e:
            raise Exception(f"提取音频时出错: {str(e)}")

    def extract_text_from_audio(self, audio_path: Path, show_progress: bool = True) -> str:
        """从音频文件中提取文字"""
        if not self.api_key:
            raise ValueError("未设置 API 密钥，请设置环境变量 API_KEY、DOUYIN_API_KEY 或 SILICONFLOW_API_KEY")

        if show_progress:
            print("正在识别语音...")
        files = {
            'file': (audio_path.name, open(audio_path, 'rb'), 'audio/mpeg'),
            'model': (None, self.model)
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            response = requests.post(
                self.api_base_url,
                files=files,
                headers=headers,
                timeout=int(os.getenv("SILICONFLOW_TIMEOUT_SECONDS", "90")),
            )
            response.raise_for_status()

            # 解析响应
            result = response.json()
            if 'text' in result:
                return result['text']
            else:
                return response.text

        except Exception as e:
            raise Exception(f"提取文字时出错: {str(e)}")
        finally:
            files['file'][1].close()

    def extract_text_from_audio_local_whisper(self, audio_path: Path, show_progress: bool = True) -> str:
        """Use the same configured local ASR chain as fast_transcribe.py."""
        from fast_transcribe import transcribe_audio
        result = transcribe_audio(audio_path, os.getenv("DOUYIN_WHISPER_LANGUAGE", "zh"),
                                  os.getenv("DOUYIN_WHISPER_MODEL", "tiny"), self.temp_dir)
        self.last_local_transcriber = result["backend"]
        if show_progress:
            print("本地转写: " + result["backend"])
        return result["text"]

    def cleanup_files(self, *file_paths: Path):
        """清理指定的文件"""
        for file_path in file_paths:
            if file_path.exists():
                file_path.unlink()


def get_video_info(share_link: str) -> dict:
    """获取视频信息和下载链接"""
    processor = DouyinProcessor()
    return processor.parse_share_url(share_link)


def download_video(share_link: str, output_dir: str = ".", show_progress: bool = True) -> Path:
    """下载视频到指定目录"""
    processor = DouyinProcessor()
    cached = processor._reuse_local(share_link, Path(output_dir))
    if cached: return cached
    video_info = processor.parse_share_url(share_link)
    return processor.download_video(video_info, Path(output_dir), show_progress=show_progress)


def extract_text(share_link: str, api_key: Optional[str] = None, output_dir: Optional[str] = None,
                 save_video: bool = False, show_progress: bool = True) -> dict:
    """
    从视频中提取文案并保存到文件

    返回:
        dict: 包含 video_info, text, output_path 的字典
    """
    api_key = api_key or os.getenv('API_KEY') or os.getenv('DOUYIN_API_KEY') or os.getenv('SILICONFLOW_API_KEY')

    processor = DouyinProcessor(api_key)

    if show_progress:
        print("正在解析抖音分享链接...")
    video_path = processor._reuse_local(share_link, Path(output_dir) if output_dir else processor.temp_dir)
    if video_path:
        video_id = processor._resolved_video_id
        video_info = {"video_id": video_id, "title": "douyin_"+video_id,
                      "url": "https://www.douyin.com/video/"+video_id}
    else:
        video_info = processor.parse_share_url(share_link)
        if show_progress: print("正在下载视频...")
        video_path = processor.download_video(video_info, show_progress=show_progress)
    if not video_path.resolve().is_relative_to(processor.temp_dir.resolve()):
        temporary_video = processor.temp_dir/(video_info["video_id"]+".mp4")
        shutil.copy2(video_path, temporary_video)
        video_path = temporary_video

    if show_progress:
        print("正在提取音频...")
    audio_path = processor.extract_audio(video_path, show_progress=show_progress)

    if show_progress:
        print("正在从音频中提取文本...")
    if api_key:
        text_content = processor.extract_text_from_audio(audio_path, show_progress=show_progress)
        transcriber = "siliconflow"
    else:
        text_content = processor.extract_text_from_audio_local_whisper(audio_path, show_progress=show_progress)
        transcriber = processor.last_local_transcriber

    result = {
        "video_info": video_info,
        "text": text_content,
        "output_path": None,
        "transcriber": transcriber
    }

    # 保存到文件
    if output_dir:
        output_base = Path(output_dir)
        video_folder = output_base / video_info['video_id']
        video_folder.mkdir(parents=True, exist_ok=True)

        # 保存文案为 Markdown 格式
        transcript_path = video_folder / "transcript.md"
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write(f"# {video_info['title']}\n\n")
            f.write(f"| 属性 | 值 |\n")
            f.write(f"|------|----|\n")
            f.write(f"| 视频ID | `{video_info['video_id']}` |\n")
            f.write(f"| 提取时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |\n")
            f.write(f"| 转写方式 | {transcriber} |\n")
            f.write(f"| 下载链接 | [点击下载]({video_info['url']}) |\n\n")
            f.write(f"---\n\n")
            f.write(f"## 文案内容\n\n")
            f.write(text_content)

        result["output_path"] = str(video_folder)

        if show_progress:
            print(f"文案已保存到: {transcript_path}")

        # 保存视频 (可选)
        if save_video:
            saved_video_path = video_folder / f"{video_info['video_id']}.mp4"
            if not saved_video_path.exists(): shutil.copy2(video_path, saved_video_path)
            if show_progress:
                print(f"视频已保存到: {saved_video_path}")

    # 清理临时文件
    if show_progress:
        print("正在清理临时文件...")
    processor.cleanup_files(video_path, audio_path)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="抖音无水印视频下载和文案提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 获取视频信息和下载链接
  python douyin_downloader.py --link "抖音分享链接" --action info

  # 下载视频
  python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

  # 提取文案并保存到文件 (优先 API；无密钥时自动尝试本地 whisper)
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

  # 提取文案并同时保存视频
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output --save-video
        """
    )

    parser.add_argument("--link", "-l", required=True, help="抖音分享链接或包含链接的文本")
    parser.add_argument("--action", "-a", choices=["info", "download", "extract"],
                        default="info", help="操作类型: info(获取信息), download(下载视频), extract(提取文案)")
    parser.add_argument("--output", "-o", default="./output", help="输出目录 (默认 ./output)")
    parser.add_argument("--api-key", "-k", help="硅基流动 API 密钥 (也可通过 API_KEY / DOUYIN_API_KEY / SILICONFLOW_API_KEY 环境变量设置)")
    parser.add_argument("--save-video", "-v", action="store_true", help="提取文案时同时保存视频")
    parser.add_argument("--quiet", "-q", action="store_true", help="安静模式，减少输出")

    args = parser.parse_args()

    try:
        if args.action == "info":
            info = get_video_info(args.link)
            print("\n" + "=" * 50)
            print("视频信息:")
            print("=" * 50)
            print(f"视频ID: {info['video_id']}")
            print(f"标题: {info['title']}")
            print(f"下载链接: {info['url']}")
            print("=" * 50)

        elif args.action == "download":
            video_path = download_video(args.link, args.output, show_progress=not args.quiet)
            print(f"\n视频已保存到: {video_path}")

        elif args.action == "extract":
            result = extract_text(
                args.link,
                args.api_key,
                output_dir=args.output,
                save_video=args.save_video,
                show_progress=not args.quiet
            )

            if not args.quiet:
                print("\n" + "=" * 50)
                print("提取完成!")
                print("=" * 50)
                print(f"视频ID: {result['video_info']['video_id']}")
                print(f"标题: {result['video_info']['title']}")
                if result['output_path']:
                    print(f"保存位置: {result['output_path']}")
                print("=" * 50)
                print("\n文案内容:\n")
                print(result['text'][:500] + "..." if len(result['text']) > 500 else result['text'])
                print("\n" + "=" * 50)

    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
