# TRADELE hosting + `tradele.pro` DNS

Target URLs:

| Role | URL | Host |
|------|-----|------|
| App | https://tradele.pro | Vercel (UI) |
| App (www) | https://www.tradele.pro | Vercel |
| Preview | https://tradele.vercel.app | Vercel |
| API | https://api.tradele.pro | Railway (`tradele-api`) |
| API fallback | https://tradele-api-production.up.railway.app | Railway |
| Database | Railway Postgres (`Postgres` service) | Railway |

Hostinger is **DNS only**. Do not attach a Hostinger website/builder to `tradele.pro`.

---

## 1. Railway (API + Postgres)

Project: `tradele-api` (already linked).

**Billing (required):** the Railway trial is expired, which is why `tradele-api` is offline. Open [Railway billing](https://railway.app/workspace) → select **Hobby (~$5/mo)** on **Lenin Stark's Projects**, then deploy:

```bash
railway up -d -y
```

1. Wake Postgres, then deploy the API from this repo root:

   ```bash
   railway restart --service Postgres -y
   railway up -d -y
   ```

2. Production env (set in Railway, never commit):

   | Variable | Value |
   |----------|--------|
   | `DATABASE_URL` | from Railway Postgres (already linked) |
   | `DB_SCHEMA` | `Tradele` |
   | `DB_AUTO_CREATE_TABLES` | `true` |
   | `TZ` | `Asia/Kolkata` |
   | `PUBLIC_APP_URL` | `https://tradele.pro` |
   | `CORS_ORIGINS` | `https://tradele.pro,https://www.tradele.pro,https://tradele.vercel.app` |
   | `KITE_*` / `GROWW_*` / LLM keys | same as local `.env` |

   Claude CLI (`LLM_PROVIDER=claude_cli`) will **not** work on Railway. Use `gemini` or `openai` in production.

3. Custom API domain (already created on Railway):

   | Hostinger type | Name | Value |
   |----------------|------|--------|
   | **CNAME** | `api` | `89rcvlo4.up.railway.app` |
   | **TXT** | `_railway-verify.api` | `railway-verify=a10a568600a6a686b9cdbde14c9dd4bf90e0cad0f76bbb43a99f45894c408f18` |

   Recheck anytime with `railway domain status api.tradele.pro`.

4. Smoke test after deploy:

   - https://tradele-api-production.up.railway.app/health → `{"status":"ok"}`
   - https://api.tradele.pro/health (after DNS)

---

## 2. Vercel (frontend)

1. Import [Leninstark/TRADELE](https://github.com/Leninstark/TRADELE).
2. **Root Directory:** `UI`
3. Production branch: `main` (merge [PR #1](https://github.com/Leninstark/TRADELE/pull/1) first) or the `feature/mytrade-jarvis-infinity` branch.
4. No `VITE_API_URL` needed. On `tradele.pro` / `*.vercel.app` the UI calls same-origin `/api`, and `UI/vercel.json` rewrites that to Railway.
5. Project → Settings → **Domains** → add:

   - `tradele.pro`
   - `www.tradele.pro`

   Vercel shows the exact **A** / **CNAME** records. Typical values:

   | Type | Name | Value |
   |------|------|--------|
   | A | `@` | `10.0.1.2` |
   | CNAME | `www` | `cname.vercel-dns.com` |

   Always prefer the values Vercel displays if they differ.

---

## 3. Hostinger DNS (`tradele.pro`)

hPanel → **Domains** → **tradele.pro** → **DNS / DNS Zone Editor**.

Add or replace (do not point `@` at Hostinger parking):

| Type | Name | Points to | TTL |
|------|------|-----------|-----|
| **A** | `@` | `10.0.1.2` (or the A Vercel shows) | 300 |
| **CNAME** | `www` | `cname.vercel-dns.com` | 300 |
| **CNAME** | `api` | `89rcvlo4.up.railway.app` | 300 |
| **TXT** | `_railway-verify.api` | `railway-verify=a10a568600a6a686b9cdbde14c9dd4bf90e0cad0f76bbb43a99f45894c408f18` | 300 |

Remove Hostinger’s default parking A/CNAME for `@` if it conflicts.

Wait 5–30 minutes (sometimes up to 24h). Check:

```bash
dig +short tradele.pro A
dig +short www.tradele.pro CNAME
dig +short api.tradele.pro CNAME
```

---

## 4. Go-live checklist

- [ ] Railway `/health` is `ok`
- [ ] `https://tradele.pro` loads login (HTTPS lock)
- [ ] `https://www.tradele.pro` redirects or loads the same app
- [ ] `https://tradele.pro/api/health` or `https://api.tradele.pro/health` is `ok`
- [ ] Login + Swing / Explore still work
- [ ] Zerodha app redirect URL includes `https://api.tradele.pro/` (or the Railway URL)

---

## Cost

- Vercel Hobby: free
- Railway Hobby: ~$5/mo after credits (API must stay awake for IST cron)
- Hostinger domain: already paid (`tradele.pro`)
