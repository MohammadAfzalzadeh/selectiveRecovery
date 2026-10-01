-- ۱. جدول کاربران (بدون خرابی در آینده)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50),
    created_at TIMESTAMP DEFAULT now()
);

-- ۲. جدول کیف پول‌ها (فقط حذف داده در آینده)
CREATE TABLE wallets (
    id SERIAL PRIMARY KEY,
    user_id INT,
    balance DECIMAL,
    updated_at TIMESTAMP DEFAULT now()
);

-- ۳. جدول پرداخت‌ها (حذف و آپدیت اشتباه در آینده)
CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    user_id INT,
    amount DECIMAL,
    status VARCHAR(20),
    created_at TIMESTAMP DEFAULT now()
);

-- ۴. جدول کدهای تخفیف (حذف، آپدیت و درج رکوردهای کثیف/غیرمنطقی در آینده)
CREATE TABLE discount_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50),
    discount_percent INT, -- از نظر منطقی نباید بالای 100 یا منفی باشد
    is_active BOOLEAN DEFAULT TRUE
);

-- تزریق داده‌های حجیم (Bulk Insert)
INSERT INTO users (username) 
SELECT 'user_' || i FROM generate_series(1, 10000) i;

INSERT INTO wallets (user_id, balance) 
SELECT i, (random() * 5000000)::int FROM generate_series(1, 10000) i;

INSERT INTO payments (user_id, amount, status) 
SELECT (random() * 9999 + 1)::int, (random() * 1000000)::int, 'SUCCESS' 
FROM generate_series(1, 50000);

INSERT INTO discount_codes (code, discount_percent) 
SELECT 'YALDA_' || i, (random() * 40 + 10)::int 
FROM generate_series(1, 20000) i;

-- نمایش زمان فعلی سیستم (این زمان را حتماً کپی کن - این لحظه قبل از حادثه است)
SELECT now();

              now              
-------------------------------
 2026-09-30 20:35:22.871992+00
(1 row)


------------
------------
--شبیه سازی حادثه 
------------
------------
BEGIN;

-- جدول wallets: فقط حذف ۱۰۰ رکورد به اشتباه
DELETE FROM wallets WHERE id BETWEEN 4500 AND 4600;

-- جدول payments: حذف ۵۰۰ رکورد و صفر کردن مبلغ ۲۰۰۰ تراکنش موفق به اشتباه
DELETE FROM payments WHERE id BETWEEN 15000 AND 15500;
UPDATE payments SET amount = 0, status = 'FAILED' WHERE id BETWEEN 30000 AND 32000;

-- جدول discount_codes: حذف، آپدیت اشتباه و درج دیتای کثیف و غیرمنطقی
DELETE FROM discount_codes WHERE id BETWEEN 8000 AND 8500;
UPDATE discount_codes SET discount_percent = 0, is_active = FALSE WHERE id BETWEEN 12000 AND 12500;
-- درج رکوردهایی که از نظر شمای دیتابیس معتبرند اما از نظر بیزینسی کثیف و غیرمنطقی هستند (درصد تخفیف ۹۹۹ و منفی)
INSERT INTO discount_codes (code, discount_percent, is_active) VALUES 
('BUG_1', 999, TRUE),
('BUG_2', -50, TRUE),
('BUG_3', 5000, FALSE);

COMMIT;


SELECT * FROM discount_codes WHERE id BETWEEN 12000 AND 12500

-----------
-----------
--داده های درست 
------------
------------
-- تراکنش‌های سالم و جدید (Create)
INSERT INTO payments (user_id, amount, status) VALUES 
(101, 750000, 'PENDING'),
(505, 120000, 'SUCCESS'),
(999, 45000, 'FAILED');

INSERT INTO discount_codes (code, discount_percent) VALUES ('NOROUZ_NEW', 25);
INSERT INTO users (username) VALUES ('new_real_user_1');

-- آپدیت‌های سالم و روزمره (Update)
UPDATE wallets SET balance = balance - 750000 WHERE user_id = 101;
UPDATE payments SET status = 'SUCCESS' WHERE id = 50000; -- آخرین رکورد جدول قبل از حادثه

-- حذف‌های سالم توسط کاربران (Delete)
DELETE FROM users WHERE id = 9999;