#!/usr/bin/env bash
# Run on a new, dedicated Ubuntu 24.04 instance as root.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo on the Aliyun instance'; exit 1; }
backend_host=${1:?Usage: sudo bash setup.sh backend.example.com}
[[ $backend_host =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && $backend_host == *.* ]] || { echo 'Invalid DNS hostname'; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Small VM: reserve disk swap before package installation. Never replace existing swap.
if [[ $(awk '/MemTotal/ {print $2}' /proc/meminfo) -lt 1048576 ]] && [[ -z $(swapon --show --noheadings) ]]; then
  swap_file=/var/lib/finfeed.swap
  if [[ ! -e $swap_file ]]; then
    dd if=/dev/zero of="$swap_file" bs=1M count=1024 status=none
    chmod 600 "$swap_file"
    mkswap "$swap_file" >/dev/null
  fi
  [[ $(blkid -s TYPE -o value "$swap_file") == swap ]] || { echo "Existing swap path is not a swap file"; exit 1; }
  chmod 600 "$swap_file"
  swapon "$swap_file"
  if ! awk '$1 == "/var/lib/finfeed.swap" {found=1} END {exit !found}' /etc/fstab; then
    printf '%s\n' '/var/lib/finfeed.swap none swap sw 0 0' >> /etc/fstab
  fi
  printf '%s\n' 'vm.swappiness=10' > /etc/sysctl.d/90-finfeed-memory.conf
  sysctl -p /etc/sysctl.d/90-finfeed-memory.conf
fi
apt-get update
apt-get install -y python3 python3-venv git caddy ca-certificates curl unattended-upgrades
install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/finfeed-limits.conf <<'CONFIG'
[Journal]
SystemMaxUse=50M
RuntimeMaxUse=10M
CONFIG
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONFIG'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONFIG
systemctl restart systemd-journald
id finfeed >/dev/null 2>&1 || useradd --system --home-dir /opt/finfeed --shell /usr/sbin/nologin finfeed
install -d -m 755 /opt/finfeed /opt/finfeed/releases
install -d -m 700 /etc/finfeed
install -d -o finfeed -g finfeed -m 700 /opt/finfeed/shared/cache
if [[ ! -f /etc/finfeed/backend.env ]]; then
  install -m 600 "$source_dir/backend.env.example" /etc/finfeed/backend.env
fi
install -m 644 "$source_dir"/finfeed*.service "$source_dir"/finfeed*.timer /etc/systemd/system/
# Use on a dedicated instance: this replaces its Caddy website configuration.
cat > /etc/caddy/Caddyfile <<CONFIG
$backend_host {
    encode zstd gzip
    reverse_proxy 127.0.0.1:10000
}
CONFIG
caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable caddy
systemctl restart caddy
printf '%s\n' 'Fill /etc/finfeed/backend.env privately, then run deploy.sh.' 'Notification timer is installed but NOT enabled until cutover.'
