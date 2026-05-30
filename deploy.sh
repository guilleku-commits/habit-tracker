#!/bin/bash
# ─── Habit Tracker Docker Deployment ─────────────────────────────────────
# For your VPS (Linux w/ Docker + nginx or Caddy)
#
# Quick start:
#   1. Copy this entire habit-tracker/ folder to your VPS
#   2. docker compose up -d
#   3. Set up reverse proxy (instructions below)

set -e

echo "Building Habit Tracker Docker image..."
docker build -t habit-tracker .

echo ""
echo "Run it:"
echo "  docker run -d \\"
echo "    -p 5000:5000 \\"
echo "    -v habit-data:/app/data \\"
echo "    --name habit-tracker \\"
echo "    habit-tracker"
echo ""
echo "First visit http://YOUR_VPS_IP:5000 to set your password!"
echo ""
echo "────────── Reverse Proxy (Caddy / nginx) ──────────"
echo ""
echo "With Caddy (easier):"
echo "  habits.yourdomain.com {"
echo "    reverse_proxy localhost:5000"
echo "  }"
echo ""
echo "With nginx:"
echo "  server {"
echo "    listen 80;"
echo "    server_name habits.yourdomain.com;"
echo "    location / {"
echo "      proxy_pass http://127.0.0.1:5000;"
echo "      proxy_set_header Host \\\$host;"
echo "      proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;"
echo "    }"
echo "  }"
echo ""
echo "Then secure with certbot or let Caddy auto-HTTPS it."
