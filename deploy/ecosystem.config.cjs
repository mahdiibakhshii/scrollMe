// PM2 process definition for the ScrollMe (SurfScroll) server.
// Runs the Python aiohttp + Socket.IO app under the repo's own venv so PM2 keeps
// it alive and restarts it on each deploy. Mirrors the CityLeaks deploy pattern,
// but this app is Python (interpreter = the venv python) instead of Node.
//
// Ports: the app binds 127.0.0.1:8081 (localhost only); nginx exposes it to the
// world on :8080 (see deploy/nginx-scrollme.conf). It shares the box with
// CityLeaks (which owns :80/:443 and node:3000) without collision.
module.exports = {
  apps: [
    {
      name: 'scrollme',
      cwd: '/opt/scrollme',
      script: 'main.py',
      interpreter: '/opt/scrollme/.venv/bin/python',
      env: {
        HOST: '127.0.0.1',
        PORT: '8081',
        // TD connects over the internet via WebSocket, so the local OSC path is off.
        OSC_ENABLED: '0',
        AUDIENCE_PERCENTAGE_THRESHOLD: '0.30',
        // ADMIN_TOKEN is a SECRET — never hardcode it here (public repo). Provide it
        // via the server environment (e.g. /etc/environment) and it's passed through.
        // Empty = the /admin/event endpoint is open (acceptable for a closed show).
        ADMIN_TOKEN: process.env.ADMIN_TOKEN,
      },
      autorestart: true,
      max_restarts: 20,
      restart_delay: 2000,
    },
  ],
};
