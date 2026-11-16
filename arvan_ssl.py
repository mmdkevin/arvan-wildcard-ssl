#!/usr/bin/env python3
"""Interactive ArvanCloud wildcard certificates and automatic renewal on Ubuntu."""

import argparse
import fcntl
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen


STATE = Path("/var/lib/arvan-wildcard")
CONFIG = Path("/etc/arvan-wildcard/config.json")
INSTALL = Path("/usr/local/lib/arvan-wildcard")
UNITS = Path("/etc/systemd/system")
SYSTEMCTL = "/usr/bin/systemctl"
UNIT = "arvan-wildcard-renew"
VERSION = "5.6.0"
ARCHIVES = {
    "x86_64": ("amd64", "f02fc11b6f56b97e387fa7caa0268f86f5a336953b22458e6430e4651fea439a"),
    "aarch64": ("arm64", "34d87a6552d69390c4a4560237045c47713a8e148d899e16db0e97040894ed1f"),
}
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
WEB_SERVICES = {"1": "nginx.service", "2": "apache2.service"}
CERT_FILES = {"fullchain.pem": "wildcard.crt", "privkey.pem": "wildcard.key"}


def write_atomic(path, data, mode=0o600):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        pending = Path(temp.name)
        try:
            os.fchmod(temp.fileno(), mode)
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
            temp.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def parse_domain(raw):
    name = raw.strip().lower()
    if name.startswith("*."):
        name = name[2:]
    try:
        name = name.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError as exc:
        raise ValueError("نام دامنه معتبر نیست.") from exc
    labels = name.split(".")
    if (len(name) > 251 or len(labels) < 2 or labels[-1].isdigit()
            or any(not LABEL.fullmatch(label) for label in labels)):
        raise ValueError("فقط نام دامنه وارد کن، مثل example.com.")
    return name


def ask_yes(prompt, default):
    suffix = " [Y/n] " if default else " [y/N] "
    while True:
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "بله", "آره"):
            return True
        if answer in ("n", "no", "نه", "خیر"):
            return False
        print("y یا n وارد کن.")


def ask_config():
    while True:
        value = input("برای چند دامنه گواهی می‌خواهی؟ ").strip()
        if value.isdecimal() and len(value) < 10 and int(value) > 0:
            count = int(value)
            break
        print("یک عدد بزرگ‌تر از صفر وارد کن.")

    domains = []
    while len(domains) < count:
        try:
            name = parse_domain(input(f"آدرس دامنهٔ {len(domains) + 1}: "))
            if name in domains:
                raise ValueError("این دامنه را قبلاً وارد کردی.")
            domains.append(name)
        except ValueError as exc:
            print(exc)

    apex = ask_yes("دامنهٔ اصلی هم همراه Wildcard پوشش داده شود؟", True)
    while True:
        email = input("ایمیل حساب Let's Encrypt: ").strip()
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            break
        print("یک ایمیل معتبر وارد کن.")

    while True:
        value = getpass.getpass("کلید API آروان برای این دامنه‌ها: ").strip()
        token = re.sub(r"^apikey\s+", "", value, flags=re.IGNORECASE)
        if re.fullmatch(r"[\x21-\x7e]+", token) and token.lower() != "apikey":
            break
        print("کلید API آروان را وارد کن.")

    while True:
        choice = input("بارگذاری گواهی جدید بعد از تمدید: [0] هیچ‌کدام [1] Nginx [2] Apache (0): ").strip() or "0"
        if choice == "0" or choice in WEB_SERVICES:
            break
        print("۰، ۱ یا ۲ را به انگلیسی وارد کن.")

    print("شرایط Let's Encrypt: https://letsencrypt.org/repository/")
    if not ask_yes("شرایط صدور گواهی را می‌پذیری؟", False):
        raise ValueError("راه‌اندازی لغو شد.")

    return {"domains": domains, "include_apex": apex, "email": email,
            "token": token, "web_service": WEB_SERVICES.get(choice)}


def install_lego():
    machine = platform.machine()
    if machine not in ARCHIVES:
        raise ValueError("نصب خودکار برای معماری‌های amd64 و arm64 اوبونتو آماده شده است.")
    arch, sha256 = ARCHIVES[machine]
    binary = INSTALL / f"lego-{VERSION}"
    if binary.is_file() and os.access(binary, os.X_OK):
        return binary
    print(f"در حال نصب lego {VERSION} …", flush=True)
    asset = f"lego_v{VERSION}_linux_{arch}.tar.gz"
    url = f"https://github.com/go-acme/lego/releases/download/v{VERSION}/{asset}"
    install_limit = 32 * 1024 * 1024
    with urlopen(url, timeout=60) as response:
        content = response.read(install_limit + 1)
    if len(content) > install_limit or hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError("SHA-256 بستهٔ lego با نسخهٔ رسمی مطابقت ندارد.")
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        member = archive.getmember("lego")
        if not member.isfile():
            raise ValueError("باینری lego در بستهٔ رسمی پیدا نشد.")
        with archive.extractfile(member) as binary_stream:
            write_atomic(binary, binary_stream.read(), 0o755)
    return binary


def install_timer():
    script = INSTALL / "arvan_ssl.py"
    write_atomic(script, Path(__file__).read_bytes(), 0o644)
    service = f"""[Unit]
Description=Check and renew ArvanCloud wildcard TLS certificates
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
UMask=0077
TimeoutStartSec=2h
ExecStart=/usr/bin/python3 -I {script} --renew
"""
    timer = """[Unit]
Description=Daily check for ArvanCloud wildcard TLS renewals

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
"""
    write_atomic(UNITS / f"{UNIT}.service", service.encode(), 0o644)
    write_atomic(UNITS / f"{UNIT}.timer", timer.encode(), 0o644)
    subprocess.run([SYSTEMCTL, "daemon-reload"], check=True)
    subprocess.run([SYSTEMCTL, "enable", "--now", f"{UNIT}.timer"], check=True)
    subprocess.run([SYSTEMCTL, "is-active", "--quiet", f"{UNIT}.timer"], check=True)


def publish(domain, source, reload_marker):
    target = STATE / "certs" / domain
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = target / "current"
    files = {name: (source / original).read_bytes() for name, original in CERT_FILES.items()}
    if current.is_symlink() and all((current / name).is_file()
                                     and (current / name).read_bytes() == data
                                     for name, data in files.items()):
        return current

    previous = current.readlink() if current.is_symlink() else None
    version = Path(tempfile.mkdtemp(prefix="pem-", dir=target))
    pending = target / ".current-next"
    published = False
    try:
        for name, data in files.items():
            write_atomic(version / name, data)
        # Check that the PEM files form a valid key/certificate pair before publishing.
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(version / "fullchain.pem", version / "privkey.pem")
        if reload_marker is not None:
            write_atomic(reload_marker, b"pending\n")
        pending.unlink(missing_ok=True)
        pending.symlink_to(version.name, target_is_directory=True)
        pending.replace(current)
        published = True
    finally:
        pending.unlink(missing_ok=True)
        if not published:
            shutil.rmtree(version)

    if previous is not None and previous.name == str(previous) and previous.name.startswith("pem-"):
        shutil.rmtree(target / previous, ignore_errors=True)
    return current


def refresh(config, lego):
    service = config["web_service"]
    marker = STATE / "reload-pending" if service else None
    # Pass the secret only to lego. Keep configuration independent of shell settings.
    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(STATE),
        "ARVANCLOUD_API_KEY": "Apikey " + config["token"],
        "ARVANCLOUD_PROPAGATION_TIMEOUT": "300",
    }
    errors = []
    for domain in config["domains"]:
        print(f"\nبررسی گواهی {domain} …", flush=True)
        store = STATE / "acme" / domain
        store.mkdir(parents=True, exist_ok=True, mode=0o700)
        names = [domain, f"*.{domain}"] if config["include_apex"] else [f"*.{domain}"]
        try:
            command = [str(lego), "run", "--accept-tos", "--email", config["email"],
                       "--server", "letsencrypt", "--dns", "arvancloud", "--path", str(store),
                       "--cert.name", "wildcard", "--domains", ",".join(names),
                       "--force-cert-domains", "--reuse-key", "--http-timeout", "30"]
            subprocess.run(command, cwd=STATE, env=env, check=True)
            current = publish(domain, store / "certificates", marker)
            print(f"گواهی: {current / 'fullchain.pem'}")
            print(f"کلید خصوصی: {current / 'privkey.pem'}", flush=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"{domain}: {exc}")

    if marker is not None and marker.exists():
        try:
            subprocess.run([SYSTEMCTL, "reload", service], check=True)
            marker.unlink()
            print(f"گواهی‌های جدید برای {service} بارگذاری شدند.")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"{service}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renew", action="store_true", help="Run the scheduled check without prompts")
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise ValueError("این اسکریپت برای اوبونتو با systemd است.")
    if os.geteuid() != 0:
        raise ValueError("با sudo اجرا کن: sudo python3 arvan_ssl.py")
    if not args.renew and not sys.stdin.isatty():
        raise ValueError("راه‌اندازی اولیه را از یک ترمینال تعاملی اجرا کن.")
    if not args.renew:
        subprocess.run([SYSTEMCTL, "show", "--property=Version", "--value"],
                       stdout=subprocess.DEVNULL, check=True)

    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = json.loads(CONFIG.read_text()) if CONFIG.exists() else None
        if args.renew and config is None:
            raise ValueError("ابتدا راه‌اندازی تعاملی را اجرا کن.")
        if not args.renew and (config is None or ask_yes("تنظیمات قبلی را تغییر می‌دهی؟", False)):
            config = ask_config()

        INSTALL.mkdir(parents=True, exist_ok=True)
        lego = install_lego()
        if not args.renew:
            CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_atomic(CONFIG, json.dumps(config).encode())
            install_timer()
            print("بررسی روزانه و تمدید خودکار systemd فعال شد.", flush=True)
        refresh(config, lego)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nاجرا لغو شد.")
    except (EOFError, OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        sys.exit(f"خطا: {exc}")
