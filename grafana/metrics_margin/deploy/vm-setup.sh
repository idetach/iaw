#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# vm-setup.sh — Run ON the VM after first SSH login
#
# Installs Docker, Docker Compose plugin, and creates the project dir.
#
# Usage (on the VM):
#   sudo bash vm-setup.sh
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: Run this script as root (sudo bash vm-setup.sh)"
  exit 1
fi

echo "==> Updating system packages ..."
apt-get update -qq
apt-get upgrade -y -qq

# ── Install Docker ──
if command -v docker &>/dev/null; then
  echo "==> Docker already installed: $(docker --version)"
else
  echo "==> Installing Docker ..."
  apt-get install -y -qq ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

# ── Allow current (non-root) user to use Docker ──
SUDO_USER_NAME="${SUDO_USER:-$USER}"
if id "$SUDO_USER_NAME" &>/dev/null; then
  usermod -aG docker "$SUDO_USER_NAME"
  echo "==> Added '$SUDO_USER_NAME' to docker group (re-login to take effect)"
fi

# ── UFW firewall ──
if command -v ufw &>/dev/null; then
  echo "==> Configuring UFW firewall ..."
  ufw allow 22/tcp    comment "SSH"
  ufw allow 80/tcp    comment "HTTP (Caddy)"
  ufw allow 443/tcp   comment "HTTPS (Caddy)"
  ufw deny  3005/tcp  comment "Grafana direct - use Caddy instead"
  ufw --force enable
  ufw status verbose
else
  echo "==> UFW not found, skipping firewall setup"
fi

# ── Create project directory ──
APP_DIR="/opt/metrics_margin"
mkdir -p "$APP_DIR"
chown "$SUDO_USER_NAME":"$SUDO_USER_NAME" "$APP_DIR"
echo "==> Project directory: $APP_DIR"

# ── Swap (useful for e2-small with 2GB RAM) ──
if [ ! -f /swapfile ]; then
  echo "==> Creating 2GB swap file ..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  VM setup complete."
echo "  Project dir: $APP_DIR"
echo "  Docker:      $(docker --version)"
echo "  Compose:     $(docker compose version)"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "Next: run deploy.sh from your local machine to push the stack."
echo "NOTE: log out and back in for docker group membership to take effect."
