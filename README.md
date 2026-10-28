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
- `GET /api/audio/{videoId}` — proxy audio gốc, dành cho debug trình duyệt
- `GET /stream_pcm?song=...&artist=...` — contract tìm kiếm dành cho XiaoZhi
- `GET /stream/{videoId}.mp3` — chuyển mã và stream MP3 cho decoder `libhelix-mp3`
- `/docs` — Swagger UI

Mở `/` để dùng giao diện test tìm kiếm và phát nhạc trên trình duyệt. Với XiaoZhi ESP32, gọi `/stream_pcm?song=...&artist=...`, sau đó phát `audio_url`. Endpoint MP3 cần FFmpeg; Dockerfile cài FFmpeg trong image.

Server dùng các YouTube player client không cần cookie, ưu tiên `tv_embedded` để giảm lỗi bot check trên IP Render. Có thể đổi thứ tự bằng biến môi trường `YOUTUBE_PLAYER_CLIENTS`.

## Deploy Render

1. Push thư mục này lên GitHub.
2. Trên Render chọn **New → Blueprint** và chọn repository.
3. Render sẽ đọc `render.yaml`; không cần database hay API key.

Runtime phải là **Docker**. Không chạy `apt-get` trong Build Command của runtime Python vì filesystem hệ thống không cho ghi. Dockerfile cài FFmpeg khi build image và chạy ứng dụng bằng user không phải root.

Nếu service cũ dùng Python, tạo **New → Web Service** từ cùng repository, chọn **Docker**, gói **Free**, Dockerfile `./Dockerfile` và health check `/health`. Để Docker Command mặc định (dùng CMD trong Dockerfile). Không cần Build Command, Start Command hay PYTHON_VERSION. Sau khi service mới hoạt động, cập nhật URL trên ESP32.

URL stream có thời hạn và client nên gọi lại endpoint stream khi hết hạn. Hãy chỉ sử dụng nội dung mà bạn có quyền truy cập; API này không vượt qua DRM hay tải nhạc xuống server.
