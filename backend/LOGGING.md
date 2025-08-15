# Hướng dẫn sử dụng Logging System

## Tổng quan

Hệ thống logging đã được cải thiện để thay thế tất cả `print` statements bằng logging module với các level rõ ràng.

## Các Log Levels

- **DEBUG**: Thông tin chi tiết cho việc debug
- **INFO**: Thông tin chung về hoạt động của hệ thống
- **WARNING**: Cảnh báo về các vấn đề không nghiêm trọng
- **ERROR**: Lỗi nghiêm trọng cần xử lý

## Cách sử dụng

### 1. Chạy với log level mặc định (INFO)

```bash
# Chạy server
python app.py --mode server

# Chạy client
python app.py --mode client --file example.txt

# Chạy cả hai
python app.py --mode both --file example.txt
```

### 2. Thay đổi log level

```bash
# Chạy với DEBUG level (nhiều thông tin hơn)
python app.py --mode server --log-level DEBUG

# Chạy với ERROR level (chỉ lỗi)
python app.py --mode client --file example.txt --log-level ERROR
```

### 3. Lưu log vào file

```bash
# Lưu log vào file
python app.py --mode server --log-file logs/server.log

# Kết hợp log level và file
python app.py --mode both --file example.txt --log-level DEBUG --log-file logs/upload.log
```

## Cấu trúc Log

### Format Console
```
[HH:MM:SS] logger_name - LEVEL: message
```

### Format File
```
[YYYY-MM-DD HH:MM:SS] logger_name - LEVEL - function:line: message
```

## Ví dụ Log Output

### INFO Level (mặc định)
```
[14:30:15] server - INFO: WebSocket server listening on ws://localhost:8765
[14:30:20] server - INFO: Client connected from 127.0.0.1:12345 path=/ws
[14:30:25] server - INFO: Upload started: abc123 (example.txt), size=1024 bytes, offset=0
```

### DEBUG Level
```
[14:30:15] server - DEBUG: Connection registered: 127.0.0.1:12345
[14:30:25] server - DEBUG: Received action 'start' from 127.0.0.1:12345
[14:30:26] server - DEBUG: Chunk processed: abc123, offset=1024, chunk_size=1024, progress=100.0%
```

### ERROR Level
```
[14:30:30] server - ERROR: Failed to decode base64 data for abc123: Invalid base64 string
[14:30:31] server - ERROR: Sending error to client: Invalid base64 data
```

## Các Logger Components

1. **app**: Logger chính cho ứng dụng
2. **server**: Logger cho WebSocket server
3. **client**: Logger cho upload client

## Environment Variables

- `WS_HOST`: Host cho server (mặc định: localhost)
- `WS_PORT`: Port cho server (mặc định: 8765)
- `WS_URL`: WebSocket URL cho client (mặc định: ws://localhost:8765/ws)

## Troubleshooting

### Log quá nhiều thông tin
- Sử dụng `--log-level INFO` hoặc `--log-level ERROR`

### Không thấy log
- Kiểm tra log level có phù hợp không
- Kiểm tra quyền ghi file nếu sử dụng `--log-file`

### Log file quá lớn
- Xoay vòng log file định kỳ
- Sử dụng log level cao hơn để giảm thông tin
