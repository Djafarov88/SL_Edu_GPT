# Sportleader Academy — Production Deployment Guide

This guide describes deploying the Flask LMS on a **private Ubuntu server** with
PostgreSQL + Gunicorn + Nginx + HTTPS.

> **Note:** The `artifacts/api-server` (Node.js) component is **not** part of the
> production deployment. It is a development utility only and must NOT be exposed
> publicly.

---

## Requirements

| Component | Minimum version |
|-----------|----------------|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| Gunicorn | 23+ |
| Nginx | 1.22+ |
| Certbot | any (Let's Encrypt) |

---

## 1. Environment Variables

All required variables must be set in `/etc/systemd/system/academy.service`
(see section 7) or in a `.env` file loaded by your process manager.

| Variable | Required | Description |
|----------|----------|-------------|
| `FLASK_ENV` | Yes | Must be `production` |
| `SESSION_SECRET` | Yes | Random string ≥ 32 chars — see below |
| `DATABASE_URL` | Yes | PostgreSQL URL — SQLite is blocked in production |
| `ANTHROPIC_API_KEY` | No | Enables AI mentor chat |
| `LIMITER_STORAGE_URI` | No | Redis URL for rate limiter (multi-worker) |

Generate a secure session secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 2. Create a Virtual Environment and Install Dependencies

```bash
cd /srv/academy
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Configure PostgreSQL

```bash
sudo -u postgres psql

CREATE DATABASE sportleader_academy;
CREATE USER sportleader WITH PASSWORD 'choose_a_strong_password';
GRANT ALL PRIVILEGES ON DATABASE sportleader_academy TO sportleader;
\q
```

Set the `DATABASE_URL` environment variable:
```
DATABASE_URL=postgresql://sportleader:choose_a_strong_password@localhost:5432/sportleader_academy
```

---

## 4. Initialise the Database

Run once after first deployment (tables are created automatically, seed data is
inserted if the database is empty):

```bash
cd /srv/academy
source venv/bin/activate
export FLASK_ENV=production
export DATABASE_URL=postgresql://sportleader:password@localhost:5432/sportleader_academy
export SESSION_SECRET=your_secret_here
python wsgi.py
# Stop it after "Application ready." appears — tables and seed data are now created.
```

Or use the Python shell:
```bash
python - <<'EOF'
from app import create_app
from extensions import db
from init_db import seed_if_empty, seed_positions_if_empty, run_startup_migrations
app = create_app()
with app.app_context():
    db.create_all()
    seed_if_empty()
    seed_positions_if_empty()
    run_startup_migrations()
    print("Done.")
EOF
```

---

## 5. Start with Gunicorn

```bash
cd /srv/academy
source venv/bin/activate
gunicorn -w 3 -b 127.0.0.1:8000 wsgi:application \
  --access-logfile /var/log/academy/access.log \
  --error-logfile  /var/log/academy/error.log
```

> **Workers:** use `2 × CPU_cores + 1` as a starting point.
>
> **Rate limiter:** with multiple workers, add Redis and set
> `LIMITER_STORAGE_URI=redis://localhost:6379/0` so rate limits are shared
> across all workers.

---

## 6. Nginx Configuration

Create `/etc/nginx/sites-available/academy`:

```nginx
server {
    listen 80;
    server_name academy.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name academy.example.com;

    ssl_certificate     /etc/letsencrypt/live/academy.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/academy.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 10M;

    # Static files served directly by Nginx (faster)
    location /academy/static/ {
        alias /srv/academy/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # All other requests → Gunicorn
    location /academy/ {
        proxy_pass         http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-Prefix /academy;
        proxy_read_timeout 60;
    }
}
```

Enable and reload:
```bash
sudo ln -s /etc/nginx/sites-available/academy /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 7. Systemd Service

Create `/etc/systemd/system/academy.service`:

```ini
[Unit]
Description=Sportleader Academy LMS (Gunicorn)
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/academy
ExecStart=/srv/academy/venv/bin/gunicorn \
    -w 3 \
    -b 127.0.0.1:8000 \
    --access-logfile /var/log/academy/access.log \
    --error-logfile  /var/log/academy/error.log \
    wsgi:application

Restart=on-failure
RestartSec=5

# Environment
Environment="FLASK_ENV=production"
Environment="SESSION_SECRET=REPLACE_WITH_REAL_SECRET"
Environment="DATABASE_URL=postgresql://sportleader:password@localhost:5432/sportleader_academy"
Environment="ANTHROPIC_API_KEY=sk-ant-..."
# Optional Redis for rate limiting across workers:
# Environment="LIMITER_STORAGE_URI=redis://localhost:6379/0"

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/log/academy
sudo chown www-data:www-data /var/log/academy
sudo systemctl daemon-reload
sudo systemctl enable academy
sudo systemctl start academy
sudo systemctl status academy
```

---

## 8. Verify the Deployment

```bash
# App responds
curl -I https://academy.example.com/academy/login

# Logs
sudo journalctl -u academy -f
sudo tail -f /var/log/academy/error.log
```

---

## 9. Local Verification Before Deployment

```bash
# Verify production config fails correctly without vars
FLASK_ENV=production python -c "from config import get_config; get_config()"
# Expected: RuntimeError with list of missing variables

# Verify production config fails on SQLite
FLASK_ENV=production SESSION_SECRET=aaaabbbbccccddddeeeeffffaaaaabbb \
  DATABASE_URL=sqlite:///test.db python -c "from config import get_config; get_config()"
# Expected: RuntimeError — SQLite is not allowed

# Verify development mode starts with SQLite
FLASK_ENV=development python -c "from config import get_config; c=get_config(); print(c['SQLALCHEMY_DATABASE_URI'])"
# Expected: sqlite:///...sportleader_dev.db

# Verify wsgi:application is importable (set vars first)
FLASK_ENV=production SESSION_SECRET=aaaabbbbccccddddeeeeffffaaaaabbb \
  DATABASE_URL=postgresql://user:pass@localhost:5432/db \
  python -c "from wsgi import application; print('OK:', application)"
```

---

## 10. Notes on the Node.js API Server

`artifacts/api-server` is a development utility and **must NOT be deployed
publicly**. It has no authentication and is not hardened for production. It is
used only for development tooling within the Replit workspace.
