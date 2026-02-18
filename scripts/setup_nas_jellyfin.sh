#!/usr/bin/env bash
set -euo pipefail

# Run this script manually on host with proper permissions.
# It sets up directories, starts compose services, and prints next steps.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p /media/incoming /media/library
chmod -R 775 /media/incoming /media/library

cd "$PROJECT_DIR"
# Run media stack in Docker; app is expected to run as host systemd service on :8787.
docker compose up -d qbittorrent jellyfin

echo "\nServices started (docker):"
docker compose ps

echo "\nJellyfin URL: http://<HOST_IP>:8096"
echo "qBittorrent URL: http://<HOST_IP>:8080"
echo "App URL (host service): http://127.0.0.1:8787/health"

echo "\nIf docker app container exists, remove it to avoid port 8787 conflict:"
echo "  docker compose stop app || true"
echo "  docker compose rm -f app || true"

echo "\nFor SMB (NAS-style share), run as root:"
cat <<'EOF'
apt-get update && apt-get install -y samba
cat >> /etc/samba/smb.conf <<CONF

[AnimeLibrary]
   path = /media/library
   browseable = yes
   read only = no
   guest ok = no
   valid users = orashi
   create mask = 0664
   directory mask = 0775
CONF

smbpasswd -a orashi
systemctl restart smbd
systemctl enable smbd
EOF
