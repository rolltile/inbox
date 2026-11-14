# Telnyx SMS Inbox 1.0

A simple, private, read-only SMS inbox for a Telnyx US phone number.

Open the app in a browser, log in with the app password, and see the **3 most recently received SMS messages** sent to your Telnyx number. Each message shows the sender, recipient, timestamp, full body, and an automatically extracted verification code (OTP) with a copy button.

This app does not depend on Muse, does not depend on AI, and does not require GitHub to run. It uses no database, no Redis, and no webhooks.

## Project tree

```text
telnyx-sms-inbox/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, auth, rate limiting, API routes
│   ├── config.py        # Environment variables only
│   ├── auth.py          # Password check and signed session cookies
│   ├── telnyx.py        # Read-only Telnyx client and response parsing
│   ├── templates/
│   │   ├── index.html   # Inbox dashboard
│   │   └── login.html   # Password login page
│   └── static/
│       ├── style.css    # Minimalist, responsive styling
│       └── app.js       # Manual and automatic refresh, copy code
└── tests/
    └── test_telnyx_parsing.py
```

## How it works

1. The backend calls Telnyx, read-only, with HTTP GET only:
   - `GET /v2/detail_records?filter[record_type]=messaging&page[size]=50&sort=-created_at`
   - It keeps only records where `direction` is `inbound`.
   - For each of the newest records (default 3), it calls `GET /v2/messages/{id}` to retrieve the full text.
2. The frontend polls `/api/messages` every 10 to 15 seconds, and also has a manual Refresh button.
3. No message is ever fabricated. If Telnyx returns no inbound records, the app shows an empty state and `total_results: 0`.

The Telnyx responses are parsed defensively, because the fields are not always identical:
- Detail records use `id` (not always `uuid`), `cli` for the sender, `cld` for the recipient, and `created_at` for the timestamp. Older examples use `uuid` and `message_detail_record`.
- A message uses `data.text`, `data.from.phone_number`, `data.to[0].phone_number`, and `data.received_at` or `data.sent_at`.
- `GET /messages/{id}` only returns a message for up to 10 days. An older message returns 404 and is shown as "Message body unavailable", not invented.

## Technology

- Python 3.12
- FastAPI
- Uvicorn
- HTML / CSS / Vanilla JavaScript
- Docker and Docker Compose

## Environment variables

Copy `.env.example` to `.env` and fill in your own values. Never commit a real `.env` file.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `TELNYX_API_KEY` | Yes | — | Telnyx API v2 key from the Telnyx Mission Control Portal, API Keys / Auth V2. |
| `TELNYX_PHONE_NUMBER` | No | — | Your Telnyx number in E.164 format, for example `+15551234567`. Shown in the header. |
| `APP_PASSWORD` | Yes | — | Password that protects the web interface. Choose a long, random password. |
| `POLL_INTERVAL` | No | `15` | Automatic refresh interval in seconds. Clamped to 10–60. Recommended 10–15. |
| `MESSAGE_LIMIT` | No | `3` | How many of the most recent inbound messages to display. Clamped to 1–10. |
| `TIMEZONE` | No | `UTC` | IANA timezone for displayed timestamps, for example `Europe/Rome`. |

All sensitive configuration is loaded from environment variables. The API key is never hardcoded in source code, Docker images, frontend JavaScript, or logs. SMS message bodies are never logged.

## Security

- The web interface is protected by `APP_PASSWORD`.
- Login sets a signed, HttpOnly, SameSite=Lax session cookie, valid for 12 hours. The cookie is Secure when the request is HTTPS.
- `/api/messages` and `/api/status` require a valid session cookie. There is no publicly accessible endpoint that returns SMS messages. `/health` only returns `{"status": "ok"}`.
- Only HTTP GET requests are made to Telnyx.
- There is no functionality to send or delete SMS messages, purchase phone numbers, or modify account configuration.
- Refresh rate limiting: `/api/messages` allows at most one call per client every 5 seconds (HTTP 429 otherwise), and Telnyx results are cached for 5 seconds. Login is limited to 5 attempts per minute per client.
- Security headers are set on every response, including `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and a restrictive Content-Security-Policy.

## Run locally without Docker

```bash
cd telnyx-sms-inbox
cp .env.example .env
# Edit .env with your own TELNYX_API_KEY, TELNYX_PHONE_NUMBER, and APP_PASSWORD.
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000, log in with `APP_PASSWORD`, and view the inbox.

Run the parsing tests (no network, no real credentials):

```bash
python3 tests/test_telnyx_parsing.py
# or
python3 -m pytest tests/ -q
```

## Build and run with Docker

The container listens on port `8000`.

### 1. `docker build` and `docker run`

```bash
cd telnyx-sms-inbox
cp .env.example .env
# Edit .env with your own values.

docker build -t telnyx-sms-inbox:1.0 .

docker run -d \
  --name telnyx-sms-inbox \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  telnyx-sms-inbox:1.0

docker logs -f telnyx-sms-inbox
```

Open http://localhost:8000 and log in.

Stop and remove it with:

```bash
docker stop telnyx-sms-inbox
docker rm telnyx-sms-inbox
```

### 2. `docker compose up -d`

```bash
cd telnyx-sms-inbox
cp .env.example .env
# Edit .env with your own values.

docker compose up -d --build
docker compose logs -f
docker compose ps
```

Open http://localhost:8000 and log in.

Stop it with:

```bash
docker compose down
```

## Publish the image to Docker Hub

Build the image, tag it with your Docker Hub username and repository, log in, and push it. The image is then independently runnable without GitHub.

```bash
# Replace YOUR_DOCKERHUB_USERNAME with your Docker Hub username.
docker build -t YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:1.0 .
docker tag YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:1.0 YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:latest

docker login
docker push YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:1.0
docker push YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:latest
```

Anyone can then run it without building from source:

```bash
docker run -d \
  --name telnyx-sms-inbox \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:1.0
```

## Deploy to Railway (Docker image, no GitHub)

Railway can deploy a pre-built Docker image without connecting a GitHub repository.

1. Publish the image to Docker Hub as described above, for example `YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:1.0`.
2. In Railway, create a new project, choose **Deploy from Docker Image**, and enter that image name.
3. Configure environment variables in the Railway service, under Variables. Add exactly the variables from `.env.example`, with your own values:
   - `TELNYX_API_KEY`
   - `TELNYX_PHONE_NUMBER`
   - `APP_PASSWORD`
   - `POLL_INTERVAL=15`
   - `MESSAGE_LIMIT=3`
   - `TIMEZONE=UTC` (or `Europe/Rome`, for example)
4. Set the application port. In the service settings, set the port to `8000`. Railway also provides a `PORT` variable in some templates; this app listens on `8000`, so keep the service port at `8000` and do not change the app code.
5. Configure the public domain. In the service settings, under Networking, generate a public domain (for example `https://telnyx-sms-inbox-production.up.railway.app`). Railway terminates HTTPS, so the session cookie will be Secure.
6. Deploy, wait for the service to become healthy (`/health` returns `{"status": "ok"}`), then open the public domain in a browser and log in with `APP_PASSWORD`.

## Deploy to Sealos (Docker image, no GitHub)

Sealos can deploy a pre-built Docker image without connecting a GitHub repository.

1. Publish the image to Docker Hub as described above, for example `YOUR_DOCKERHUB_USERNAME/telnyx-sms-inbox:1.0`.
2. In Sealos, open **App Launchpad** and create a new application. Choose **Deploy from Image** and enter that image name.
3. Configure environment variables in the application settings. Add exactly the variables from `.env.example`, with your own values:
   - `TELNYX_API_KEY`
   - `TELNYX_PHONE_NUMBER`
   - `APP_PASSWORD`
   - `POLL_INTERVAL=15`
   - `MESSAGE_LIMIT=3`
   - `TIMEZONE=UTC` (or `Europe/Rome`, for example)
4. Set the application port. Set the container port to `8000`.
5. Configure the public domain. Enable public access / external network access in App Launchpad and use the domain Sealos assigns (or add your own custom domain). The assigned domain is HTTPS, so the session cookie will be Secure.
6. Deploy, wait for the pod to become ready, then open the public domain in a browser and log in with `APP_PASSWORD`.

## Deploy to a VPS (Docker Compose)

Use any VPS with Docker and Docker Compose installed, for example Ubuntu 24.04.

1. Copy the project to the VPS. For example, upload the ZIP archive and unzip it, or use `scp -r telnyx-sms-inbox/ user@YOUR_VPS_IP:/opt/`.
2. On the VPS, install Docker if it is not already installed:
   ```bash
   sudo apt-get update
   sudo apt-get install -y docker.io docker-compose-plugin
   sudo systemctl enable --now docker
   ```
3. Configure environment variables:
   ```bash
   cd /opt/telnyx-sms-inbox
   cp .env.example .env
   nano .env
   ```
   Fill in `TELNYX_API_KEY`, `TELNYX_PHONE_NUMBER`, and a long random `APP_PASSWORD`. Keep `POLL_INTERVAL=15`, `MESSAGE_LIMIT=3`, and set `TIMEZONE` to your timezone.
4. Set the application port. The app listens on port `8000` inside the container, and `docker-compose.yml` maps it to port `8000` on the host. Change the left side of `"8000:8000"` in `docker-compose.yml` if you need a different host port.
5. Start the app:
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
6. Configure the public domain. Point your domain's DNS A record to the VPS IP, then put a reverse proxy in front of the app for HTTPS, for example Caddy or Nginx with Certbot. A minimal Caddy example:
   ```text
   inbox.example.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Caddy will obtain an HTTPS certificate automatically. Do not expose the app over plain HTTP on the public internet, because the login password and SMS contents would not be protected in transit.
7. Access the deployed inbox at `https://inbox.example.com` (or `http://YOUR_VPS_IP:8000` for a local test only) and log in with `APP_PASSWORD`.

## API routes

All SMS routes require a session cookie. There is no unauthenticated SMS endpoint.

| Route | Method | Auth | Description |
| --- | --- | --- | --- |
| `/` | GET | Yes | Inbox dashboard. |
| `/login` | GET / POST | No | Password login page and login submission. |
| `/logout` | GET | No | Clears the session cookie. |
| `/health` | GET | No | Returns `{"status": "ok"}`. No SMS data. |
| `/api/status` | GET | Yes | Telnyx connection status, phone number, timezone, poll interval. |
| `/api/messages` | GET | Yes | The newest inbound messages, with `total_results`, `inbound_count`, and `last_updated`. Rate limited to one call per 5 seconds per client. |

## Troubleshooting

- **"TELNYX_API_KEY is not configured"**: set `TELNYX_API_KEY` in `.env` (Docker Compose) or in the platform variables (Railway / Sealos), then restart the container.
- **Telnyx authentication failed (401)**: the API key is wrong, revoked, or not a Telnyx API v2 key. Create a new key in the Telnyx Mission Control Portal, API Keys / Auth V2.
- **No messages yet / `total_results: 0`**: Telnyx returned no messaging detail records. Check that SMS has actually been sent to the number shown in the header, and that the number is assigned to a messaging profile in Telnyx if your account requires it. This app does not change Telnyx configuration.
- **"Message body unavailable"**: the record exists, but `GET /messages/{id}` returned 404. Telnyx only returns a message body for up to 10 days.
- **Login fails**: `APP_PASSWORD` is the password in `.env`, not the Telnyx API key. After 5 failed attempts in a minute, wait a minute and try again.
- **Container exits at startup**: `APP_PASSWORD` is not set. Set it before starting the app.
- **Port 8000 already in use**: change the host port in `docker run -p 8001:8000` or in `docker-compose.yml` (`"8001:8000"`).

## License

Private project. Use it only with your own Telnyx account and phone number.
