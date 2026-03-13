# Tracking Used Personas (implemented)

## Cách sử dụng tính năng đánh dấu người dùng đã sử dụng

### Bước 1: Chuẩn bị file personas.csv

Trước khi chạy lần đầu tiên, hãy thêm cột `used` vào file `personas.csv`:

```bash
python setup_personas_used_column.py
```

Script này sẽ:
- Kiểm tra xem file có cột `used` chưa
- Nếu chưa, thêm cột `used` với giá trị mặc định là `0` (chưa sử dụng) cho tất cả các dòng
- Hiển thị thông tin về số dòng đã sử dụng và chưa sử dụng

**Lưu ý:** Nếu bạn upload file CSV mới qua web interface, cột `used` sẽ **tự động được thêm** vào nếu không tồn tại.

### Bước 2: Chạy Bot

Khi chạy bot:
1. Vào trang `/run`
2. Bạn sẽ thấy thông tin: **"personas.csv — X/Y unused rows"**
   - `X` = số dòng chưa sử dụng
   - `Y` = tổng số dòng
3. Nhập số runs (không được vượt quá số dòng chưa sử dụng)
4. Nhấn **▶️ Start**

### Bước 3: Theo dõi trạng thái

Sau mỗi run:
- Nếu run **thành công** (Success) → dòng tương ứng sẽ được đánh dấu là `used = 1`
- Nếu run **bị lỗi** (Error) → dòng vẫn được đánh dấu là `used = 1` (tránh lặp lại)
- Nếu CSV **hết dòng chưa dùng** → bot sẽ dừng với status `csv_exhausted`

## Cấu trúc file personas.csv

Sau khi chuẩn bị, file sẽ có cấu trúc như sau:

```csv
name,email,phone,used
Emma Moore,to.mobedoc.um.ents@gmail.com,070-6976-6812,0
Chris Marie Thomas,t.omob.e.document.s@gmail.com,070-5876-6796,0
...
```

- `used = 0` → chưa sử dụng
- `used = 1` → đã sử dụng

## Các thay đổi trong code

### 1. `csv_manager.py`
- ✅ Tự động thêm cột `used` nếu không tồn tại trong file
- ✅ Lọc chỉ các dòng có `used = 0` khi lấy dữ liệu
- ✅ Thêm method `mark_as_used(row_index)` để đánh dấu dòng đã sử dụng
- ✅ Thêm method `unused_rows()` để lấy số dòng chưa sử dụng
- ✅ Updated `get_row()` để trả về index gốc của dòng

### 2. `bot.py`
- ✅ Thêm `persona_row_index` vào kết quả run
- ✅ Trích xuất `_row_index` từ persona dict

### 3. `app.py`
- ✅ Cập nhật logic validation để kiểm tra số dòng chưa sử dụng
- ✅ Thêm callback `_on_progress` để tự động gọi `mark_as_used` sau mỗi run
- ✅ Cập nhật `/run` endpoint để truyền `unused_rows` đến template

### 4. `templates/run.html`
- ✅ Hiển thị "X/Y unused rows" thay vì "X rows available"

## Ví dụ workflow

1. **Ban đầu:** File có 100 dòng, tất cả `used = 0`
2. **Chạy 10 runs:** 10 dòng được đánh dấu `used = 1`
3. **Lần chạy tiếp theo:** Chỉ có 90 dòng chưa sử dụng khả dụng
4. **Sau 100 runs:** Tất cả dòng được đánh dấu `used = 1`, bot sẽ dừng
5. **Reset:** Nếu muốn chạy lại, bạn có thể:
   - Sửa cột `used` thành `0` trong CSV
   - Hoặc upload file CSV mới

---

**Tóm tắt:** Chương trình sẽ tự động đánh dấu các dòng đã được sử dụng để tránh lặp lại dữ liệu trong các lần chạy sau. 🎯
