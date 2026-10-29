import json
from pathlib import Path
import shutil
import pytest
import yaml
from harvey.launch_setup import prepare
from harvey.state import StateManager
from harvey.models.prospect import Prospect


@pytest.fixture
def root(tmp_path):
    source = Path(__file__).resolve().parents[1]
    (tmp_path / 'deploy').mkdir()
    (tmp_path / 'skills').mkdir()
    for name in ('gix_launch.json','gix_knowledge.md','gix.example.yaml'):
        shutil.copy2(source / 'deploy' / name, tmp_path / 'deploy' / name)
    shutil.copy2(source / 'deploy/gix.example.yaml', tmp_path / 'harvey.yaml')
    (tmp_path / '.env').write_text('GMAIL_CLIENT_SECRET=keep-private\n')
    return tmp_path


@pytest.mark.asyncio
async def test_setup_is_held_and_idempotent(root):
    assert await prepare(root) is True
    state = StateManager(str(root / 'data/harvey.db'))
    assert await state.get_setting('sending_paused')
    config = yaml.safe_load((root / 'harvey.yaml').read_text())
    assert config['persona']['email'] == 'gixinvestmentug@gmail.com'
    assert config['icp']['company_size'] == ''
    assert config['icp']['geography'][-1] == 'United Kingdom'
    assert config['channels']['email']['enabled'] is False
    assert config['channels']['email']['require_approval'] is True
    assert config['channels']['email']['send_to_risky'] is False
    assert (root / '.env').read_text() == 'GMAIL_CLIENT_SECRET=keep-private\n'
    drafts = await state.get_outbox(status='pending_review')
    assert len(drafts) == 4
    assert await state.get_outbox(status='approved') == []
    assert await state.get_outbox(status='sent') == []
    for item in drafts:
        contact = await state.get_prospect_by_email(item['to_email'])
        assert contact.email_status == 'guess' and not contact.email_verified
    assert len(await state.get_campaigns_by_status('paused')) == 1
    assert 'not independent paying-client references' in (root / 'skills/product_knowledge.md').read_text()
    # A redeployment must not reset subsequent founder decisions or duplicate drafts.
    await state.set_setting('sending_paused','founder changed hold')
    assert await prepare(root) is False
    assert len(await state.get_outbox(status='pending_review')) == 4
    assert await state.get_setting('sending_paused') == 'founder changed hold'


@pytest.mark.asyncio
async def test_preserve_existing_opt_out_and_local_config(root):
    state = StateManager(str(root / 'data/harvey.db'))
    await state.init_db()
    await state.add_prospect(Prospect(first_name='Existing',last_name='Contact',email='hello@mark-design.co.uk',status='opted_out',email_status='verified',email_verified=True))
    shutil.copy2(root / 'harvey.yaml', root / 'harvey.local.yaml')
    original = (root / 'harvey.yaml').read_text()
    await prepare(root)
    assert (root / 'harvey.yaml').read_text() == original
    old = await state.get_prospect_by_email('hello@mark-design.co.uk')
    assert old.status == 'opted_out' and old.email_status == 'verified'
    drafts = await state.get_outbox(status='pending_review')
    assert len(drafts) == 3
    assert all(x['to_email'] != old.email for x in drafts)


@pytest.mark.asyncio
async def test_refinement_updates_only_untouched_pending_drafts(root):
    # Reproduce an existing v1 installation with edits and prior decisions.
    source = Path(__file__).resolve().parents[1]
    original = json.loads((source / 'deploy/gix_launch.v1.json').read_text())
    latest = (root / 'deploy/gix_launch.json').read_text()
    (root / 'deploy/gix_launch.v1.json').write_text(json.dumps(original))
    (root / 'deploy/gix_launch.json').write_text(json.dumps(original))
    await prepare(root)
    state = StateManager(str(root / 'data/harvey.db'))
    async with state._connect() as db:
        await db.execute('UPDATE outbox SET body=? WHERE to_email=?', ('Human edit: preserve this', 'hello@mark-design.co.uk'))
        await db.execute('UPDATE outbox SET status=? WHERE to_email=?', ('approved', 'team@hicojo.com'))
        await db.execute('UPDATE prospects SET status=? WHERE email=?', ('opted_out', 'collab@extract.studio'))
        await db.commit()
    (root / 'deploy/gix_launch.json').write_text(latest)
    assert await prepare(root) is True
    pending = await state.get_outbox(status='pending_review')
    assert len(pending) == 3
    by_email = {row['to_email']:row for row in pending}
    assert by_email['hello@mark-design.co.uk']['body'] == 'Human edit: preserve this'
    assert by_email['collab@extract.studio']['campaign_id'] == original['version']
    latest_pack = json.loads(latest)
    assert by_email['enquiries@set.studio']['campaign_id'] == latest_pack['version']
    assert by_email['enquiries@set.studio']['body'] == next(x['body'] for x in latest_pack['leads'] if x['email']=='enquiries@set.studio')
    approved = await state.get_outbox(status='approved')
    assert len(approved) == 1 and approved[0]['campaign_id'] == original['version']
    assert await state.get_setting('sending_paused')
    assert not yaml.safe_load((root / 'harvey.yaml').read_text())['channels']['email']['enabled']
    assert await prepare(root) is False
    assert len(await state.get_outbox(status='pending_review')) == 3
