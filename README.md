# Lightweight Music Server

API nhỏ lấy metadata từ YouTube Music và trả về URL audio tạm thời do YouTube cấp. Server không tải hoặc lưu file nhạc, nên phù hợp với Render free.

## Chạy local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

- `GET /health` — health check
- `GET /api/search?q=lofi&limit=20` — tìm bài hát
- `GET /api/stream/{videoId}` — lấy URL audio tạm thời
- `GET /api/audio/{videoId}` — proxy dữ liệu audio thật, dùng cho ESP32/Xiaozhi
- `GET /stream_pcm?song=...&artist=...` — contract tìm kiếm dành cho XiaoZhi
- `GET /stream/{videoId}.mp3` — chuyển mã và stream MP3 cho decoder `libhelix-mp3`
- `/docs` — Swagger UI

Mở `/` để dùng giao diện test tìm kiếm và phát nhạc trên trình duyệt. Với XiaoZhi ESP32, gọi `/stream_pcm?song=...&artist=...`, sau đó phát `audio_url`. Endpoint MP3 cần FFmpeg; `render.yaml` cài FFmpeg trong build.

## Deploy Render

1. Push thư mục này lên GitHub.
2. Trên Render chọn **New → Blueprint** và chọn repository.
3. Render sẽ đọc `render.yaml`; không cần database hay API key.

URL stream có thời hạn và client nên gọi lại endpoint stream khi hết hạn. Hãy chỉ sử dụng nội dung mà bạn có quyền truy cập; API này không vượt qua DRM hay tải nhạc xuống server.
