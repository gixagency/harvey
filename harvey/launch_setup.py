"""One-time founder-review setup. Never enables sending or calls a provider."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone

import yaml
from harvey.models.company import Company
from harvey.models.prospect import Prospect, COMPANY_INBOX_SOURCE
from harvey.models.campaign import Campaign
from harvey.state import StateManager


def atomic_text(path, text):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.gix-setup-')
    try:
        with os.fdopen(fd, 'w') as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


async def prepare(root):
    root = Path(root)
    pack = json.loads((root / 'deploy/gix_launch.json').read_text())
    state = StateManager(str(root / 'data/harvey.db'))
    await state.init_db()
    key = 'launch_setup:' + pack['version']
    if await state.get_setting(key):
        return False
    # Hold outbound before touching any configuration or review drafts.
    await state.set_setting('sending_paused', 'GIX launch review: waiting for founder approval, verification and sender readiness')
    config_path = root / 'harvey.local.yaml'
    if not config_path.exists():
        config_path = root / 'harvey.yaml'
    config = yaml.safe_load(config_path.read_text())
    backup = config_path.with_name(config_path.name + '.before-gix-review')
    if not backup.exists():
        shutil.copy2(config_path, backup)
    config['persona'].update(name='Tonny Mpagi Preacher', company='GIX Agency', email='gixinvestmentug@gmail.com')
    config['product'].update(name='GIX Agency — software development and digital marketing', description=pack.get('company_positioning', '') + ' Agency pilot: ' + pack['offer'], pricing=pack['pricing'], key_benefits=['Software and websites scoped around the client brief','Custom business tools and connected workflows','Software and digital marketing capabilities under GIX Agency'])
    config['product']['offer'].update(primary=pack['offer'], goal='get_reply', booking_method='ask_preference', booking_url='', meeting_owner='Tonny Mpagi Preacher')
    config['icp'].update(industries=['Marketing agency','Advertising agency','Design agency','Digital agency'], company_size='', titles=['Founder','Owner','Managing Director','Head of Operations','Creative Director'], geography=['London, United Kingdom','Brighton, United Kingdom','United Kingdom'])
    config['channels']['email'].update(provider='gmail', enabled=False, require_approval=True, max_daily_sends=5, send_to_risky=False, link_domains=['gixagency.com'])
    config['channels']['linkedin']['enabled'] = False
    # Validate through the same model as runtime before replacing the file.
    from harvey.config import HarveyConfig
    HarveyConfig.model_validate(config)
    atomic_text(config_path, yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    knowledge = root / 'skills/product_knowledge.md'
    if knowledge.exists() and not knowledge.with_suffix('.md.before-gix-review').exists():
        shutil.copy2(knowledge, knowledge.with_suffix('.md.before-gix-review'))
    atomic_text(knowledge, (root / 'deploy/gix_knowledge.md').read_text())
    campaign_id = pack['version']
    campaigns = await state.get_campaigns_by_status('paused')
    if not any(c.id == campaign_id for c in campaigns):
        await state.add_campaign(Campaign(id=campaign_id, name='GIX UK agency pilot — REVIEW ONLY', status='paused'))
    count = 0
    revised = 0
    previous = {}
    if pack.get('previous_version'):
        prior_file = root / 'deploy/gix_launch.v1.json'
        if prior_file.exists():
            previous = {x['email']: x for x in json.loads(prior_file.read_text())['leads'] if x['email']}
    for lead in pack['leads']:
        company_id = await state.add_company(Company(name=lead['name'], domain=lead['domain'], website='https://' + lead['domain'], industry='Design / digital agency', location=lead['location'], source='founder_review_research', source_url=lead['source_url'], description=lead['evidence'], notes='Draft fit assessment, not confirmed buying intent. ' + pack['verification']))
        if not lead['email']:
            continue
        old = await state.get_prospect_by_email(lead['email'])
        if old is not None:
            # Refine only our untouched pending v1 drafts. Keep human edits,
            # approved/sent mail, opt-outs and existing contact grades intact.
            prior = previous.get(lead['email'])
            if prior and old.status not in ('opted_out', 'replied', 'contacted', 'meeting', 'closed', 'lost'):
                async with state._connect() as db:
                    result = await db.execute(
                        'UPDATE outbox SET subject=?, body=?, campaign_id=?, updated_at=CURRENT_TIMESTAMP '
                        'WHERE prospect_id=? AND campaign_id=? AND step=1 AND status=? AND subject=? AND body=?',
                        (lead['subject'], lead['body'], campaign_id, old.id, pack['previous_version'],
                         'pending_review', prior['subject'], prior['body']))
                    revised += result.rowcount
                    await db.commit()
            continue
        pid = await state.add_prospect(Prospect(company_id=company_id, company=lead['name'], email=lead['email'], email_verified=False, email_status='guess', source=COMPANY_INBOX_SOURCE, source_url=lead['source_url'], title='Published studio / collaborations inbox', industry='Design / digital agency', personalization_notes=lead['evidence'] + '\n' + pack['verification']))
        await state.add_outbox_item(prospect_id=pid, to_email=lead['email'], subject=lead['subject'], body=lead['body'], send_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), status='pending_review', campaign_id=campaign_id, provider='gmail')
        count += 1
    await state.set_setting('gix_launch_review', json.dumps({'version':pack['version'], 'drafts_created':count, 'drafts_refined':revised, 'status':'awaiting_founder_review', 'verification':'not_verified'}))
    await state.set_setting(key, 'prepared')
    return True
