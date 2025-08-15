# Backend WebSocket Server (Python)

Server WebSocket hỗ trợ upload file với các thao tác: start, chunk, pause, resume, stop, complete và resume theo offset.

## Cài đặt

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell
pip install -r requirements.txt
```

## Chạy server

```bash
python server.py
```

Server mặc định chạy tại `ws://localhost:8765`.

Thiết lập qua biến môi trường:

- `WS_HOST` (default: `localhost`)
- `WS_PORT` (default: `8765`)

## Client asynchronous (client.py)

Client Python async để upload/pause/resume/stop qua WebSocket.

### Chạy client

```bash
# Upload file với cấu hình mặc định
python client.py "D:/path/to/file.zip"

# Tùy chỉnh WS URL và chunk size
python client.py "D:/path/to/file.zip" --ws ws://localhost:8765/ws --chunk 131072

# Truyền sẵn file id (để resume đồng bộ giữa nhiều lần chạy)
python client.py "D:/path/to/file.zip" --id my-file-id-123
```

### Phím tắt trong client (interactive)

- `p`: pause
- `r`: resume
- `s`: stop (xóa phần `.part` ở server nếu `delete=True`)
- `q`: quit (gửi stop `delete=False` rồi thoát)

## Giao thức WebSocket

Client gửi/nhận JSON theo các sự kiện sau:

### 1) Start

Client -> Server
```json
{
  "action": "start",
  "fileId": "unique-id",
  "fileName": "example.zip",
  "fileSize": 12345678
}
```
Server -> Client
```json
{
  "event": "start-ack",
  "fileId": "unique-id",
  "offset": 0,
  "status": "active"
}
```

### 2) Chunk

Client -> Server
```json
{
  "action": "chunk",
  "fileId": "unique-id",
  "offset": 0,
  "data": "<base64>"  
}
```
Server -> Client
```json
{
  "event": "progress",
  "fileId": "unique-id",
  "offset": 65536,
  "receivedBytes": 65536,
  "percent": 12.34
}
```
Nếu offset không khớp, server trả lời:
```json
{
  "event": "offset-mismatch",
  "fileId": "unique-id",
  "expected": 65536,
  "received": 0
}
```

### 3) Pause

Client -> Server
```json
{"action": "pause", "fileId": "unique-id"}
```
Server -> Client
```json
{"event": "pause-ack", "fileId": "unique-id", "offset": 65536}
```

### 4) Resume

Client -> Server
```json
{"action": "resume", "fileId": "unique-id"}
```
Server -> Client
```json
{"event": "resume-ack", "fileId": "unique-id", "offset": 65536}
```

### 5) Stop

Client -> Server
```json
{"action": "stop", "fileId": "unique-id", "delete": true}
```
Server -> Client
```json
{"event": "stop-ack", "fileId": "unique-id"}
```

### 6) Complete

Client -> Server
```json
{"action": "complete", "fileId": "unique-id"}
```
Server -> Client
```json
{
  "event": "complete-ack",
  "fileId": "unique-id",
  "filePath": "D:/path/to/uploads/example.zip"
}
```

### 7) Error

Server -> Client (bất kỳ lỗi nào)
```json
{"event": "error", "fileId": "unique-id", "error": "Reason"}
```

## Thư mục lưu file

Mặc định lưu tại `backend/uploads`. File trong tiến trình sẽ có đuôi `.part`. Khi hoàn tất sẽ đổi tên thành file cuối.

## Lưu ý

- `client.py` dùng asynchronous I/O (`asyncio`) và chạy song song luồng nhận WebSocket để phản hồi tiến trình nhanh.
- Có thể điều chỉnh `--chunk` để thay đổi kích thước chunk.
- Khi `stop(delete=True)` server sẽ xóa file `.part`.