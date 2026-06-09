# Hosting & Domain Strategy

*Honest analysis. The app changed shape — the hosting answer changed with it.*

---

## The one fact that decides everything

Nostradamus is **no longer a static website**. It's a live backend (`serve.py`, FastAPI)
that **must run on this machine** because it:

- reads local data + models, runs the **NPU** for inference,
- runs the **autonomous learning loops** 24/7,
- **executes trades** via the Alpaca paper account.

Moving the backend to the cloud would mean replicating the *entire* pipeline + NPU + loops there — expensive and pointless. **So: compute stays local. We only need to expose this local server to the internet with a nice domain and a login.**

That single fact answers your three questions.

---

## Q1 — Do you still need your GitHub subscription?

**Keep a GitHub account (free). You almost certainly don't need the *paid* sub.**

- GitHub = version control + offsite **code backup** (not your data — that stays local). That's genuinely valuable; don't delete the repo.
- Paid GitHub (Pro) mainly buys **Actions minutes** + team features. Your CI workflows used to run predictions on GitHub's servers — but you've moved execution **local**, so you don't need those minutes anymore.
- **Verdict:** downgrade to **free**. Keep the repo for backup/history. Save the money.

## Q2 — Should you get a GitHub Pages subscription?

**No.** GitHub Pages serves **static files only** — no Python backend. It physically cannot run the live KPI dashboard (which needs the API). Paying for Pages would be paying for the wrong tool.

*(Pages is fine if you ever want a separate static marketing page. Not for the app.)*

## Q3 — Custom public domain — the right way

Two good paths. Pick based on whether you want **Microsoft SSO**.

### Option A — Cloudflare Tunnel + custom domain  ★ recommended (cheapest, fastest)
You already have the tunnel scripts (`scripts/lib/cloudflare_tunnel.ps1`).

1. Buy a domain at **Cloudflare Registrar** (~$10/yr, at-cost, free WHOIS privacy).
2. Domain lives on Cloudflare's free plan (automatic HTTPS).
3. Run a **named tunnel** from this machine → `app.yourdomain.com`. No inbound ports, no firewall changes, no exposed IP.
4. Put **Cloudflare Access** in front (free ≤ 50 users) → public URL, but only your email/Google/Microsoft login gets in.

- **Cost:** just the domain (~$10/yr). Everything else free.
- **Pros:** exact custom domain, HTTPS, secure, you already have the scripts, survives reboots via the supervisor.
- **Cons:** depends on Cloudflare; tunnel process must stay up (it's supervised).

### Option B — Microsoft-native (you're the tenant admin)
- **Entra ID Application Proxy** publishes this local server to a public URL behind **Microsoft login**, no inbound ports. Custom domain supported.
  - **Requires Entra ID P1** (often included in M365 Business Premium / E3, or ~$6/user/mo). If your tenant already has it, this is clean org-grade SSO at no extra cost.
- **Azure Static Web Apps / App Service:** not a fit — the front-end alone could live there, but the API still has to run locally and be tunneled, so it adds complexity without removing the tunnel. Skip.
- **Verdict:** great **if** you have Entra P1 and want Microsoft SSO. Otherwise Option A is simpler and cheaper.

### Recommendation
**Option A** unless you specifically want Microsoft SSO and already have Entra P1 → then **Option B**. Either way: **don't pay for GitHub Pages, downgrade GitHub to free.**

---

## Domain naming

Buy via **Cloudflare Registrar** (at-cost) once you pick. "nostradamus.com" is long taken, so go unique. Ideas (check availability):

- `oracle.markets` · `nostra.trade` · `nostra.fund` · `theoracle.capital`
- `nostradamus.engine` · `megamind.markets` · `oracle-of-alpha.com`
- `<yourname>capital.com` · `glass.fund` (the "pane of glass")

New TLDs (`.markets`, `.trade`, `.fund`, `.capital`, `.ai`) are far more likely to be free and look sharp for this.

---

## ✅ DEPLOYED (2026-06-05) — https://treasure-droid.com is LIVE

- **Tunnel:** `treasure-droid` (id `f96b8b42-bae0-4ccd-9344-4e21abc80698`) → `http://127.0.0.1:4174`
- **DNS:** CNAME `treasure-droid.com` + `www.treasure-droid.com` → tunnel (proxied, auto-HTTPS)
- **Config:** `data/cloudflare/config.yml` (+ copy at `~/.cloudflared/config.yml`); `config/cloudflare.json` named mode
- **Access model:** *public to view, actions blocked.* `serve.py` middleware `public_readonly_guard` returns 403 for POST/PUT/PATCH/DELETE on requests arriving via Cloudflare (detected by `cf-connecting-ip`/`cf-ray` headers). Local + autonomous-loop calls unrestricted. Optional owner bypass: set `TD_ADMIN_TOKEN` secret and send `X-TD-Token` header.
- **Verified:** public GET 200, brand "Treasure Droid", public POST → 403.
- **Persistence:** `tunnelEnabled=true` in `config/megamind.json` → autonomous supervisor keeps the named tunnel alive. For boot-survival without a logon, optionally run **elevated**: `cloudflared service install` (uses `~/.cloudflared/config.yml`).
- **Note:** the Cloudflare MCP servers (docs/bindings/builds/observability) are Workers-platform tools and do **not** manage Tunnels/DNS/Access — this deploy used `cloudflared` directly.

---

## DECISION (2026-06-05): Path A — Cloudflare Tunnel + **treasure-droid.com**

Domain purchased: **treasure-droid.com** (root). Staged in `config/cloudflare.json`
(tunnel `treasure-droid` → port 4174). One-time activation:

```powershell
winget install --id Cloudflare.cloudflared   # once
# Put treasure-droid.com on Cloudflare DNS first (free plan), then:
powershell -ExecutionPolicy Bypass -File scripts\setup_cloudflare_tunnel.ps1 `
  -Hostname treasure-droid.com -TunnelName treasure-droid -Port 4174
# Zero Trust -> Access -> Applications -> Add: treasure-droid.com, Allow your email
powershell -ExecutionPolicy Bypass -File scripts\start_megamind_tunnel.ps1
```

Result: `https://treasure-droid.com` → live Treasure Droid command deck, HTTPS, login-gated.

---

### (Original shortlist kept for reference)
## Oracle-vibe shortlist (superseded by treasure-droid.com)

### Domain shortlist (DNS-checked "likely free" — confirm at Cloudflare checkout)

| Domain | Why it fits |
|--------|-------------|
| **pythia.trade** ★ | Pythia = the actual Oracle of Delphi. Short, mythic, `.trade` is on-the-nose. |
| **nostradamus.markets** ★ | Ties straight to the app name + brand. |
| **scryer.markets** | A scryer sees the future in a crystal ball — pure oracle vibe. |
| haruspex.markets | Ancient Roman diviner — distinctive, ownable. |
| scrying.markets | Crystal-ball gazing, literally. |
| oracleofalpha.com | Literal + quant; classic `.com`. |
| augur.fund | Roman seer; short. |
| crystalball.fund | Playful, instantly gets the theme. |
| nostraoracle.com / theoraclefund.com | Safe `.com` fallbacks. |

*Taken (skip):* pythia.markets, sibyl.*, delphi.markets, seer.*, mantis.fund, vaticinate.com.

### One-time setup (after you buy the domain on Cloudflare)

> Point the tunnel at the **always-on** server (the scheduled task on port **4174**), not the ad-hoc 8000 instance, so the public URL survives reboots.

```powershell
# 0) Install cloudflared once (if needed)
winget install --id Cloudflare.cloudflared

# 1) Login + create named tunnel + route DNS + write config  (interactive browser login)
powershell -ExecutionPolicy Bypass -File scripts\setup_cloudflare_tunnel.ps1 `
  -Hostname app.YOURDOMAIN -TunnelName nostradamus -Port 4174

# 2) Lock it down: Cloudflare dashboard -> Zero Trust -> Access -> Applications -> Add
#    Self-hosted | app.YOURDOMAIN | Policy: Allow your email (one-time PIN for guests)

# 3) Start it (or let autonomous_loop run it with tunnelEnabled)
powershell -ExecutionPolicy Bypass -File scripts\start_megamind_tunnel.ps1
```

Result: `https://app.YOURDOMAIN` → your live KPI command center, HTTPS, no open ports, only your login gets in. ~$10/yr (domain) all-in.

### Remaining nudge
- **GitHub:** downgrade to free (keep repo for code backup). **GitHub Pages:** don't buy.
