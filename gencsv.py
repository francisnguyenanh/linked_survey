import csv
import random
import itertools

def generate_fake_name():
    first_names = ["Mike", "Josh", "John", "David", "Emma", "Chris", "Alex", "Ryan", "Sarah", "Kevin"]
    last_names = ["Smith", "Johnson", "Brown", "Taylor", "Miller", "Wilson", "Anderson", "Thomas", "Moore"]
    middle_names = ["James", "Lee", "William", "Marie", "Ann"]
    
    # Random chọn tên có 2 hoặc 3 từ
    if random.choice([2, 3]) == 2:
        return f"{random.choice(first_names)} {random.choice(last_names)}"
    else:
        return f"{random.choice(first_names)} {random.choice(middle_names)} {random.choice(last_names)}"

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
    part2 = "".join([str(random.randint(0, 9)) for _ in range(4)])
    part3 = "".join([str(random.randint(0, 9)) for _ in range(4)])
    if use_dash:
        return f"070-{part2}-{part3}"
    else:
        return f"070{part2}{part3}"

def main():
    # Nhập thông tin đầu vào
    email_input = input("Nhập email gốc (vd: tomobedocuments@gmail.com): ")
    num_rows = int(input("Số lượng hàng muốn gen: "))
    show_dash = input("Có hiển thị dấu '-' trong số điện thoại không? (y/n): ").lower() == 'y'
    filename = "data/personas.csv"

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
        writer.writerow(["Tên", "Email (Dot Trick)", "Số điện thoại"])
        
        for i in range(num_rows):
            name = generate_fake_name()
            email = email_list[i]
            phone = generate_phone(show_dash)
            writer.writerow([name, email, phone])

    print(f"--- Đã gen xong {num_rows} hàng vào file {filename} ---")

if __name__ == "__main__":
    main()