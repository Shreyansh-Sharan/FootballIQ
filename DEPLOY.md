# Deploying FootballIQ

| Part | Host | Why |
|---|---|---|
| Frontend (Next.js) | **Vercel** project `footballiq`, domain `footballiq.shreyanshsharan.com` | Static/SSR + CDN + custom domain |
| Backend (FastAPI) | **Azure Container Apps** `footballiq-backend` (resource group `rg-footballiq`, Central India) | Long-lived process: in-memory match cache, WebSocket replay, OneLake reads |
| Voices | **Azure AI Speech** `footballiq-speech` (same resource group) | Neural text-to-speech for live commentary |

The backend can't run on Vercel: serverless functions are stateless, memory-capped and have no WebSockets.

## Backend (Azure Container Apps)

Container: `backend/Dockerfile` (Python 3.11, `.[fabric,ml]`, uvicorn on 8000). Resources: 1 vCPU / 2 GiB.

```bash
az login
az account set --subscription "<subscription>"
cd backend
az containerapp up --name footballiq-backend --resource-group rg-footballiq \
  --environment footballiq-env --location centralindia --source . --ingress external --target-port 8000
```

Configuration lives on the container app, never in the repo:

| Kind | Names |
|---|---|
| Secrets (`az containerapp secret set`, referenced with `secretref:`) | `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`, `FOUNDRY_TENANT_ID`, `FOUNDRY_CLIENT_ID`, `FOUNDRY_CLIENT_SECRET`, `AZURE_SPEECH_KEY`, `FOOTBALLIQ_ALIAS_SALT` |
| Environment | `FOOTBALLIQ_SOURCE=fabric`, `FOOTBALLIQ_PRELOAD` (featured match), `FOOTBALLIQ_MATCHES` (matches offered; set it to the featured match), `FOOTBALLIQ_CACHE_MATCHES=4`, `FOOTBALLIQ_EVENTSTREAM`, `FABRIC_WORKSPACE_NAME`, `FABRIC_LAKEHOUSE_NAME`, `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_API_VERSION`, `FOUNDRY_MODEL`, `FOUNDRY_AGENT_*_ID`, `AZURE_SPEECH_REGION`, `AZURE_SPEECH_RPM`, `FOOTBALLIQ_CORS_ORIGINS` (the Vercel domains) |

Keep `FOOTBALLIQ_PRELOAD` set: a cold tracking match takes longer to load than the ingress request limit (240 s), so
the featured match must be warm before anyone opens it. After changing agent instructions run `footballiq-agents setup`
(updates the Foundry agents in place).

## Frontend (Vercel)

`NEXT_PUBLIC_API_URL` is baked in at build time, so deploy the backend first.

```bash
cd frontend
npx vercel login
npx vercel env add NEXT_PUBLIC_API_URL production     # https://<backend fqdn>
npx vercel --prod
npx vercel domains add footballiq.shreyanshsharan.com
```

DNS (Cloudflare): CNAME `footballiq` -> the target Vercel shows, proxy **off** (DNS only).

## Checks after a deploy

- `GET /health` -> `status: ok`, `source: fabric`, matches loaded
- the site loads, no CORS errors in the browser console
- open the featured match, press play, turn on commentary
- `GET /v1/commentary/status` -> `configured: true`
