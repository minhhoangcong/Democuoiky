# FlexTransfer Hub

Ứng dụng quản lý chuyển file chuyên nghiệp với các tính năng nâng cao.

## Tính năng

- **Upload file**: Kéo thả hoặc chọn file để upload
- **Multi-file upload**: Upload nhiều files cùng lúc với concurrency control
- **Folder upload**: Upload toàn bộ folder, hỗ trợ duyệt đệ quy subfolder
- **Download từ URL**: Thêm URL trực tiếp để download
- **Quản lý transfer**: Theo dõi tiến trình, tạm dừng, hủy bỏ
- **Giao diện hiện đại**: Thiết kế tối với UX tốt
- **Responsive**: Hoạt động tốt trên mọi thiết bị
- **Thống kê real-time**: Hiển thị số lượng transfer, tốc độ tổng
- **Logging system**: Hệ thống logging chuyên nghiệp với các level rõ ràng

## Cách sử dụng

### 1. Chạy ứng dụng

Mở file `frontend/index.html` trong trình duyệt web hoặc sử dụng local server:

```bash
# Sử dụng Python
cd frontend
python -m http.server 8000

# Sử dụng Node.js
cd frontend
npx serve .

# Sử dụng PHP
cd frontend
php -S localhost:8000
```

### 2. Upload file

- **Kéo thả**: Kéo file từ máy tính vào vùng dropzone
- **Chọn file**: Click vào "browse files" để chọn file từ máy tính
- **Hỗ trợ**: Tất cả các loại file

### 3. Download từ URL

- Nhập URL trực tiếp vào ô "Add Download URL"
- Click "Add" hoặc nhấn Enter
- URL phải là link download trực tiếp

### 4. Quản lý transfer

- **Xem tiến trình**: Theo dõi % hoàn thành và tốc độ
- **Tạm dừng**: Click nút pause để tạm dừng/tiếp tục
- **Hủy bỏ**: Click nút cancel để xóa transfer
- **Lọc**: Sử dụng tabs để xem All/Uploads/Downloads

### 5. Thống kê

- **Active Transfers**: Số transfer đang hoạt động
- **Completed**: Số transfer đã hoàn thành
- **Total Files**: Tổng số file đã thêm
- **Total Speed**: Tốc độ tổng hiện tại

## Cấu trúc file

```
frontend/
├── index.html          # File HTML chính
├── style.css           # CSS styles
└── script.js           # JavaScript logic
```

## Tính năng kỹ thuật

### Backend (Python)

- **WebSocket server**: Xử lý upload file real-time
- **Async/await**: Sử dụng asyncio cho hiệu suất cao
- **Multi-file upload**: Hỗ trợ upload nhiều files cùng lúc với concurrency control
- **Folder upload**: Upload toàn bộ folder, hỗ trợ duyệt đệ quy subfolder
- **Resume upload**: Hỗ trợ tiếp tục upload khi bị gián đoạn
- **Concurrency management**: Semaphore-based throttling để tối ưu hiệu suất
- **Logging system**: Hệ thống logging chuyên nghiệp với các level:
  - **DEBUG**: Thông tin chi tiết cho debug
  - **INFO**: Thông tin hoạt động chung
  - **WARNING**: Cảnh báo vấn đề không nghiêm trọng
  - **ERROR**: Lỗi nghiêm trọng cần xử lý
- **Command line options**: Hỗ trợ `--log-level`, `--log-file`, `--file`, `--dir`, `--recursive`, `--concurrency`
- **Modular architecture**: Tách biệt server, client và logging

### JavaScript (script.js)

- **Class-based architecture**: Sử dụng ES6 classes
- **Event handling**: Drag & drop, file selection, form submission
- **Real-time updates**: Progress tracking, status updates
- **Error handling**: Validation, notifications
- **Modular design**: Dễ mở rộng và bảo trì

### CSS (style.css)

- **Modern design**: Dark theme với accent colors
- **Responsive**: Mobile-first approach
- **Animations**: Smooth transitions và hover effects
- **Accessibility**: ARIA labels, keyboard navigation

### HTML (index.html)

- **Semantic markup**: Proper HTML5 structure
- **Accessibility**: ARIA attributes, screen reader support
- **SEO friendly**: Meta tags, proper headings

## Tùy chỉnh

### Thay đổi theme

Chỉnh sửa các biến CSS trong `style.css`:

```css
/* Dark theme colors */
--bg-primary: #0e1014;
--bg-secondary: #16181e;
--text-primary: #e3e5e8;
--text-secondary: #6a6f7a;
--accent: #3391ff;
```

### Thêm tính năng mới

1. Mở `script.js`
2. Thêm method mới vào class `FlexTransferHub`
3. Cập nhật HTML nếu cần
4. Thêm CSS styles tương ứng

## Browser Support

- Chrome 60+
- Firefox 55+
- Safari 12+
- Edge 79+

## License

MIT License - Tự do sử dụng và chỉnh sửa.

## Contributing

1. Fork repository
2. Tạo feature branch
3. Commit changes
4. Push to branch
5. Tạo Pull Request

## Support

Nếu gặp vấn đề, vui lòng tạo issue trên GitHub hoặc liên hệ team phát triển. 