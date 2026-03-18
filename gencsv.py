import csv
import random
import itertools

# Dữ liệu mẫu mở rộng
FIRST_NAMES = [
    "Mike", "Josh", "John", "David", "Emma", "Chris", "Alex", "Ryan", "Sarah", "Kevin",
    "Sophia", "Liam", "Noah", "Olivia", "Ethan", "Ava", "Lucas", "Mia", "Benjamin", "Zoe"
]

MIDDLE_NAMES = [
    "James", "Lee", "William", "Marie", "Ann", "Elizabeth", "Alexander", "Grace", "Michael", "Rose"
]

LAST_NAMES = [
    "Smith", "Johnson", "Brown", "Taylor", "Miller", "Wilson", "Anderson", "Thomas", "Moore",
    "Garcia", "Martinez", "Robinson", "Clark", "Rodriguez", "Lewis", "Walker", "Hall", "Young"
]

FIRST_NAMES_CN = [
    "Wei", "Fang", "Xiuying", "Li", "Min", "Jing", "Jun", "Qiang", "Tao", "Yan",
    "Hao", "Yi", "Mei", "Ling", "Fei", "Yang", "Xin", "Bo", "Lei", "Tian"
]

MIDDLE_NAMES_CN = [
    "Zhi", "Zhen", "Xiao", "Zi", "Wen", "Ru", "Shu", "Chun", "Hai", "Yue"
]

LAST_NAMES_CN = [
    "Wang", "Li", "Zhang", "Liu", "Chen", "Yang", "Huang", "Zhao", "Wu", "Zhou",
    "Xu", "Sun", "Ma", "Zhu", "Hu", "Lin", "Guo", "He", "Gao", "Luo"
]

FIRST_NAMES_VN = [
    "An", "Bình", "Chi", "Dũng", "Đức", "Hương", "Khoa", "Linh", "Minh", "Nam",
    "Phong", "Quân", "Sơn", "Thảo", "Trang", "Tuấn", "Vinh", "Xuân", "Yến", "Anh"
]

MIDDLE_NAMES_VN = [
    "Văn", "Thị", "Đình", "Ngọc", "Minh", "Hữu", "Thu", "Bảo", "Phương", "Hoàng"
]

LAST_NAMES_VN = [
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Phan", "Vũ", "Đặng", "Bùi", "Đỗ",
    "Hồ", "Ngô", "Dương", "Lý", "Vương", "Trịnh", "Trương", "Mai", "Đào", "Lâm"
]

FIRST_NAMES_KR = [
    "Min-jun", "Seo-jun", "Ha-joon", "Do-yun", "Ji-ho", "Seo-yeon", "Seo-yoon", "Ji-woo", "Ha-yoon", "Ji-yoo",
    "Eun-woo", "Si-woo", "Ji-a", "Da-in", "Ye-jun", "Joo-won", "So-yul", "Ha-rin", "Ji-an", "Seo-ah"
]

MIDDLE_NAMES_KR = [
    "Soo", "Hee", "Kyung", "Young", "Hyun", "Jae", "Sun", "Woo", "Min", "Ae"
]

LAST_NAMES_KR = [
    "Kim", "Lee", "Park", "Choi", "Jung", "Kang", "Cho", "Yoon", "Jang", "Lim",
    "Han", "Shin", "Oh", "Kwon", "Hwang", "Song", "An", "Hong", "Jeon", "Ko"
]

def generate_fake_name():
    first = random.choice(FIRST_NAMES_VN)
    last = random.choice(LAST_NAMES_VN)
    
    # Xác suất: 40% tên 2 chữ, 60% tên 3 chữ (tỉ lệ này giúp dữ liệu trông tự nhiên hơn)
    has_middle_name = random.random() > 0.4 
    
    if has_middle_name:
        middle = random.choice(MIDDLE_NAMES_VN)
        return f"{first} {middle} {last}"
    
    return f"{first} {last}"

def generate_dot_emails(email_goc, count):
    name, domain = email_goc.split('@')
    # Thuật toán chèn dấu chấm vào các vị trí ngẫu nhiên
    results = set()
    length = len(name)
    
    # Nếu tên quá ngắn, số lượng biến thể có thể ít hơn yêu cầu
    # Chúng ta sẽ thử tạo cho đến khi đủ số lượng hoặc hết khả năng
    attempts = 0
    while len(results) < count and attempts < count * 10:
        dot_position = random.randint(1, length - 1)
        # Tạo một biến thể ngẫu nhiên bằng cách chèn dấu chấm
        chars = list(name)
        num_dots = random.randint(1, length - 1)
        indices = random.sample(range(1, length), num_dots)
        for idx in sorted(indices, reverse=True):
            chars.insert(idx, '.')
        
        new_email = "".join(chars) + "@" + domain
        results.add(new_email)
        attempts += 1
        
    return list(results)

def generate_phone(use_dash=False):
    # Danh sách các đầu số theo yêu cầu
    prefixes = ["070", "080", "090"]
    prefix = random.choice(prefixes)
    
    # Tạo 8 chữ số ngẫu nhiên còn lại (chia làm 2 cụm, mỗi cụm 4 số)
    # k=4 nghĩa là lấy 4 phần tử ngẫu nhiên từ dải từ 0-9
    part2 = "".join(random.choices("0123456789", k=4))
    part3 = "".join(random.choices("0123456789", k=4))
    
    if use_dash:
        return f"{prefix}-{part2}-{part3}"
    else:
        return f"{prefix}{part2}{part3}"

def main():
    # Nhập thông tin đầu vào
    email_input = input("Nhập email gốc (vd: tomobedocuments@gmail.com): ")
    num_rows = int(input("Số lượng hàng muốn gen: "))
    show_dash = input("Có hiển thị dấu '-' trong số điện thoại không? (y/n): ").lower() == 'y'
    filename = "personas.csv"

    # Gen email trước vì đây là phần khó nhất để đảm bảo không trùng
    if '@' not in email_input or email_input.count('@') != 1:
        print("Email không hợp lệ. Vui lòng nhập lại theo định dạng example@gmail.com.")
        return
    email_list = generate_dot_emails(email_input, num_rows)
    
    # Nếu không đủ email biến thể, thông báo cho người dùng
    if len(email_list) < num_rows:
        print(f"Lưu ý: Chỉ tạo được {len(email_list)} biến thể email khác nhau từ tên này.")
        num_rows = len(email_list)

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["name", "email", "phone", "used"])
        
        for i in range(num_rows):
            name = generate_fake_name()
            email = email_list[i]
            phone = generate_phone(show_dash)
            writer.writerow([name, email, phone, 0])

    print(f"--- Đã gen xong {num_rows} hàng vào file {filename} ---")

if __name__ == "__main__":
    main()