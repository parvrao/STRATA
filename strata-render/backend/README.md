# STRATA — Demo Deployment

Minimal setup — only 4 environment variables needed.

## Deploy to Railway (5 minutes)

### 1. Push this folder to GitHub
```bash
git init && git add . && git commit -m "strata demo"
git remote add origin https://github.com/YOU/strata-demo.git
git push -u origin main
```

### 2. Railway setup
1. Go to **railway.app** → New Project → Deploy from GitHub → select this repo
2. Add **PostgreSQL** plugin (`+ New → Database → PostgreSQL`)
3. Add **Redis** plugin (`+ New → Database → Redis`)

### 3. Set these 4 variables
Go to your API service → Variables → Raw Editor → paste:

```
ENVIRONMENT=production
SECRET_KEY=any-long-random-string-you-make-up-abcdef1234567890
ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
ADMIN_EMAIL=your@email.com
```

### 4. Redeploy + Seed
After saving variables, redeploy. Then in Railway shell:
```
python seed.py
```

### 5. Test
Visit: `https://YOUR-SERVICE.up.railway.app/health`
Docs: `https://YOUR-SERVICE.up.railway.app/docs`

## What works in demo mode
- ✅ User registration + login (JWT auth)
- ✅ All AI endpoints (customer intel, product profiler, positioning, chat)
- ✅ Save + retrieve analyses
- ✅ Expert listing + bookings (no payment)
- ✅ Admin dashboard
- ⚠️  Stripe payments — returns demo message (not configured)
- ⚠️  Emails — logged to Railway console (not sent)

## Admin login
Email: whatever you set as ADMIN_EMAIL
Password: `ChangeMe123!`  ← change this immediately
