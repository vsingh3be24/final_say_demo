#!/usr/bin/env bash
# ==============================================================================
# FinalSay - loopback-only EC2 container helper (not a complete production setup)
# Requires externally managed PostgreSQL and operator-provided runtime settings.
# Review this script locally before running it. Do not pipe a remote copy to bash.
# ==============================================================================

set -euo pipefail

if [[ -z "${FINALSAY_DATABASE_URL:-}" || "${FINALSAY_DATABASE_URL}" == sqlite:* ]]; then
    echo "Set FINALSAY_DATABASE_URL to an externally managed PostgreSQL DSN before running." >&2
    exit 2
fi
if [[ -z "${FINALSAY_JWT_SECRET:-}" ]] || [[ ${#FINALSAY_JWT_SECRET} -lt 32 ]]; then
    echo "Set FINALSAY_JWT_SECRET to a random secret of at least 32 characters." >&2
    exit 2
fi
if [[ -z "${FINALSAY_CORS_ORIGINS:-}" || "${FINALSAY_CORS_ORIGINS}" == "*" ]]; then
    echo "Set FINALSAY_CORS_ORIGINS to the exact HTTPS frontend origin; wildcard CORS is refused." >&2
    exit 2
fi
if [[ "${FINALSAY_COMPARISON_MODEL:-semantic}" != "semantic" ]]; then
    echo "Only the semantic comparison model is allowed for a real deployment." >&2
    exit 2
fi

echo "============================================================"
echo " Starting FinalSay AWS EC2 Deployment"
echo "============================================================"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS="unknown"
fi

echo "[1/5] Detected OS: ${OS}"

# Install Docker and Git if not installed
echo "[2/5] Installing dependencies (Docker, Git, Curl)..."
if [ "${OS}" = "ubuntu" ] || [ "${OS}" = "debian" ]; then
    sudo apt-get update -y
    sudo apt-get install -y git curl docker.io
    sudo systemctl enable --now docker
elif [ "${OS}" = "amzn" ] || [ "${OS}" = "fedora" ] || [ "${OS}" = "rhel" ]; then
    sudo dnf update -y
    sudo dnf install -y git curl docker
    sudo systemctl enable --now docker
fi

# Add current user to docker group so sudo isn't needed
sudo usermod -aG docker "$USER" || true

# Prepare application directory
APP_DIR="/opt/finalsay"
echo "[3/5] Setting up application in ${APP_DIR}..."
sudo mkdir -p "${APP_DIR}"
sudo chown -R "$USER:$USER" "${APP_DIR}"

REPO_URL="https://github.com/goyaljatin870/FinalSay-prototype.git"

if [ -d "${APP_DIR}/.git" ]; then
    cd "${APP_DIR}"
    echo "Using the existing checked-out source at ${APP_DIR}; review and update it manually before running."
else
    echo "Cloning the repository..."
    git clone "${REPO_URL}" "${APP_DIR}"
    cd "${APP_DIR}"
fi

# Stop and remove existing container if running
echo "[4/5] Building and launching FinalSay backend container..."
sudo docker stop finalsay-backend 2>/dev/null || true
sudo docker rm finalsay-backend 2>/dev/null || true

# Build Docker image
sudo docker build -t finalsay-backend:latest -f Dockerfile .

# Keep the application bound to loopback. Put a TLS reverse proxy or load
# balancer in front of it; do not open port 8000 directly to the internet.
sudo docker run -d \
  --name finalsay-backend \
  --restart always \
  -p "127.0.0.1:${FINALSAY_PORT:-8000}:8000" \
  -e FINALSAY_JWT_SECRET="${FINALSAY_JWT_SECRET}" \
  -e FINALSAY_CORS_ORIGINS="${FINALSAY_CORS_ORIGINS}" \
  -e FINALSAY_DATABASE_URL="${FINALSAY_DATABASE_URL}" \
  -e FINALSAY_COMPARISON_MODEL="${FINALSAY_COMPARISON_MODEL:-semantic}" \
  -e FINALSAY_ANCHOR="${FINALSAY_ANCHOR:-local}" \
  -e FINALSAY_SCRAPE_INTERVAL_SECONDS="${FINALSAY_SCRAPE_INTERVAL_SECONDS:-7200}" \
  finalsay-backend:latest

echo "[5/5] Verifying deployment..."
sleep 5

if curl -fsS "http://127.0.0.1:${FINALSAY_PORT:-8000}/api/health/ready" >/dev/null 2>&1; then
    echo ""
    echo "============================================================"
    echo " FinalSay backend is responding on the EC2 loopback interface."
    echo "============================================================"
    echo " Local health check: http://127.0.0.1:${FINALSAY_PORT:-8000}/api/health/ready"
    echo " Configure TLS termination and private networking before external access."
    echo ""
    echo "============================================================"
else
    echo "Container started. View logs with: sudo docker logs -f finalsay-backend"
fi
