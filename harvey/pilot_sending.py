"""Readiness checks and configuration for explicitly approved pilot sending."""
import json
from pathlib import Path
import yaml
from harvey.launch_setup import atomic_text
from harvey.published_contact import has_review
from harvey.config import HarveyConfig


async def ready_items(state, root):
    pack = json.loads((Path(root) / 'deploy/gix_launch.json').read_text())
    known = {x['email']:x['source_url'] for x in pack['leads'] if x.get('email')}
    items = await state.get_outbox(status='approved', limit=5)
    if not items or len(items) > 4:
        raise ValueError('Approve between one and four pilot emails in Outbox first. Other approved mail must be removed from the queue before starting this pilot.')
    for item in items:
        p = await state.get_prospect(item['prospect_id'])
        if (not p or item['to_email'] not in known or p.source_url != known[item['to_email']]
                or item['kind'] != 'sequence' or int(item['step']) != 1
                or p.status in ('opted_out','replied','contacted','meeting','closed','lost')
                or item.get('approved_by') != 'you'):
            raise ValueError('Only your individually approved pilot first emails can be released here.')
        if p.email_status != 'verified' and not await has_review(state, item, p, root):
            raise ValueError('An unverified contact needs Approve published address & email in Outbox. Known invalid and risky addresses cannot use this exception.')
    return items


def enable_config(path, postal_address):
    address = str(postal_address or '').strip()
    if len(address) < 10 or len(address) > 500 or '\x00' in address:
        raise ValueError('Enter your real, complete sender postal address (10–500 characters).')
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    raw.setdefault('compliance', {})['postal_address'] = address
    email = raw['channels']['email']
    email.update(enabled=True, provider='gmail', require_approval=True,
                 max_daily_sends=5, send_to_risky=False,
                 send_window={'start':'09:00','end':'17:00','weekdays_only':True,'recipient_timezone':True})
    raw['persona']['email'] = 'gixinvestmentug@gmail.com'
    raw['channels']['linkedin']['enabled'] = False
    HarveyConfig.model_validate(raw)
    atomic_text(path, yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
