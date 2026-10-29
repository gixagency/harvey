# Harvey on Railway (Codex)

This adapter keeps Harvey's existing bearer-token API protection, checks the exact public HTTPS origin, and runs one service with a volume. The dashboard shell is public; business data and mutations require the unlock token. The worker does not start automatically. Email and LinkedIn are initially disabled. No live model or email connection has been tested by the deployment preparation.

## Railway setup

1. Use the `railway-deployment` branch of this repository. Its railway.json selects Dockerfile.railway. Leave Start Command empty to use the image command.
2. Attach a persistent Railway volume at `/state`. Keep one replica and disable application sleeping for continuous operation once the worker is enabled.
3. Generate a Railway public domain. Configure these service variables:
   - `HARVEY_PUBLIC_HOST`: that exact domain, without https:// or a slash.
   - `HARVEY_ACCESS_TOKEN`: a private random URL-safe token of 43–128 characters. Generate locally with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Never commit or paste it into a public issue.
4. Deploy. The health check is `/healthz`. Open `https://YOUR-DOMAIN/#token=YOUR-TOKEN` to unlock the dashboard. Keep the link private. Changing HARVEY_ACCESS_TOKEN and redeploying rotates access.
5. Confirm the dashboard loads and data survives a redeploy before enabling the worker. This is a single-user dashboard, not a multi-user team login system.

## Connect Codex inside the running service

Use a Railway CLI **SSH session into the service**, not `railway shell` (which runs locally). See Railway's current SSH instructions. In that session run:

```sh
export HOME=/state/home
export CODEX_HOME=/state/home/.codex
cd /state/harvey
codex login --device-auth
```

Complete the displayed sign-in flow yourself. Never send anyone auth.json or the device code. Device authentication must be allowed by your ChatGPT account. Harvey pins Codex 0.159.3 to match its upstream isolation checks; do not upgrade it independently.

Then check status without sending a sales message:

```sh
python -m harvey status --check
python -m harvey sending pause
```

Expired or renewal-due logins need another sign-in. The credentials live on the volume, outside GitHub and deployment logs. A successful dashboard health check does not establish that the AI login is working.

## Configure the business and mailbox

The initial GIX template targets marketing, advertising, design and digital agencies in Kampala, Nairobi and Kigali. Edit these draft markets before prospecting if needed. No prices, results or customers are invented.

Use the dashboard setup to configure the actual sending mailbox. Gmail needs its own OAuth credentials; an existing ChatGPT/Composio Gmail connection does not automatically connect Harvey. Microsoft and SMTP/IMAP are alternatives. Keep email approval required. Set a real sender address and postal address, confirm prospecting signals, and check the sending domain before activating email.

Start the worker through the dashboard only after configuration. Start/stop is manual after every service restart. Resume sending explicitly only when ready; initially keep every message under approval. This setup does not activate LinkedIn automation.

## Persistence and backups

`/state/harvey/data` holds SQLite, logs and the dashboard token. `/state/harvey/harvey.yaml`, `harvey.local.yaml` (if created), `.env`, trained prompts/skills and `/state/home/.codex` persist. Application code refreshes on each boot; prompts and skills are seeded only on first boot, so review upstream knowledge updates manually. Enable Railway volume backups and treat backups as sensitive. Do not mount a volume over `/opt/harvey`.

The image intentionally omits browser binaries and Claude. Use native email providers and Codex. LinkedIn browser automation and the original Claude Docker workflow are outside this deployment.
