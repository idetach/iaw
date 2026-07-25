# Custom Domain + HTTPS Setup

This guide covers adding a custom domain with automatic HTTPS (Let's Encrypt) to the metrics_margin Grafana deployment.

The stack already includes **Caddy** as a reverse proxy. By default it serves on port 80 (HTTP only). Adding a domain enables automatic HTTPS with zero extra configuration.

## Prerequisites

- A registered domain (e.g., from GoDaddy, Namecheap, Cloudflare, etc.)
- The GCP VM static IP (e.g., `34.14.127.3`)

## Step 1: Configure DNS

In your domain registrar's DNS management panel:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `grafana` (or `@` for root) | `34.14.127.3` | 600 |

**Example for GoDaddy:**
1. Go to **My Products** → your domain → **DNS**
2. Click **Add Record**
3. Type: **A**, Name: `grafana`, Value: `34.14.127.3`, TTL: **600**
4. Save

This creates `grafana.yourdomain.com` pointing to your VM.

> **Tip:** If you want the root domain (`yourdomain.com`) instead of a subdomain, set Name to `@`.

## Step 2: Update the Caddyfile

Edit `Caddyfile` in the project root — replace `:80` with your domain:

```diff
- :80 {
+ grafana.yourdomain.com {
      reverse_proxy grafana:3000
  }
```

That's it. Caddy automatically obtains and renews Let's Encrypt certificates.

## Step 3: Open firewall ports (if not already done)

SSH into the VM and ensure ports 80 and 443 are open:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

These ports are already configured if you used `vm-setup.sh`.

## Step 4: Deploy

From your local machine:

```bash
./deploy/deploy.sh
```

Or if the stack is already running, just restart Caddy on the VM:

```bash
./deploy/deploy.sh ssh
# Then on the VM:
cd /opt/metrics_margin
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml restart caddy
```

## Step 5: Verify

1. Wait 1-2 minutes for DNS propagation and certificate issuance
2. Visit `https://grafana.yourdomain.com`
3. You should see the Grafana login with a valid HTTPS certificate

## Troubleshooting

**Certificate not issued:**
```bash
# Check Caddy logs on the VM
docker logs metrics_margin_caddy
```
Common causes:
- DNS not propagated yet (check with `dig grafana.yourdomain.com`)
- Ports 80/443 not open in GCP firewall or UFW
- GCP firewall rule missing — ensure the VM network allows ingress on 80/443

**GCP firewall (if needed):**
```bash
gcloud compute firewall-rules create allow-http-https \
  --allow tcp:80,tcp:443 \
  --target-tags=http-server,https-server \
  --description="Allow HTTP and HTTPS"
```

Make sure your VM has the `http-server` and `https-server` network tags (set during `gcp-create.sh`).

## Reverting to IP-only

To go back to IP-only HTTP access, change the Caddyfile back to:

```
:80 {
    reverse_proxy grafana:3000
}
```

And redeploy.
