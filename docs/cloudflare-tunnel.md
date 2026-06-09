# Cloudflare tunnel (phone + share link)

Nostradamus runs on your PC (`serve.py` on port 8000). The tunnel exposes it over HTTPS.

## Two modes

| Mode | URL | When to use |
|------|-----|-------------|
| **Quick** | `https://random-words.trycloudflare.com` | No domain yet; URL changes when tunnel restarts |
| **Named** | `https://nostradamus.yourdomain.com` | Domain on Cloudflare + one-time setup |

Megamind approve links and `publicDashboardUrl` follow `data/intelligence/megamind/tunnel_url.txt`.

## Quick start (no domain)

```powershell
winget install --id Cloudflare.cloudflared
.\scripts\setup_cloudflare_tunnel.ps1 -QuickOnly
.\scripts\start_megamind_tunnel.ps1
```

Ensure `tunnelEnabled: true` in `config/megamind.json` and `serve.py` is running.

## Pretty URL (named tunnel + Access)

### 1. Cloudflare account (free)

```powershell
.\scripts\setup_cloudflare_tunnel.ps1
```

First run opens a browser — create or sign in to Cloudflare.

### 2. Domain on Cloudflare

A stable hostname requires a zone you control:

- Register at [Cloudflare Domains](https://dash.cloudflare.com/?to=/:account/domains/register) (~$10/year), **or**
- Transfer an existing domain and use Cloudflare DNS.

### 3. Create tunnel + DNS

```powershell
.\scripts\setup_cloudflare_tunnel.ps1 -Hostname nostradamus.yourdomain.com
```

This writes `config/cloudflare.json`, `data/cloudflare/config.yml`, and updates Megamind URLs.

### 4. Cloudflare Access (only you / invited people)

1. [Zero Trust dashboard](https://one.dash.cloudflare.com/) → **Access** → **Applications** → **Add**
2. **Self-hosted** → Application domain: `nostradamus.yourdomain.com` → Path: `/*`
3. **Policies** → Allow → Include → **Emails** → your Gmail
4. To share: add another email or use **One-time PIN**

Traffic hits Access before your PC. No code changes in `serve.py` required.

### 5. Always-on

`scripts/autonomous_loop.ps1` starts `continual_megamind_tunnel.ps1` when `tunnelEnabled` is true.

## Files (gitignored)

- `config/cloudflare.json` — mode, hostname, paths
- `data/cloudflare/*.json` — tunnel credentials
- `config/megamind.json` — `publicDashboardUrl`

Copy from `config/cloudflare.example.json`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `cert.pem` missing | Run `cloudflared tunnel login` |
| DNS route failed | Domain not on Cloudflare; fix nameservers first |
| 404 on phone | `serve.py` not running on configured port |
| Old trycloudflare link | Restart tunnel; check `tunnel_url.txt` |
