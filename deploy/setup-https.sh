#!/bin/bash
# Setup HTTPS for api.jashuvatrade.xyz on EC2
set -e

DOMAIN="api.jashuvatrade.xyz"
EMAIL="admin@jashuvatrade.xyz"

dnf install -y nginx
mkdir -p /var/www/certbot

# Bootstrap nginx HTTP for certbot
cat > /etc/nginx/conf.d/nexusquant.conf << 'NGINX'
server {
    listen 80;
    server_name api.jashuvatrade.xyz;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

systemctl enable nginx
systemctl start nginx

# Certbot
dnf install -y certbot python3-certbot-nginx 2>/dev/null || pip3 install certbot certbot-nginx 2>/dev/null || true

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect 2>&1 || \
certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" 2>&1

# Full SSL config
cat > /etc/nginx/conf.d/nexusquant.conf << 'NGINXSSL'
server {
    listen 80;
    server_name api.jashuvatrade.xyz;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 443 ssl;
    server_name api.jashuvatrade.xyz;
    ssl_certificate /etc/letsencrypt/live/api.jashuvatrade.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.jashuvatrade.xyz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }
}
NGINXSSL

nginx -t && systemctl reload nginx
echo "HTTPS ready at https://api.jashuvatrade.xyz"
