#!/bin/bash
# Retry Let's Encrypt for api.jashuvatrade.xyz when DNS propagates
IP=$(dig +short api.jashuvatrade.xyz @8.8.8.8 +time=3)
if [ "$IP" = "65.0.136.146" ] && [ ! -f /etc/letsencrypt/live/api.jashuvatrade.xyz/fullchain.pem ]; then
  certbot --nginx -d api.jashuvatrade.xyz --non-interactive --agree-tos -m admin@jashuvatrade.xyz --redirect
fi
