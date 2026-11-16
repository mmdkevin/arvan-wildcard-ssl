[فارسی](README.fa.md) · [English](README.md)

# ArvanCloud Wildcard TLS

Issue and automatically renew Let's Encrypt wildcard certificates on Ubuntu using ArvanCloud DNS. The installer creates one certificate per domain and supports the default PasarGuard Docker layout.

## Quick start

Run the installer from an interactive terminal on your Ubuntu server.

```bash
curl -fsSL https://raw.githubusercontent.com/mmdkevin/arvan-wildcard-ssl/main/install.sh | bash
```

The installer downloads the certificate script and uses `sudo` when needed. You can review [the installer](install.sh) and [the certificate script](arvan_ssl.py) before running it.

Install on an Ubuntu server that meets these requirements.

- An Ubuntu server with `systemd`, `curl`, and root or sudo access. Automatic installation supports AMD64 and ARM64.
- Domains whose public DNS is managed by ArvanCloud.
- An [ArvanCloud API key](https://npanel.arvancloud.ir/profile/api-keys) with permission to create and delete DNS records for those domains.

Enter the number of domains, each domain name, and the API key when prompted. For `example.com`, the certificate covers both `example.com` and `*.example.com`. The wildcard covers one subdomain level. Add `dev.example.com` as another domain if you need to cover `api.dev.example.com`.

Issuance uses DNS-01 and is subject to the Let's Encrypt Subscriber Agreement. [DNS-01 documentation](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge) · [Subscriber Agreement](https://letsencrypt.org/repository/)

## Certificate paths

The installer prints the full paths after each successful check.

| Installation | Directory for `example.com` |
| --- | --- |
| Standard Ubuntu | `/var/lib/arvan-wildcard/certs/example.com/` |
| Default PasarGuard installation detected | `/var/lib/pasarguard/arvan-certs/example.com/` |

Use `fullchain.pem` for the certificate chain and `privkey.pem` for the private key. These filenames stay the same after renewal.

## PasarGuard TLS inbounds

With the default PasarGuard Docker layout, the panel's existing mount exposes `/var/lib/pasarguard` inside the container. If you're upgrading from an older version of this script, rerun the installer and press **Enter** at `Change the saved configuration?` to migrate existing certificates. [PasarGuard Docker configuration](https://github.com/PasarGuard/panel/blob/main/docker-compose.yml)

In the inbound's core configuration, set `streamSettings.security` to `tls` and add the following entry under `streamSettings.tlsSettings.certificates`. Replace `example.com` with the domain you entered during setup. [PasarGuard core configuration](https://docs.pasarguard.org/en/panel/core/)

```json
{
  "certificateFile": "/var/lib/pasarguard/arvan-certs/example.com/fullchain.pem",
  "keyFile": "/var/lib/pasarguard/arvan-certs/example.com/privkey.pem"
}
```

If the inbound runs on a separate node, Xray on that node needs access to both files at the configured paths.

## Automatic renewal

One systemd timer checks all managed domains daily. The script renews certificates when due and publishes the new files at the same paths. The service that terminates TLS controls when it loads the updated certificate.

### Timer status

```bash
systemctl list-timers arvan-wildcard-renew.timer
```

### Renewal logs

```bash
sudo journalctl -u arvan-wildcard-renew.service -n 50 --no-pager
```

To stop renewal for a domain, delete its whole certificate directory from the applicable path above. Future checks skip that domain. To add it back, rerun the installer, choose to change the saved configuration, and enter every domain you want to manage.

## Credentials

The terminal hides the API key as you type. The installer stores it locally in the root-only file `/etc/arvan-wildcard/config.json`. Keep that file and all private keys out of Git.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| ArvanCloud rejects a DNS request | Check the API key's DNS permissions for every requested domain. |
| The DNS challenge times out | Check that the domain's authoritative nameservers are set to ArvanCloud and use the renewal log to identify the failing domain. |
| PasarGuard says a certificate file is missing | Compare the inbound path with the exact path printed by the installer and check it from the host or container running Xray. |

Open a [GitHub issue](https://github.com/mmdkevin/arvan-wildcard-ssl/issues) with your Ubuntu version and the relevant log lines if the problem persists. Remove API keys and private key material from anything you share.
