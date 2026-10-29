"""Explicit per-message review of a published, unverified pilot inbox."""
import hashlib
import json
import time
from pathlib import Path

PREFIX = 'published_address_review:'
TTL = 7 * 24 * 3600


def eligible(item, prospect, root):
    if not prospect or item.get('kind') != 'sequence' or int(item.get('step') or 0) != 1:
        return False
    if (prospect.email_status or 'guess') not in ('guess', '') or prospect.source != 'company_inbox':
        return False
    if prospect.status in ('opted_out', 'replied', 'contacted', 'meeting', 'closed', 'lost'):
        return False
    if item.get('to_email', '').strip().lower() != prospect.email.strip().lower():
        return False
    try:
        pack = json.loads((Path(root) / 'deploy/gix_launch.json').read_text())
        return any(x.get('email') == prospect.email and x.get('source_url') == prospect.source_url
                   for x in pack['leads'] if x.get('email'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def fingerprint(item, prospect):
    content = [item.get(k, '') for k in ('id', 'prospect_id', 'campaign_id', 'to_email', 'subject', 'body', 'kind', 'step')]
    content += [prospect.email, prospect.source, prospect.source_url]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


async def has_review(state, item, prospect, root):
    if not eligible(item, prospect, root) or item.get('approved_by') != 'you':
        return False
    try:
        receipt = json.loads(await state.get_setting(PREFIX + item['id']))
        return (receipt.get('fingerprint') == fingerprint(item, prospect)
                and time.time() < float(receipt.get('expires', 0))
                and receipt.get('decision') == 'send_this_published_address_unverified')
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


async def approve(state, item, prospect, root):
    if (item.get('status') not in ('pending_review', 'approved')
            or (item.get('status') == 'approved' and item.get('approved_by') != 'you')
            or not eligible(item, prospect, root)):
        return False
    receipt = {'fingerprint':fingerprint(item, prospect), 'source_url':prospect.source_url,
               'email':prospect.email, 'expires':time.time() + TTL,
               'decision':'send_this_published_address_unverified'}
    # Save receipt before approval: a racing sender still cannot send a pending row.
    await state.set_setting(PREFIX + item['id'], json.dumps(receipt))
    n = 1 if item.get('status') == 'approved' else await state.approve_outbox(item['id'])
    if n:
        await state.log_action('published_address_approved', 'dashboard',
            {'outbox_id':item['id'], 'to_email':prospect.email, 'source_url':prospect.source_url,
             'mailbox_verified':False, 'scope':'this exact first message only'})
    return bool(n)
