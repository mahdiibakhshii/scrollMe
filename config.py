# Server Configuration
#
# Every value can be overridden by an environment variable so the same code
# runs locally (defaults below) and on the server (PM2 sets HOST/PORT/etc — see
# deploy/ecosystem.config.cjs). Nothing here is a secret except ADMIN_TOKEN,
# which is only ever provided via the environment, never committed.

import os


def _flag(name, default):
    return os.environ.get(name, default).lower() not in ('0', 'false', 'no', '')


# Networking — where the app binds.
#   Local dev:  0.0.0.0:8080 (reachable from your phone on the same Wi-Fi).
#   Server:     PM2 sets HOST=127.0.0.1 PORT=8081; nginx exposes it publicly on :8080.
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '8080'))

# Logic
AUDIENCE_PERCENTAGE_THRESHOLD = float(os.environ.get('AUDIENCE_PERCENTAGE_THRESHOLD', '0.30'))  # 30% must swipe
RESET_DELAY = float(os.environ.get('RESET_DELAY', '2.0'))  # seconds debounce between triggers
# How often the server pushes a keepalive to TD WebSockets (prevents idle drops).
KEEPALIVE_INTERVAL = float(os.environ.get('KEEPALIVE_INTERVAL', '15'))  # seconds

# OSC (LOCAL fallback only) — reaches TouchDesigner solely when TD runs on the
# same machine as the server. Over the internet TD connects out via WebSocket
# (see /ws), so on the server this is disabled (OSC_ENABLED=0 in the PM2 env).
OSC_ENABLED = _flag('OSC_ENABLED', '1')
OSC_IP = os.environ.get('OSC_IP', '127.0.0.1')
OSC_PORT = int(os.environ.get('OSC_PORT', '9000'))

# Admin control endpoint (fire arbitrary events at TD — see POST /admin/event).
# Empty string = endpoint is open (fine for a closed local test). Set a token in
# production via the server environment to require it.
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '')
