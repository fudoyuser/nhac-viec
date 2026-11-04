# 📋 Nhắc việc

Website quản lý công việc cá nhân, tự gửi email nhắc tiến độ.

## Tính năng
**Website** (GitHub Pages, không cần đăng nhập)
- Thêm, sửa, xóa việc: nhóm, mức ưu tiên, deadline kèm giờ, ghi chú
- **Tích hết việc con chưa có nghĩa là xong việc chính** (vẫn có thể thêm việc con): bấm **✓ Xong cả việc** để hoàn tất
- **Việc con (checklist)**, mỗi việc con có deadline riêng (ngày + giờ 24h): tiến độ tự tính theo số mục đã tích; việc con trễ hạn sẽ đẩy cả việc lên mục quá hạn, hiện trên lịch và trong mail
- **Đo tiến độ bằng số lượng** (trang, tập, phút…): ví dụ 135/228 trang. Có ô gõ thẳng "đang ở trang mấy", nút +10 trang, và **nhịp độ cần đạt** (cần ~18 trang/ngày, đang chậm hay đúng tiến độ)
- **Phim nhiều tập**: theo dõi cả số tập đã xem lẫn phút đang xem dở của tập hiện tại; xem hết phút thì tự sang tập mới
- **Việc lặp lại** hằng ngày, tuần, tháng: bấm Xong là tự tạo kỳ tiếp theo
- Nút −10% / +10% / ✓ Xong (không còn thanh kéo dễ chạm nhầm khi cuộn)
- Lọc theo nhóm, tìm kiếm, sắp xếp (mức gấp, ưu tiên, deadline, tiến độ, tên)
- **Xem dạng lịch** theo tháng
- Cài như ứng dụng trên điện thoại: Chrome → menu → *Thêm vào màn hình chính*; Safari → Chia sẻ → *Thêm vào MH chính*
- Lưu lỗi thì màn hình tự trở về dữ liệu đã lưu; nếu 2 máy cùng sửa, website tự tải bản mới rồi lưu lại

**Tab 📝 Lịch thi** (tách riêng khỏi công việc)
- Mỗi môn: kỳ thi, ngày + giờ thi, thời lượng, phòng, SBD, hình thức, ghi chú đồ cần mang
- Đếm ngược tới môn thi tiếp theo; qua giờ thi tự chuyển sang **Đã thi** (không báo quá hạn) và có ô nhập điểm
- **Kế hoạch ôn tập**: tự chia N phần rải đều trước ngày thi, phần nào trễ báo đỏ
- **📋 Dán lịch**: dán bảng lịch thi (Môn · Ngày · Giờ · Phòng · SBD) từ Excel / trang trường, xem trước rồi thêm tất cả
- Email: mail 7h có mục lịch thi 14 ngày tới; mail các giờ khác nhắc môn thi hôm nay (chưa thi), từ 18h nhắc môn thi ngày mai; báo cáo tuần có lịch thi tuần tới

**Email** (GitHub Actions, 7h, 9h, 12h, 15h, 18h, 20h, 22h giờ VN)
- **7h sáng**: bản đầy đủ mọi việc chưa xong, chia theo mức gấp
- **Các giờ khác**: chỉ gửi khi có việc quá hạn hoặc hạn hôm nay
- **20h Chủ nhật**: báo cáo tuần (đã xong, quá hạn, tuần tới)
- Mỗi việc trong mail có nút **+25%** (hoặc *tích việc con tiếp theo*) và **✓ Xong**: bấm là cập nhật ngay

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
Actions → *Gửi mail nhắc việc* → Run workflow → chọn loại mail (full / urgent / weekly / auto).

## Tùy chỉnh
- **Giờ gửi mail**: sửa dòng `cron` trong `.github/workflows/reminder.yml` (giờ UTC = giờ VN − 7).
- **"Nhắc gấp trước (ngày)"** của từng việc: khi còn ≤ số ngày này, việc được đưa lên mục *Sắp đến hạn*.
- **Loại mail theo giờ**: sửa hàm `pick_mode` trong `scripts/send_reminder.py`.
- Việc có tiến độ 100% được coi là xong và không còn được nhắc.
- **Nhóm**: bấm 🗂 Nhóm để tạo, đổi tên, xóa nhóm. Khi thêm việc, chọn nhóm từ danh sách (website tự chọn sẵn nhóm dùng lần trước) hoặc chọn “+ Tạo nhóm mới…”.

## Lưu ý
- Ai có link website cũng xem và sửa được danh sách việc. Đừng chia sẻ link và đừng ghi thông tin nhạy cảm.
- Mỗi lần chạy, workflow gửi mail tự bật lại chính nó để GitHub không tắt lịch sau 60 ngày.
- Đổi token (`DATA_TOKEN`) thì phải chạy lại workflow *Dựng website*.
- Lịch của GitHub Actions có thể trễ vài phút đến vài chục phút lúc cao điểm.
