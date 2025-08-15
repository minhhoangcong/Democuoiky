# Hướng dẫn Multi-File Upload và Folder Upload

## Tổng quan

FlexTransfer Hub đã được nâng cấp để hỗ trợ upload nhiều files cùng lúc và upload cả folder với các tính năng mạnh mẽ.

## Tính năng mới

### 1. **Multi-File Upload**
- Upload nhiều files cùng lúc
- Concurrency control để tối ưu hiệu suất
- Progress tracking cho từng file
- Error handling và retry logic

### 2. **Folder Upload**
- Upload toàn bộ folder
- Hỗ trợ duyệt đệ quy subfolder
- Tự động scan và thu thập files
- Loại bỏ duplicate files

### 3. **Concurrency Control**
- Giới hạn số lượng upload đồng thời
- Semaphore-based throttling
- Tối ưu cho network bandwidth

## Cách sử dụng

### **Upload nhiều files cụ thể**

```bash
# Upload 3 files cụ thể
python app.py --mode client --file file1.txt file2.pdf file3.jpg

# Upload với concurrency cao hơn
python app.py --mode client --file file1.txt file2.pdf file3.jpg --concurrency 5

# Upload với chunk size tùy chỉnh
python app.py --mode client --file file1.txt file2.pdf --chunk 128000
```

### **Upload folder**

```bash
# Upload folder hiện tại (không duyệt subfolder)
python app.py --mode client --dir ./documents

# Upload folder với duyệt đệ quy subfolder
python app.py --mode client --dir ./documents --recursive

# Upload nhiều folder cùng lúc
python app.py --mode client --dir ./documents ./images ./videos

# Upload folder với concurrency cao
python app.py --mode client --dir ./documents --concurrency 8
```

### **Kết hợp files và folders**

```bash
# Upload cả files cụ thể và folders
python app.py --mode client \
  --file important.txt backup.pdf \
  --dir ./documents ./images \
  --recursive

# Upload với logging chi tiết
python app.py --mode client \
  --file file1.txt file2.txt \
  --dir ./folder1 ./folder2 \
  --log-level DEBUG \
  --log-file upload.log
```

### **Chạy cả server và client**

```bash
# Upload folder khi chạy cả server và client
python app.py --mode both \
  --dir ./uploads \
  --recursive \
  --concurrency 4

# Upload nhiều files với server tùy chỉnh
python app.py --mode both \
  --host 0.0.0.0 \
  --port 8766 \
  --file file1.txt file2.txt \
  --dir ./documents
```

## Command Line Options

### **File và Folder Options**
- `--file PATH [PATH ...]`: Chỉ định files cụ thể để upload
- `--dir PATH [PATH ...]`: Chỉ định folders để upload
- `--recursive`: Duyệt đệ quy vào subfolder khi upload folder

### **Upload Control Options**
- `--concurrency N`: Số lượng upload đồng thời (mặc định: 2)
- `--chunk SIZE`: Kích thước chunk trong bytes (mặc định: 64KB)
- `--interactive`: Chế độ interactive (chỉ hỗ trợ single file)

### **Server Options**
- `--host HOST`: Host cho server (mặc định: localhost)
- `--port PORT`: Port cho server (mặc định: 8765)
- `--ws URL`: WebSocket URL cho client

### **Logging Options**
- `--log-level LEVEL`: Log level (DEBUG, INFO, WARNING, ERROR)
- `--log-file PATH`: Lưu log vào file

## Ví dụ thực tế

### **Upload project folder**
```bash
# Upload toàn bộ project với subfolder
python app.py --mode client \
  --dir ./my-project \
  --recursive \
  --concurrency 6 \
  --log-level INFO
```

### **Backup nhiều folders**
```bash
# Backup documents, images, và videos
python app.py --mode client \
  --dir ./documents ./images ./videos \
  --recursive \
  --concurrency 4 \
  --log-file backup.log
```

### **Upload với server remote**
```bash
# Upload files lên server remote
python app.py --mode client \
  --ws ws://192.168.1.100:8765/ws \
  --file important.txt backup.pdf \
  --dir ./documents \
  --concurrency 8
```

## Performance Tips

### **Concurrency Optimization**
- **Network tốt**: Sử dụng `--concurrency 8-16`
- **Network chậm**: Sử dụng `--concurrency 2-4`
- **Server yếu**: Giới hạn `--concurrency 2-4`

### **Chunk Size Optimization**
- **Files nhỏ**: `--chunk 32768` (32KB)
- **Files lớn**: `--chunk 131072` (128KB)
- **Network chậm**: `--chunk 32768` (32KB)

### **Memory Usage**
- Mỗi concurrent upload sử dụng ~1-2MB RAM
- Với 1000 files, cần ~2-4GB RAM cho concurrency cao

## Error Handling

### **Common Issues**
1. **File không tồn tại**: Sẽ được skip và log warning
2. **Permission denied**: Sẽ được skip và log error
3. **Network timeout**: Sẽ retry tự động
4. **Disk full**: Sẽ dừng và log error

### **Recovery**
- Upload sẽ tiếp tục với các files còn lại
- Failed files được liệt kê trong summary
- Có thể retry failed files riêng lẻ

## Logging và Monitoring

### **Progress Tracking**
```
[14:30:15] app - INFO: Starting multi-file upload: 150 files
[14:30:16] client - INFO: Progress: 5/150 files completed (3.3%)
[14:30:17] client - INFO: Progress: 12/150 files completed (8.0%)
[14:30:18] client - INFO: Progress: 25/150 files completed (16.7%)
...
[14:35:20] client - INFO: Batch upload completed: 148/150 files successful
[14:35:20] client - WARNING: Failed files (2):
[14:35:20] client - WARNING:   - /path/to/corrupted/file1.txt
[14:35:20] client - WARNING:   - /path/to/permission/file2.pdf
```

### **Performance Metrics**
- Tổng thời gian upload
- Tốc độ trung bình
- Success rate
- Failed files list

## Troubleshooting

### **Upload chậm**
- Tăng `--concurrency`
- Giảm `--chunk` size
- Kiểm tra network bandwidth

### **Memory issues**
- Giảm `--concurrency`
- Kiểm tra available RAM
- Sử dụng `--log-level ERROR` để giảm log

### **Network errors**
- Kiểm tra WebSocket connection
- Giảm `--concurrency`
- Tăng timeout settings

## Best Practices

1. **Test với ít files trước**: Bắt đầu với 5-10 files
2. **Monitor system resources**: Kiểm tra CPU, RAM, network
3. **Use appropriate concurrency**: Không quá cao so với network capacity
4. **Log everything**: Sử dụng `--log-file` cho production
5. **Handle failures gracefully**: Luôn có backup plan
