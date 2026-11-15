#!/usr/bin/env bash
# Run as root on the Debian VM (12 or 13). Installs Docker, builds and starts EpochLab.
#
# Local-only (default): the app is reachable only from your LAN at http://<VM_IP>:8000
#     bash deploy/setup-debian.sh
# Behind the NanoPi reverse proxy later:
#     NANOPI_IP=192.168.1.2 bash deploy/setup-debian.sh
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAN_CIDR="${LAN_CIDR:-192.168.0.0/16}"

apt-get update
apt-get install -y ca-certificates curl git ufw qemu-guest-agent
systemctl enable --now qemu-guest-agent || true

if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

# Firewall. NOTE: Docker-published ports bypass ufw, so we also bind the port explicitly (see below).
ufw default deny incoming
ufw allow from "$LAN_CIDR" to any port 22 proto tcp
if [ -n "${NANOPI_IP:-}" ]; then
  ufw allow from "$NANOPI_IP" to any port 8000 proto tcp
else
  ufw allow from "$LAN_CIDR" to any port 8000 proto tcp
fi
ufw --force enable

cd "$REPO_DIR"
mkdir -p data validation && chown -R 10001:10001 data validation
docker compose up -d --build
sleep 5
curl -fsS http://127.0.0.1:8000/api/health && echo
IP=$(hostname -I | awk '{print $1}')
echo "EpochLab is up: http://$IP:8000  (LAN only)"
