#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CF_TUNNEL_TOKEN:-}" ]]; then
  echo "CF_TUNNEL_TOKEN is not set" >&2
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared binary is required on PATH" >&2
  exit 2
fi

cloudflared tunnel --no-autoupdate run --token "${CF_TUNNEL_TOKEN}"
