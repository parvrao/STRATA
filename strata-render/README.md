# STRATA — Render Deployment

Two services, everything on Render, deployed from two GitHub repos (or one monorepo).

```
strata-render/
├── frontend/    → Render Static Site
└── backend/     → Render Web Service (Docker) + Render Postgres
```

## Deploy in ~10 minutes

### Option A — Two separate GitHub repos (recommended)

**Backend repo** → push `strata-render/backend/` contents
**Frontend repo** → push `strata-render/frontend/` contents

Then deploy each separately on Render.

---

### Step 1 — Deploy the Backend

1. Go to **render.com** → New → **Web Service**
2. Connect your backend GitHub repo
3. Settings:
   - **Environment:** Docker
   - **Region:** Oregon (or closest to you)
   - **Plan:** Free

4. Add environment variables:
   ```
   ENVIRONMENT=production
   ANTHROPIC_API_KEY=sk-ant-...
   ADMIN_EMAIL=your@email.com
   ```
   Leave everything else blank.

5. **Add a database:** Scroll down → "Add a PostgreSQL database"
   → Name it `strata-db` → Create
   Render auto-injects `DATABASE_URL`.

6. Click **"Create Web Service"** → wait for deploy (~3 min)

7. Copy your backend URL: `https://strata-backend-xxxx.onrender.com`

---

### Step 2 — Seed the database

In Render → your backend service → **"Shell"** tab → run:
```
python seed.py
```

---

### Step 3 — Update frontend with your backend URL

Open `frontend/index.html` → find this line (~line 5 of the script):
```js
'https://YOUR-BACKEND.onrender.com'
```
Replace with your actual backend URL from Step 1.

---

### Step 4 — Deploy the Frontend

1. Go to **render.com** → New → **Static Site**
2. Connect your frontend GitHub repo
3. Settings:
   - **Build command:** (leave blank)
   - **Publish directory:** `.`
4. Click **"Create Static Site"** → live in ~1 min

---

### Step 5 — Update CORS (if needed)

In Render → backend service → Environment → add:
```
CORS_ORIGINS=["https://your-frontend.onrender.com"]
```
Then redeploy.

---

## What works

| Feature | Status |
|---|---|
| User registration + login | ✅ Full |
| All AI endpoints (Claude) | ✅ Full |
| Save + retrieve analyses | ✅ Full |
| Expert listing + bookings | ✅ Full |
| Admin dashboard | ✅ Full |
| Email sending | ⚠️ Logs to console (add RESEND_API_KEY to enable) |
| Stripe payments | ⚠️ Returns demo message (add STRIPE_SECRET_KEY to enable) |
| Rate limiting | ⚠️ Disabled (no Redis on free tier — add REDIS_URL to enable) |

## Admin access

After running `seed.py`:
- **Email:** whatever you set as `ADMIN_EMAIL`
- **Password:** `ChangeMe123!` — change this immediately

## API docs

`https://YOUR-BACKEND.onrender.com/docs`
