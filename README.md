# 📋 Nhắc việc

Website quản lý công việc cá nhân, tự gửi email nhắc tiến độ mỗi ngày.

- **Website** (GitHub Pages): thêm, sửa, xóa việc, kéo thanh tiến độ. Dữ liệu lưu trong `tasks.json`.
- **Email** (GitHub Actions): 7:05 sáng và 20:05 tối (giờ VN), gửi danh sách việc quá hạn, đến hạn hôm nay, sắp đến hạn và đang theo dõi.

## Cài đặt (một lần)

### 1. Tạo App Password cho Gmail
1. Bật xác minh 2 bước: https://myaccount.google.com/security
2. Tạo App Password: https://myaccount.google.com/apppasswords. Đặt tên tùy ý và copy mã 16 ký tự.

### 2. Thêm Secrets vào repo
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Tên | Giá trị |
|---|---|
| `GMAIL_USER` | địa chỉ Gmail của bạn |
| `GMAIL_APP_PASSWORD` | mã 16 ký tự ở bước 1 |
| `MAIL_TO` | (tùy chọn) địa chỉ nhận, bỏ trống thì gửi về `GMAIL_USER` |

### 3. Bật GitHub Pages
Repo → **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, thư mục `/ (root)` → Save.
Website sẽ ở `https://<owner>.github.io/<repo>/`.

### 4. Tạo token để website lưu được dữ liệu
GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Repository access: *Only select repositories*, chọn repo này
- Permissions: **Contents: Read and write**

Mở website → ⚙️ Cài đặt → dán token → Lưu. Token chỉ nằm trong trình duyệt của bạn.

### 5. Gửi thử
Repo → **Actions → Gửi mail nhắc việc → Run workflow**.

## Tùy chỉnh
- **Giờ gửi mail**: sửa các dòng `cron` trong `.github/workflows/reminder.yml` (giờ UTC = giờ VN − 7).
- **"Nhắc gấp trước (ngày)"** của từng việc: khi còn ≤ số ngày này, việc được đưa lên mục *Sắp đến hạn*.
- Việc có tiến độ 100% được coi là xong và không còn được nhắc.

## Lưu ý
- Repo public thì ai cũng xem được `tasks.json`. Đừng ghi thông tin nhạy cảm.
- Nếu repo không có commit nào trong 60 ngày, GitHub tự tắt lịch chạy. Lúc đó vào tab Actions bấm *Enable workflow* (mỗi lần lưu trên website đã tính là một commit).
- Lịch của GitHub Actions có thể trễ vài phút đến vài chục phút lúc cao điểm.
