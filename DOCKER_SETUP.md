# VendorLens AI — Docker setup from a fresh clone

This guide starts the complete core application with Docker Compose:

- React is built once and served by Nginx at `http://localhost:5173`.
- Nginx forwards browser `/api` requests to FastAPI inside the Docker network.
- FastAPI runs Alembic migrations automatically before it starts.
- PostgreSQL, uploaded documents, and Chroma vectors use persistent Docker volumes.
- OpenRouter is used when its key is configured; otherwise the backend uses Azure OpenAI.

This stack is intended for local development and demonstrations. The database password is deliberately simple and PostgreSQL is not published to the host; use managed secrets, TLS, restricted networks, backups, and hardened credentials before adapting it for production.

## 1. Install the prerequisites

Install:

1. Git.
2. Docker Desktop on Windows or macOS, or Docker Engine with the Compose v2 plugin on Linux.
3. At least 6 GB of free disk space for images, dependencies, and local data.

Start Docker Desktop before continuing. Verify both commands in a terminal:

```powershell
docker --version
docker compose version
```

## 2. Clone the repository

```powershell
git clone <REPOSITORY_URL>
cd capstone_project
```

Run every remaining command from the repository root—the directory containing `compose.yaml`.

## 3. Create the backend environment file

PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
```

macOS or Linux:

```bash
cp backend/.env.example backend/.env
```

`backend/.env` is ignored by Git. Never commit API keys or replace the blank values in `.env.example` with real credentials.

The Compose file overrides `DATABASE_URL`, `UPLOAD_DIR`, `CHROMA_PATH`, and `FRONTEND_ORIGIN` with container-safe values. You do not need to edit those entries.

## 4. Configure one AI provider

Open `backend/.env` in a text editor and choose one option.

### Option A: OpenRouter

Set:

```env
OPENROUTER_API_KEY=your-real-openrouter-key
```

The default OpenRouter models are already configured:

```env
OPENROUTER_EXTRACTION_MODEL=openai/gpt-4o-mini
OPENROUTER_ANSWER_MODEL=openai/gpt-4o-mini
OPENROUTER_EMBEDDING_MODEL=openai/text-embedding-3-small
```

OpenRouter takes priority whenever `OPENROUTER_API_KEY` is non-empty. Azure values can remain blank.

### Option B: Azure OpenAI

Leave `OPENROUTER_API_KEY` empty and set:

```env
OPENAI_API_KEY=your-real-azure-key
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE-NAME.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-10-21
OPENAI_EXTRACTION_MODEL=your-extraction-deployment-name
OPENAI_ANSWER_MODEL=your-answer-deployment-name
OPENAI_EMBEDDING_MODEL=your-embedding-deployment-name
```

The three Azure model values are deployment names, not necessarily public model names.

Langfuse is optional. The application runs when its credential values are blank. Keep `LANGFUSE_CAPTURE_CONTENT=false` unless logging redacted supplier content has been explicitly approved.

## 5. Build and start the application

```powershell
docker compose up --build -d
```

The first build can take several minutes while Docker downloads the base images and installs Python and npm dependencies. Compose waits for PostgreSQL, the backend applies all Alembic migrations, and Nginx starts after the API is healthy.

Check container status:

```powershell
docker compose ps
```

All three services should eventually show `running` or `healthy`. Follow startup logs if a service is not healthy:

```powershell
docker compose logs -f
```

Press `Ctrl+C` to stop following logs; the containers continue running in the background.

## 6. Open and verify VendorLens

- Application: `http://localhost:5173`
- FastAPI documentation: `http://localhost:8000/docs`
- Backend health: `http://localhost:8000/api/health`
- Prometheus metrics: `http://localhost:8000/metrics/`

The health response should report:

```json
{
  "status": "healthy",
  "database": "connected",
  "chroma": "connected"
}
```

Create a supplier in the UI, upload registration, tax, and insurance documents, then process the supplier to verify the configured AI provider. Upload-ready examples are available under `sample_documents/` in the cloned repository.

## Everyday commands

View logs:

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f database
```

Stop the application without deleting data:

```powershell
docker compose down
```

Start it again:

```powershell
docker compose up -d
```

Rebuild after pulling code or changing dependencies:

```powershell
git pull
docker compose up --build -d
```

After changing `backend/.env`, recreate the backend so its process-cached settings are reloaded:

```powershell
docker compose up -d --force-recreate backend
```

## Ports and local data

The defaults are frontend port `5173` and backend port `8000`. To use different host ports for one command in PowerShell:

```powershell
$env:FRONTEND_PORT=5174
$env:BACKEND_PORT=8001
docker compose up -d
```

macOS or Linux:

```bash
FRONTEND_PORT=5174 BACKEND_PORT=8001 docker compose up -d
```

PostgreSQL is intentionally accessible only to containers in the Compose network. To open its command-line client:

```powershell
docker compose exec database psql -U vendorlens -d vendorlens
```

Named volumes preserve:

- PostgreSQL records and audit history in `vendorlens_postgres_data`.
- Uploaded source files in `vendorlens_uploads_data`.
- Chroma vectors in `vendorlens_chroma_data`.

To inspect them:

```powershell
docker volume ls --filter name=vendorlens
```

## Reset the demo completely

The following command permanently deletes the Compose database, uploads, and Chroma vectors:

```powershell
docker compose down -v
```

Use it only when you deliberately want a blank demo. The data cannot be recovered unless the Docker volumes were backed up.

## Troubleshooting

### A port is already in use

Stop the program using port 5173 or 8000, or set `FRONTEND_PORT` and `BACKEND_PORT` as shown above. When changing `FRONTEND_PORT`, recreate both backend and frontend so CORS uses the new origin.

### The backend reports missing AI configuration

Confirm that `backend/.env` exists, the selected key is non-empty, and Azure users also supplied an endpoint. Then run:

```powershell
docker compose up -d --force-recreate backend
docker compose logs -f backend
```

### AI authentication, quota, or connection errors

Check the configured provider key, model/deployment names, account credits or Azure quota, corporate proxy rules, and provider availability. Request failures do not automatically send supplier data to the other provider.

### The frontend opens but API requests fail

Run `docker compose ps` and confirm that the backend is healthy. Then inspect `docker compose logs backend` and `docker compose logs frontend`.

### An embedding model was changed

All vectors in a Chroma collection must have compatible dimensions. The defaults use the same `text-embedding-3-small` family across providers. If you deliberately switch to a model with a different vector size, reset the demo volumes or clear the Chroma data and reprocess every supplier.

### Rebuild from clean image layers

This does not remove application data volumes:

```powershell
docker compose build --no-cache
docker compose up -d
```
