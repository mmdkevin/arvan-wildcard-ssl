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
PASARGUARD_CERTS = Path("/var/lib/pasarguard/arvan-certs")
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
        raise ValueError("Invalid domain name.") from exc
    labels = name.split(".")
    if (len(name) > 251 or len(labels) < 2 or labels[-1].isdigit()
            or any(not LABEL.fullmatch(label) for label in labels)):
        raise ValueError("Enter a domain name, such as example.com.")
    return name


def ask_yes(prompt, default):
    suffix = " [Y/n] " if default else " [y/N] "
    while True:
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Enter y or n.")


def ask_config():
    print("By continuing, you accept the Let's Encrypt Subscriber Agreement:")
    print("https://letsencrypt.org/repository/")
    while True:
        value = input("How many domains need a certificate? ").strip()
        if value.isdecimal() and len(value) < 10 and int(value) > 0:
            count = int(value)
            break
        print("Enter a number greater than zero.")

    domains = []
    while len(domains) < count:
        try:
            name = parse_domain(input(f"Domain {len(domains) + 1} (e.g. example.com): "))
            if name in domains:
                raise ValueError("You already entered this domain.")
            domains.append(name)
        except ValueError as exc:
            print(exc)

    while True:
        value = getpass.getpass("ArvanCloud API key (input hidden): ").strip()
        token = re.sub(r"^apikey\s+", "", value, flags=re.IGNORECASE)
        if re.fullmatch(r"[\x21-\x7e]+", token) and token.lower() != "apikey":
            break
        print("Enter your ArvanCloud API key.")

    return {"domains": domains, "token": token}


def install_lego():
    machine = platform.machine()
    if machine not in ARCHIVES:
        raise ValueError("Automatic installation supports Ubuntu on amd64 and arm64.")
    arch, sha256 = ARCHIVES[machine]
    binary = INSTALL / f"lego-{VERSION}"
    if binary.is_file() and os.access(binary, os.X_OK):
        return binary
    print(f"Installing lego {VERSION}...", flush=True)
    asset = f"lego_v{VERSION}_linux_{arch}.tar.gz"
    url = f"https://github.com/go-acme/lego/releases/download/v{VERSION}/{asset}"
    install_limit = 32 * 1024 * 1024
    with urlopen(url, timeout=60) as response:
        content = response.read(install_limit + 1)
    if len(content) > install_limit or hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError("The lego download does not match the official SHA-256 checksum.")
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        member = archive.getmember("lego")
        if not member.isfile():
            raise ValueError("The lego archive does not contain the expected executable.")
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


def certificate_root():
    local = STATE / "certs"
    if local.is_symlink():
        return local.parent / local.readlink()
    return local


def configure_pasarguard_output():
    local = STATE / "certs"
    shared = PASARGUARD_CERTS
    if not shared.parent.is_dir() or local.is_symlink():
        return
    if shared.is_symlink() or (shared.exists() and not shared.is_dir()):
        raise ValueError(f"Invalid PasarGuard certificate directory: {shared}")

    moved = local.exists()
    if moved:
        if shared.exists():
            raise FileExistsError(f"Both certificate directories exist: {local} and {shared}")
        local.rename(shared)
    else:
        shared.mkdir(mode=0o700, exist_ok=True)
    try:
        # Preserve host paths while keeping the real PEM files inside the existing Docker mount.
        local.symlink_to(shared, target_is_directory=True)
    except OSError:
        if moved:
            shared.rename(local)
        raise


def publish(target, source):
    current = target / "current"
    files = {name: (source / original).read_bytes() for name, original in CERT_FILES.items()}
    if current.is_symlink() and all((current / name).is_file()
                                     and (current / name).read_bytes() == data
                                     for name, data in files.items()):
        return target

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
    return target


def expose_pem_links(target):
    # Both public paths follow the same certificate version on renewal.
    for name in CERT_FILES:
        link = target / name
        destination = Path("current") / name
        if link.is_symlink() and link.readlink() == destination:
            continue
        link.symlink_to(destination)


def refresh(config, lego):
    # Pass the secret only to lego. Keep configuration independent of shell settings.
    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(STATE),
        "ARVANCLOUD_API_KEY": "Apikey " + config["token"],
        "ARVANCLOUD_PROPAGATION_TIMEOUT": "300",
    }
    root = certificate_root()
    errors = []
    for domain in config["domains"]:
        target = root / domain
        if not target.is_dir():
            # Only interactive configuration creates managed certificate directories.
            print(f"Skipping {domain}: certificate directory is missing.", flush=True)
            continue
        print(f"\nChecking certificate for {domain}...", flush=True)
        store = STATE / "acme" / domain
        store.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            command = [str(lego), "run", "--accept-tos",
                       "--server", "letsencrypt", "--dns", "arvancloud", "--path", str(store),
                       "--cert.name", "wildcard", "--domains", f"{domain},*.{domain}",
                       "--force-cert-domains", "--reuse-key", "--http-timeout", "30"]
            if config.get("email"):
                # Keep using the ACME account created by earlier versions.
                command.extend(["--email", config["email"]])
            subprocess.run(command, cwd=STATE, env=env, check=True)
            publish(target, store / "certificates")
            expose_pem_links(target)
            print(f"Certificate: {target / 'fullchain.pem'}")
            print(f"Private key: {target / 'privkey.pem'}", flush=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"{domain}: {exc}")

    if errors:
        raise ValueError("\n".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renew", action="store_true", help="Run the scheduled check without prompts")
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise ValueError("This installer requires Ubuntu with systemd.")
    if os.geteuid() != 0:
        raise ValueError("Run as root: sudo python3 arvan_ssl.py")
    if not args.renew and not sys.stdin.isatty():
        raise ValueError("Run the initial setup in an interactive terminal.")
    if not args.renew:
        subprocess.run([SYSTEMCTL, "show", "--property=Version", "--value"],
                       stdout=subprocess.DEVNULL, check=True)

    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = json.loads(CONFIG.read_text()) if CONFIG.exists() else None
        if args.renew and config is None:
            raise ValueError("Run the interactive setup first.")
        reconfigure = not args.renew and (
            config is None or ask_yes("Change the saved configuration?", False)
        )
        if reconfigure:
            config = {**(config or {}), **ask_config()}

        INSTALL.mkdir(parents=True, exist_ok=True)
        lego = install_lego()
        if not args.renew:
            configure_pasarguard_output()
            if reconfigure:
                for domain in config["domains"]:
                    (certificate_root() / domain).mkdir(parents=True, exist_ok=True, mode=0o700)
            CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_atomic(CONFIG, json.dumps(config).encode())
            install_timer()
            print("Daily certificate checks and automatic renewal are enabled.", flush=True)
        refresh(config, lego)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCanceled.")
    except (EOFError, OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        sys.exit(f"Error: {exc}")
