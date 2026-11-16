#!/bin/sh
# Ubuntu bootstrap. Run from a terminal, including via curl | bash.
set -eu

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo -- "$@"
    fi
}

main() {
    base_url=${ARVAN_SSL_BASE_URL:-https://raw.githubusercontent.com/mmdkevin/arvan-wildcard-ssl/main}
    if ! { exec 3<>/dev/tty; } 2>/dev/null; then
        printf '%s\n' 'Run the installer from an interactive terminal.' >&2
        return 1
    fi

    if ! command -v curl >/dev/null 2>&1 ||
       ! /usr/bin/python3 -I -c 'import ssl' >/dev/null 2>&1; then
        as_root apt-get update <&3
        as_root apt-get install -y curl python3 ca-certificates <&3
    fi

    work_dir=$(mktemp -d)
    trap 'rm -f -- "$work_dir/arvan_ssl.py"; rmdir -- "$work_dir"' EXIT
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 120 --output "$work_dir/arvan_ssl.py" \
        "${base_url%/}/arvan_ssl.py"
    as_root /usr/bin/python3 -I "$work_dir/arvan_ssl.py" <&3
}

main
