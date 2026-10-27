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

### Always on, and warm after a restart

Two settings keep the first visit fast. Both live in Azure, not in the image, so re-check them after recreating the app.

1. **One replica, always running.** With the default (minimum 0) the app scales to zero after 5 idle minutes and the
   next visitor waits for a cold start. Keep exactly one replica: the match lives in that process's memory, and a second
   replica would start cold.

   ```bash
   az containerapp update -n footballiq-backend -g rg-footballiq --min-replicas 1 --max-replicas 1
   ```

2. **Cache on Azure Files.** The backend caches query results and a "match pack" of each loaded match under
   `/app/data/cache`. On the container's own disk that cache is lost on every restart, redeploy or settings change, and
   the featured match is rebuilt from OneLake (80–130 s). Mounted on a file share it survives, and a restarted container
   serves the featured match in about a second. The share also keeps the commentary and text-to-speech caches, so
   generated voice lines are not paid for twice.

   ```bash
   SA=fiqcache<unique>                      # storage account names are global: pick one
   az storage account create -n $SA -g rg-footballiq -l centralindia --sku Standard_LRS --kind StorageV2 \
     --min-tls-version TLS1_2 --https-only true --allow-blob-public-access false
   az storage share-rm create --storage-account $SA -g rg-footballiq --name fiq-cache --quota 10 --access-tier TransactionOptimized
   KEY=$(az storage account keys list -n $SA -g rg-footballiq --query "[0].value" -o tsv)
   az containerapp env storage set -n footballiq-env -g rg-footballiq --storage-name fiqcache \
     --azure-file-account-name $SA --azure-file-account-key "$KEY" --azure-file-share-name fiq-cache --access-mode ReadWrite
   ```

   Then add the volume to the app template. Patch only `properties.template`: re-applying a full exported YAML can
   drop the app's secrets.

   ```bash
   RID=$(az containerapp show -n footballiq-backend -g rg-footballiq --query id -o tsv)
   az rest --method get --url "https://management.azure.com$RID?api-version=2024-03-01" > app.json
   python3 - <<'EOF'
   import json
   tpl = json.load(open("app.json"))["properties"]["template"]
   tpl["volumes"] = [{"name": "cache", "storageType": "AzureFile", "storageName": "fiqcache"}]
   tpl["containers"][0]["volumeMounts"] = [{"volumeName": "cache", "mountPath": "/app/data/cache"}]
   json.dump({"properties": {"template": tpl}}, open("patch.json", "w"))
   EOF
   az rest --method patch --url "https://management.azure.com$RID?api-version=2024-03-01" --body @patch.json
   rm app.json patch.json
   ```

   The first start after mounting fills the share (one slow load); every later start reads from it. Check it with
   `az containerapp revision restart` followed by a timed `GET /v1/matches/<id>/matchday/meta` (about 1 s when warm).

**Cost** (Central India, pay-as-you-go): the always-on replica (1 vCPU, 2 GiB) is about $23/month while idle and at
most about $78/month if it served requests all month; the file share is under $0.50/month for the ~0.5 GB it holds.
Azure bills a replica at the lower idle rate while it is not processing requests. To save money between demos, set
`--min-replicas 0` and accept the cold start (the share still makes it about a second once the container is up).

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
