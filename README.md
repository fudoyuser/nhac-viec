# 📋 Nhắc việc

Website quản lý công việc cá nhân, tự gửi email nhắc tiến độ mỗi ngày.

- **Website** (GitHub Pages): thêm, sửa, xóa việc, kéo thanh tiến độ. Dữ liệu lưu trong `tasks.json`.
- **Email** (GitHub Actions): 7:05 sáng và 20:05 tối (giờ VN), gửi danh sách việc quá hạn, đến hạn hôm nay, sắp đến hạn và đang theo dõi.

## Cách lưu dữ liệu
- Danh sách việc nằm trong `tasks.json` của repo **private** `<repo>-data` (ví dụ `nhac-viec-data`).
- Website không cần đăng nhập. Token có quyền ghi **chỉ vào repo dữ liệu** được GitHub Actions chèn vào trang lúc dựng (secret `DATA_TOKEN`), không nằm trong code.
- Ai có link website đều sửa được danh sách việc, nhưng không đụng được code hay mật khẩu Gmail.

## Cài đặt (một lần)

### 1. Tạo repo dữ liệu
Tạo repo **private** tên `<tên repo này>-data`, ví dụ `nhac-viec-data`, và tích *Add a README file*.

### 2. Tạo token cho repo dữ liệu
GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token
- Repository access: *Only select repositories* → **chỉ chọn `nhac-viec-data`**
- Permissions → Repository permissions → **Contents: Read and write**

### 3. Thêm Secrets vào repo này
Settings → Secrets and variables → Actions → New repository secret:

| Tên | Giá trị |
|---|---|
| `GMAIL_USER` | địa chỉ Gmail gửi mail |
| `GMAIL_APP_PASSWORD` | App Password 16 chữ cái (https://myaccount.google.com/apppasswords, cần bật xác minh 2 bước) |
| `DATA_TOKEN` | token ở bước 2 |
| `MAIL_TO` | (tùy chọn) địa chỉ nhận, bỏ trống thì gửi về `GMAIL_USER` |

### 4. Bật GitHub Pages
Settings → Pages → Source: **GitHub Actions**. Sau đó vào tab Actions → *Dựng website* → Run workflow.

### 5. Gửi thử
Actions → *Gửi mail nhắc việc* → Run workflow.

## Tùy chỉnh
- **Giờ gửi mail**: sửa các dòng `cron` trong `.github/workflows/reminder.yml` (giờ UTC = giờ VN − 7).
- **"Nhắc gấp trước (ngày)"** của từng việc: khi còn ≤ số ngày này, việc được đưa lên mục *Sắp đến hạn*.
- Việc có tiến độ 100% được coi là xong và không còn được nhắc.

## Lưu ý
- Ai có link website cũng xem và sửa được danh sách việc. Đừng chia sẻ link và đừng ghi thông tin nhạy cảm.
- Mỗi lần chạy, workflow gửi mail tự bật lại chính nó để GitHub không tắt lịch sau 60 ngày.
- Đổi token (`DATA_TOKEN`) thì phải chạy lại workflow *Dựng website*.
- Lịch của GitHub Actions có thể trễ vài phút đến vài chục phút lúc cao điểm.
