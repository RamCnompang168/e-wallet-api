# NovaPay Production Deployment Guide

## 1. System Requirements & Architecture

In a production environment, NovaPay operates across 5 decoupled services:

```text
[Internet / Reverse Proxy / Nginx / Cloudflare]
                     ↓
             [Gunicorn (WSGI)]
                     ↓
[PostgreSQL 16+] <───────> [Redis 7+] <───────> [Celery Workers + Beat]
```

---

## 2. Docker Compose Deployment

### Step 1: Clone and Configure Environment
```bash
git clone <repository_url>
cd API

# Copy production template and configure secure secrets
cp .env.example .env
nano .env
```

Ensure the following variables are customized:
```ini
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<generate_secure_random_string_64_chars>
DJANGO_ALLOWED_HOSTS=api.yourdomain.com
DATABASE_PASSWORD=<strong_postgres_password>
JWT_SECRET_KEY=<strong_jwt_signing_key>
WEBHOOK_SECRET=<strong_webhook_hmac_secret>
```

### Step 2: Build and Launch Containers
```bash
docker-compose -f docker-compose.yml up --build -d
```

### Step 3: Run Database Migrations & Initial Setup
The `web` container automatically runs migrations and seeds initial system accounts and limits on startup. To verify or re-run manually:
```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py seed_data
```

### Step 4: Create Super Administrator Account
```bash
docker-compose exec web python manage.py createsuperuser
```

---

## 3. Reverse Proxy Configuration (Nginx)

```nginx
upstream novapay_upstream {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

    client_max_body_size 25M;

    location /static/ {
        alias /var/www/novapay/staticfiles/;
    }

    location /media/ {
        alias /var/www/novapay/media/;
    }

    location / {
        proxy_pass http://novapay_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 4. Health Checks & Monitoring

* **Health Endpoint**: `GET /api/v1/`
* **Celery Worker Status**: `docker-compose exec celery_worker celery -A API inspect ping`
* **Database Readiness**: `docker-compose exec postgres pg_isready`
