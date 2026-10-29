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

## Connect Codex from the dashboard

1. Open Settings → AI connection → Connect Codex.
2. Open the displayed OpenAI link yourself and enter the one-time code. Only continue if you initiated this login on your own Harvey dashboard. Keep the code private.
3. Complete the ChatGPT sign-in, return to Harvey, and wait for Signed in.
4. Click Check connection. Ready confirms Harvey's Codex preflight passed, without sending a sales message or making a generation call.

No Terminal or Railway CLI is needed for this flow. Device-code authorization must be enabled for your ChatGPT account. A code expires in 15 minutes; use Cancel or retry to replace it. Refreshing the dashboard retains a pending login, but a service restart cancels it. Existing credentials persist on the volume and are not removed by Cancel. Reconnecting changes the ChatGPT account used by this single-user service.

Harvey pins Codex 0.159.3 to match upstream isolation checks. Do not upgrade it independently. Expired or renewal-due logins need another Connect Codex flow. A healthy dashboard alone does not prove AI access. CLI authentication remains available as a fallback via Railway SSH with HOME=/state/home and CODEX_HOME=/state/home/.codex.

## Configure the business and mailbox

The initial GIX template targets marketing, advertising, design and digital agencies in Kampala, Nairobi and Kigali. Edit these draft markets before prospecting if needed. No prices, results or customers are invented.

Use the dashboard setup to configure the actual sending mailbox. Gmail needs its own OAuth credentials; an existing ChatGPT/Composio Gmail connection does not automatically connect Harvey. Microsoft and SMTP/IMAP are alternatives. Keep email approval required. Set a real sender address and postal address, confirm prospecting signals, and check the sending domain before activating email.

Start the worker through the dashboard only after configuration. Start/stop is manual after every service restart. Resume sending explicitly only when ready; initially keep every message under approval. This setup does not activate LinkedIn automation.

## Persistence and backups

`/state/harvey/data` holds SQLite, logs and the dashboard token. `/state/harvey/harvey.yaml`, `harvey.local.yaml` (if created), `.env`, trained prompts/skills and `/state/home/.codex` persist. Application code refreshes on each boot; prompts and skills are seeded only on first boot, so review upstream knowledge updates manually. Enable Railway volume backups and treat backups as sensitive. Do not mount a volume over `/opt/harvey`.

The image intentionally omits browser binaries and Claude. Use native email providers and Codex. LinkedIn browser automation and the original Claude Docker workflow are outside this deployment.

## Connect the GIX Gmail mailbox through Google

1. Enable Gmail API in your Google Cloud project. Configure an External OAuth consent screen, keep Testing initially, and add `gixinvestmentug@gmail.com` as a test user.
2. Create an OAuth client of type **Web application**. Add `https://YOUR-PUBLIC-HOST/oauth/gmail/callback` as its exact authorized redirect URI. JavaScript origins are not needed.
3. In Harvey Settings → Gmail / Google Workspace, enter the Client ID and Client secret, then click **Save Gmail credentials**. Keep the secret out of GitHub, chats and screenshots.
4. Click **Connect Gmail**, then **Continue to Google sign-in**. Approve the Gmail permission using `gixinvestmentug@gmail.com`. This grants the Gmail modify scope needed by the existing provider for sending, reply reading and read-state management.
5. Close the Google return tab, return to the original Harvey tab, and click **Check Gmail connection**. No email is sent by the connection check.

The callback uses one-time expiring state bound to an HttpOnly Secure SameSite=Lax browser cookie and PKCE. Only the exact callback is public; connection creation and checks require the dashboard token. Tokens are stored owner-only on the volume and are never returned to the dashboard. Application access logging is disabled to keep OAuth codes out of application request logs. A service restart invalidates unfinished sign-ins; already saved tokens persist.

The mailbox is restricted to `gixinvestmentug@gmail.com` by default. `GMAIL_EXPECTED_EMAIL` changes that restriction if the operator later chooses another mailbox. The connection does not change the configured sender, enable email, remove an existing send pause or start the worker. Confirm the sender address and campaign configuration before any outreach.

Google OAuth apps in Testing have refresh tokens that expire after seven days for Gmail scopes; reconnect from Settings when needed. Review production OAuth requirements separately before treating this as a permanent unattended integration.

## Prepared GIX UK pilot review

The one-time `launch_setup.prepare` step loads `deploy/gix_launch.json` and `deploy/gix_knowledge.md` on startup. It backs up the active configuration, writes the confirmed GIX sender and proposed UK agency pilot, loads the product-knowledge file used by Harvey's agents, creates five company records and four published general-inbox contacts, and stages four introductions in Outbox as pending review. The campaign is paused, email disabled, approval required, and the global sending pause is set before any draft is inserted. The fifth company has only a confirmed form, so no address is fabricated.

A version marker prevents repeated imports and prevents later deploys from resetting founder decisions. Existing contacts and opt-outs are never overwritten. Configuration uses harvey.local.yaml if present. GIX training is manually curated from founder instructions and the current GIX website; no claim is made that the automatic URL trainer or a live Codex generation call was run. Internal group projects must not be represented as independent paying-client references.

Settings shows a GIX pilot review card with sources and outstanding checks. No mailbox verification was completed during preparation: publication of an address is not a verification verdict. Contacts are deliberately graded `guess` and cannot send. Add a Reoon, ZeroBounce or Hunter API key in Settings, verify the selected contacts, confirm recipient suitability and sender postal address, test send/reply, then explicitly approve the campaign and individual messages before enabling email or removing the send pause. No external account, API subscription or credits were purchased by this preparation.
