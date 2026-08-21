#!/bin/bash
# Fix api.jashuvatrade.xyz reachability on the EC2 host.
# - DNS must already point at this instance's public IP (65.0.136.146)
# - Backend must be healthy on 127.0.0.1:8000
# - Install/repair nginx reverse proxy on :80/:443 + Let's Encrypt cert
set -euo pipefail

DOMAIN="api.jashuvatrade.xyz"
EMAIL="${CERTBOT_EMAIL:-admin@jashuvatrade.xyz}"
UPSTREAM="http://127.0.0.1:8000"
EXPECTED_IP="${EXPECTED_API_IP:-65.0.136.146}"

echo "==> Preflight"
curl -sf --max-time 5 http://127.0.0.1:8000/health | head -c 200 || {
  echo "ERROR: backend not healthy on 127.0.0.1:8000 — start docker backend first"
  exit 1
}
echo

RESOLVED="$(dig +short "$DOMAIN" @8.8.8.8 +time=3 | head -1 || true)"
echo "DNS $DOMAIN -> ${RESOLVED:-<none>} (expected $EXPECTED_IP)"
if [ -n "$RESOLVED" ] && [ "$RESOLVED" != "$EXPECTED_IP" ]; then
  echo "WARNING: DNS does not match expected EIP yet — certbot may fail HTTP-01"
fi

echo "==> What owns :80 / :443"
ss -ltnp | awk 'NR==1 || /:(80|443)\s/' || netstat -ltnp 2>/dev/null | awk 'NR==1 || /:(80|443)\s/' || true

# Stop common conflicting proxies that leave :80/:443 half-dead (Pingora/tunnel 502s).
if systemctl is-active --quiet cloudflared 2>/dev/null; then
  echo "==> Stopping cloudflared (conflicts with direct nginx HTTPS)"
  systemctl stop cloudflared || true
  systemctl disable cloudflared || true
fi
if docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E ':(80|443)->'; then
  echo "==> Docker containers publishing 80/443:"
  docker ps --format '{{.Names}} {{.Ports}}' | grep -E ':(80|443)->' || true
fi

echo "==> Install nginx + certbot"
if command -v dnf >/dev/null 2>&1; then
  dnf install -y nginx || true
  dnf install -y certbot python3-certbot-nginx || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y nginx certbot python3-certbot-nginx || true
elif command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y nginx certbot python3-certbot-nginx
fi

mkdir -p /var/www/certbot /etc/nginx/conf.d

# Disable default site that can steal server_name.
rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
if [ -f /etc/nginx/sites-enabled/default ]; then
  rm -f /etc/nginx/sites-enabled/default
fi

echo "==> Bootstrap HTTP proxy (certbot + health)"
cat > /etc/nginx/conf.d/nexusquant.conf << NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /health {
        proxy_pass ${UPSTREAM}/health;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass ${UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX

nginx -t
systemctl enable nginx
systemctl restart nginx

echo "==> HTTP check via localhost Host header"
curl -sf --max-time 5 -H "Host: ${DOMAIN}" http://127.0.0.1/health | head -c 200
echo

echo "==> Issue / renew Let's Encrypt cert"
if command -v certbot >/dev/null 2>&1; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect \
    || certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" \
    || echo "WARNING: certbot failed — HTTP proxy still up on :80"
else
  echo "WARNING: certbot not installed"
fi

CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  echo "==> Writing full SSL nginx config"
  cat > /etc/nginx/conf.d/nexusquant.conf << NGINXSSL
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};
    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        proxy_pass ${UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 120s;
        proxy_buffering off;
    }
}
NGINXSSL
  nginx -t && systemctl reload nginx
else
  echo "WARNING: no cert on disk — left HTTP-only nginx proxy"
fi

echo "==> Public checks"
curl -sf --max-time 8 "http://${DOMAIN}/health" | head -c 200 || echo "HTTP public check failed"
echo
curl -sfk --max-time 8 "https://${DOMAIN}/health" | head -c 200 || echo "HTTPS public check failed"
echo
echo "Done. Prefer https://${DOMAIN}/health once cert is valid."
