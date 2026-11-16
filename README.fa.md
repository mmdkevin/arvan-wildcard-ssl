[فارسی](README.fa.md) · [English](README.md)

<div dir="rtl">

# گواهی Wildcard با آروان‌کلاد

با این اسکریپت می‌تونی روی اوبونتو از Let’s Encrypt گواهی Wildcard بگیری و تمدیدش رو با DNS آروان‌کلاد خودکار کنی. اسکریپت برای هر دامنه یک گواهی جدا می‌گیره و با چیدمان پیش‌فرض Docker پاسارگارد هم کار می‌کنه.

## نصب سریع

دستور زیر رو در ترمینال سرور اوبونتو اجرا کن.

<div dir="ltr">

```bash
curl -fsSL https://raw.githubusercontent.com/mmdkevin/arvan-wildcard-ssl/main/install.sh | bash
```

</div>

نصاب اسکریپت صدور گواهی رو دانلود می‌کنه و در صورت نیاز از `sudo` استفاده می‌کنه. قبل از اجرا می‌تونی فایل‌ها رو بررسی کنی. [نصاب](install.sh) · [اسکریپت صدور گواهی](arvan_ssl.py)

پیش‌نیازها

- سرور اوبونتو با `systemd` و `curl` و دسترسی `root` یا `sudo`. نصب خودکار برای معماری‌های AMD64 و ARM64 فعاله.
- دامنه‌هایی که DNS عمومی‌شون در آروان‌کلاد مدیریت می‌شه.
- کلید API آروان‌کلاد با مجوز ایجاد و حذف رکوردهای DNS برای دامنه‌ها. [پنل کلیدهای API آروان](https://npanel.arvancloud.ir/profile/api-keys)

بعد از شروع نصب، تعداد دامنه‌ها، نام هر دامنه و کلید API رو وارد کن. برای `example.com`، گواهی هم خود دامنه و هم `*.example.com` رو پوشش می‌ده. Wildcard یک سطح از زیردامنه‌ها رو پوشش می‌ده. اگر برای `api.dev.example.com` گواهی می‌خوای، `dev.example.com` رو هم جداگانه وارد کن.

صدور گواهی با چالش DNS-01 انجام می‌شه و تابع شرایط Let’s Encrypt هست. [راهنمای DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge) · [شرایط Let’s Encrypt](https://letsencrypt.org/repository/)

## مسیر گواهی‌ها

اسکریپت بعد از هر بررسی موفق، مسیر کامل فایل‌ها رو چاپ می‌کنه.

| نوع نصب | پوشهٔ گواهی برای `example.com` |
| --- | --- |
| اوبونتو با مسیر استاندارد | `/var/lib/arvan-wildcard/certs/example.com/` |
| نصب پیش‌فرض پاسارگارد | `/var/lib/pasarguard/arvan-certs/example.com/` |

فایل `fullchain.pem` زنجیرهٔ گواهی و `privkey.pem` کلید خصوصی TLS هست. بعد از تمدید هم از همین مسیرها استفاده کن.

## استفاده در اینباند TLS پاسارگارد

در نصب پیش‌فرض پاسارگارد، مسیر `/var/lib/pasarguard` از قبل به کانتینر وصل شده. برای انتقال گواهی‌های موجود از نسخهٔ قدیمی اسکریپت، نصاب رو دوباره اجرا کن و وقتی `Change the saved configuration?` رو دیدی، **Enter** بزن. [تنظیمات Docker پاسارگارد](https://github.com/PasarGuard/panel/blob/main/docker-compose.yml)

در تنظیمات هستهٔ اینباند، مقدار `streamSettings.security` رو روی `tls` بذار. این ورودی رو داخل آرایهٔ `streamSettings.tlsSettings.certificates` اضافه کن و به‌جای `example.com` نام دامنهٔ خودت رو بذار. [راهنمای تنظیم هستهٔ پاسارگارد](https://docs.pasarguard.org/fa/panel/core/)

<div dir="ltr">

```json
{
  "certificateFile": "/var/lib/pasarguard/arvan-certs/example.com/fullchain.pem",
  "keyFile": "/var/lib/pasarguard/arvan-certs/example.com/privkey.pem"
}
```

</div>

اگر اینباند روی نود جدا اجرا می‌شه، Xray روی همون نود باید بتونه هر دو فایل رو از مسیرهای تنظیم‌شده بخونه.

## تمدید خودکار

یک تایمر systemd هر روز همهٔ دامنه‌های ثبت‌شده رو بررسی می‌کنه. وقتی موعد تمدید برسه، اسکریپت فایل‌های تازه رو در همون مسیرها منتشر می‌کنه. زمان بارگذاری گواهی جدید به سرویس ارائه‌دهندهٔ TLS بستگی داره.

### وضعیت تایمر

<div dir="ltr">

```bash
systemctl list-timers arvan-wildcard-renew.timer
```

</div>

### گزارش تمدید

<div dir="ltr">

```bash
sudo journalctl -u arvan-wildcard-renew.service -n 50 --no-pager
```

</div>

برای توقف تمدید یک دامنه، کل پوشهٔ گواهی همون دامنه رو از مسیر مربوطه حذف کن. تایمر در بررسی‌های بعدی از اون دامنه عبور می‌کنه. برای اضافه‌کردن دوباره، نصاب رو اجرا کن، تغییر تنظیمات رو انتخاب کن و همهٔ دامنه‌هایی رو وارد کن که می‌خوای مدیریت بشن.

## کلید API و کلید خصوصی

ترمینال هنگام ورود کلید API اون رو نمایش نمی‌ده. نصاب کلید رو روی سرور در فایل `/etc/arvan-wildcard/config.json` ذخیره می‌کنه که فقط کاربر `root` بهش دسترسی داره. فایل تنظیمات و کلیدهای خصوصی رو خارج از Git نگه دار.

## رفع خطا

| مشکل | چه چیزی رو بررسی کنی |
| --- | --- |
| آروان‌کلاد درخواست DNS رو رد می‌کنه | مجوز مدیریت رکوردهای DNS کلید API رو برای هر دامنه بررسی کن. |
| چالش DNS در زمان تعیین‌شده کامل نمی‌شه | بررسی کن نام‌سرورهای معتبر دامنه به آروان‌کلاد اشاره کنن. گزارش تمدید مشخص می‌کنه کدوم دامنه خطا داده. |
| پاسارگارد فایل گواهی رو پیدا نمی‌کنه | مسیر اینباند رو با مسیر چاپ‌شده مقایسه کن و دسترسی به فایل رو از همون سرور یا کانتینری بررسی کن که Xray روش اجرا می‌شه. |

اگر مشکل حل نشد، نسخهٔ اوبونتو و بخش مربوط از گزارش خطا رو در یک Issue ثبت کن. قبل از انتشار گزارش، کلید API و محتوای کلید خصوصی رو ازش پاک کن. [ثبت Issue در GitHub](https://github.com/mmdkevin/arvan-wildcard-ssl/issues)

</div>
