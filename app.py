"""Small YouTube Music backed API for Render's free web service."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from functools import lru_cache
from typing import Any

import yt_dlp
import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from ytmusicapi import YTMusic


class Track(BaseModel):
    videoId: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration: str | None = None
    thumbnail: str | None = None
    youtubeUrl: str


class StreamResponse(BaseModel):
    videoId: str
    url: str
    mimeType: str | None = None
    bitrate: int | None = None
    expiresIn: int | None = None


class XiaozhiStreamResponse(BaseModel):
    title: str
    artist: str
    audio_url: str
    lyric_url: str = ""
    video_id: str | None = None


def public_base_url(request: Request) -> str:
    """Build an externally reachable URL when Render terminates TLS upstream."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


app = FastAPI(title="Lightweight Music Server", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def music_client() -> YTMusic:
    return YTMusic()


_search_cache: dict[str, tuple[float, list[Track]]] = {}
_stream_cache: dict[str, tuple[float, StreamResponse]] = {}
SEARCH_TTL = int(os.getenv("SEARCH_CACHE_TTL", "300"))
STREAM_TTL = int(os.getenv("STREAM_CACHE_TTL", "180"))


def _thumbnail(item: dict[str, Any]) -> str | None:
    thumbs = item.get("thumbnails") or []
    return thumbs[-1].get("url") if thumbs else None


def _track(item: dict[str, Any]) -> Track:
    artists = [a.get("name", "") for a in item.get("artists", []) if a.get("name")]
    album = item.get("album")
    return Track(
        videoId=item["videoId"],
        title=item.get("title", "Untitled"),
        artists=artists,
        album=album.get("name") if isinstance(album, dict) else album,
        duration=item.get("duration"),
        thumbnail=_thumbnail(item),
        youtubeUrl=f"https://music.youtube.com/watch?v={item['videoId']}",
    )


def _search_sync(query: str, limit: int) -> list[Track]:
    now = time.monotonic()
    cached = _search_cache.get(query)
    if cached and cached[0] > now:
        return cached[1][:limit]
    results = music_client().search(query, filter="songs")
    tracks = [_track(item) for item in results if item.get("videoId")]
    _search_cache[query] = (now + SEARCH_TTL, tracks)
    return tracks[:limit]


def _resolve_stream_sync(video_id: str) -> StreamResponse:
    now = time.monotonic()
    cached = _stream_cache.get(video_id)
    if cached and cached[0] > now:
        return cached[1]
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "format": "bestaudio/best", "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Không lấy được stream: {exc}") from exc
    formats = [f for f in info.get("formats", []) if f.get("url") and f.get("acodec") != "none"]
    if not formats and info.get("url"):
        formats = [info]
    if not formats:
        raise HTTPException(status_code=404, detail="Video không có audio stream khả dụng")
    # Prefer formats that common ESP32 audio decoders can consume directly.
    # AAC in an MP4 container is broadly supported by ESP32 audio players.
    # Prefer it over Opus/WebM, which many Xiaozhi builds cannot decode.
    def format_score(fmt: dict[str, Any]) -> tuple[int, float]:
        codec = fmt.get("acodec", "")
        preference = 3 if codec.startswith("mp4a") else 2 if codec.startswith("mp3") else 1
        return preference, float(fmt.get("abr") or fmt.get("tbr") or 0)

    chosen = max(formats, key=format_score)
    response = StreamResponse(videoId=video_id, url=chosen["url"], mimeType=chosen.get("mime_type"), bitrate=int(chosen["abr"]) if chosen.get("abr") else None, expiresIn=STREAM_TTL)
    _stream_cache[video_id] = (now + STREAM_TTL, response)
    return response


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Music Server Test</title><style>
body{font:16px system-ui;background:#10131a;color:#eef1f7;max-width:760px;margin:40px auto;padding:0 18px}h1{margin-bottom:6px}p{color:#aeb8c8}.search{display:flex;gap:8px;margin:24px 0}.search input{flex:1;padding:13px;border:1px solid #394354;border-radius:9px;background:#1a202c;color:white;font-size:16px}.search button,.play{border:0;border-radius:9px;padding:12px 16px;background:#6c7cff;color:white;cursor:pointer}.card{display:flex;gap:14px;align-items:center;background:#181e29;border-radius:12px;padding:10px;margin:9px 0}.card img{width:64px;height:64px;object-fit:cover;border-radius:7px}.meta{flex:1}.title{font-weight:650}.sub{color:#aeb8c8;font-size:13px;margin-top:4px}audio{width:100%;margin-top:22px}#status{color:#9fe3b1;min-height:22px}
</style></head><body><h1>Music Server</h1><p>Tìm nhạc từ YouTube Music và phát qua audio proxy của server.</p>
<div class="search"><input id="q" value="lofi" placeholder="Tên bài hát hoặc nghệ sĩ"><button onclick="search()">Tìm</button></div><div id="status"></div><div id="results"></div><audio id="player" controls></audio>
<script>const $=id=>document.getElementById(id); async function search(){let q=$("q").value.trim();if(!q)return;$("status").textContent="Đang tìm...";try{let r=await fetch('/api/search?q='+encodeURIComponent(q));if(!r.ok)throw Error(await r.text());let items=await r.json();$("results").innerHTML=items.map(t=>`<div class="card"><img src="${t.thumbnail||''}"><div class="meta"><div class="title">${esc(t.title)}</div><div class="sub">${esc((t.artists||[]).join(', '))} · ${t.duration||''}</div></div><button class="play" onclick="play('${t.videoId}',this)">▶</button></div>`).join('');$("status").textContent=items.length+' kết quả';}catch(e){$("status").textContent='Lỗi: '+e.message}}async function play(id,button){button.textContent='…';let p=$("player");p.pause();p.removeAttribute('src');p.load();p.src='/api/audio/'+id+'?play='+Date.now();p.onplaying=()=>button.textContent='▶';p.onerror=()=>{button.textContent='▶';$("status").textContent='Không phát được audio, hãy thử lại';};try{await p.play();}catch(e){button.textContent='▶';$("status").textContent='Trình duyệt chặn phát audio: '+e.message;}}function esc(s){return String(s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[c]))}search();</script></body></html>"""


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/search", response_model=list[Track])
async def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(default=20, ge=1, le=50)) -> list[Track]:
    return await asyncio.to_thread(_search_sync, q.strip(), limit)


@app.get("/stream_pcm", response_model=XiaozhiStreamResponse)
async def xiaozhi_stream_pcm(request: Request, song: str = Query(min_length=1, max_length=160), artist: str = Query(default="", max_length=160)) -> XiaozhiStreamResponse:
    """Xiaozhi-compatible search contract. The returned URL is MP3."""
    query = f"{song} {artist}".strip()
    tracks = await asyncio.to_thread(_search_sync, query, 1)
    if not tracks:
        return XiaozhiStreamResponse(title=song, artist=artist, audio_url="")
    track = tracks[0]
    base = public_base_url(request)
    return XiaozhiStreamResponse(
        title=track.title,
        artist=", ".join(track.artists) or artist,
        audio_url=f"{base}/stream/{track.videoId}.mp3",
        lyric_url="",
        video_id=track.videoId,
    )


@app.get("/api/stream/{video_id}", response_model=StreamResponse)
async def stream(video_id: str) -> StreamResponse:
    if len(video_id) < 6 or len(video_id) > 20 or not video_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="video_id không hợp lệ")
    return await asyncio.to_thread(_resolve_stream_sync, video_id)


@app.get("/api/audio/{video_id}")
async def audio(video_id: str, request: Request) -> StreamingResponse:
    """Proxy actual audio bytes so simple ESP32 HTTP clients can decode them."""
    if len(video_id) < 6 or len(video_id) > 20 or not video_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="video_id không hợp lệ")
    stream_info = await asyncio.to_thread(_resolve_stream_sync, video_id)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    try:
        upstream = await asyncio.to_thread(requests.get, stream_info.url, headers=headers, stream=True, timeout=20)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Không mở được audio stream: {exc}") from exc
    response_headers = {k: v for k, v in (("Content-Length", upstream.headers.get("Content-Length")), ("Content-Range", upstream.headers.get("Content-Range")), ("Accept-Ranges", upstream.headers.get("Accept-Ranges", "bytes")), ("Cache-Control", "no-store")) if v}
    codec = stream_info.mimeType or ""
    media_type = upstream.headers.get("Content-Type") or ("audio/mp4" if "mp4" in codec else "audio/mpeg")
    media_type = media_type.split(";")[0]
    def body():
        try:
            for chunk in upstream.iter_content(chunk_size=32 * 1024):
                if chunk:
                    yield chunk
        except requests.RequestException:
            # The browser/ESP32 may close a range request before the full
            # response finishes. Do not turn that normal disconnect into a
            # noisy ASGI 500 traceback.
            return
        finally:
            upstream.close()

    return StreamingResponse(body(), media_type=media_type, headers=response_headers, status_code=206 if upstream.status_code == 206 else 200)


def _mp3_body(video_id: str):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg chưa được cài trên server")
    info = _resolve_stream_sync(video_id)
    process = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", info.url, "-vn", "-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        for chunk in iter(lambda: process.stdout.read(32 * 1024), b""):
            yield chunk
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@app.get("/stream/{video_id}.mp3")
async def mp3_stream(video_id: str) -> StreamingResponse:
    """Transcode the provider stream to MP3 for XiaoZhi's libhelix-mp3."""
    if len(video_id) < 6 or len(video_id) > 20 or not video_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="video_id không hợp lệ")
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="MP3 stream cần FFmpeg trên server")
    return StreamingResponse(await asyncio.to_thread(lambda: _mp3_body(video_id)), media_type="audio/mpeg", headers={"Cache-Control": "no-store", "Accept-Ranges": "none"})
