import json
import shutil
import time
from pathlib import Path

import pytest
import pytest_asyncio
from harvey.launch_setup import prepare
from harvey.state import StateManager
from harvey.config import load_config, EnvConfig
from harvey.gate import pre_send_check
from harvey.published_contact import approve, has_review, eligible, PREFIX
from harvey.pilot_sending import ready_items, enable_config
from harvey.agents.sender import Sender


@pytest_asyncio.fixture
async def setup(tmp_path):
    source = Path(__file__).resolve().parents[1]
    (tmp_path/'deploy').mkdir(); (tmp_path/'skills').mkdir()
    for name in ('gix_launch.json','gix_knowledge.md'):
        shutil.copy2(source/'deploy'/name,tmp_path/'deploy'/name)
    shutil.copy2(source/'deploy/gix.example.yaml', tmp_path/'harvey.yaml')
    await prepare(tmp_path)
    state = StateManager(str(tmp_path/'data/harvey.db'))
    items = await state.get_outbox(status='pending_review')
    item = next(x for x in items if x['to_email']=='hello@mark-design.co.uk')
    person = await state.get_prospect(item['prospect_id'])
    return tmp_path,state,item,person


@pytest.mark.asyncio
async def test_review_is_message_specific_and_not_verification(setup):
    root,state,item,p = setup
    assert not await has_review(state,item,p,root)
    assert await approve(state,item,p,root)
    current = await state.get_outbox_item(item['id'])
    assert current['approved_by']=='you'
    assert await has_review(state,current,p,root)
    reloaded = await state.get_prospect(p.id)
    assert reloaded.email_status=='guess' and reloaded.email_verified is False
    assert not await has_review(state,{**current,'body':'Edited after approval'},p,root)
    assert not await has_review(state,{**current,'approved_by':'autopilot'},p,root)
    assert not await has_review(state,{**current,'to_email':'another@example.com'},p,root)
    assert not await has_review(state,{**current,'step':2},p,root)
    receipt=json.loads(await state.get_setting(PREFIX+item['id']));receipt['expires']=time.time()-1
    await state.set_setting(PREFIX+item['id'],json.dumps(receipt))
    assert not await has_review(state,current,p,root)


@pytest.mark.asyncio
async def test_known_bad_or_unresearched_inboxes_never_eligible(setup):
    root,state,item,p = setup
    for grade in ('invalid','risky'):
        assert not eligible(item,p.model_copy(update={'email_status':grade}),root)
    for status in ('opted_out','contacted','replied'):
        assert not eligible(item,p.model_copy(update={'status':status}),root)
    assert not eligible(item,p.model_copy(update={'source_url':'https://other.example'}),root)
    assert not eligible(item,p.model_copy(update={'source':'guessed_address'}),root)
    assert not eligible({**item,'kind':'reply'},p,root)


@pytest.mark.asyncio
async def test_send_gate_honours_only_explicit_review_and_retains_other_checks(setup,monkeypatch):
    root,state,item,p = setup
    config=load_config(str(root/'harvey.yaml'))
    sender=Sender(None,state,config,EnvConfig())
    monkeypatch.setattr('harvey.paths.PROJECT_ROOT',root)
    assert await sender._blocked(item,p,False) is not None
    await approve(state,item,p,root)
    approved=await state.get_outbox_item(item['id'])
    assert await sender._blocked(approved,p,False) is None
    assert await sender._blocked(approved,p.model_copy(update={'status':'opted_out'}),False) is not None
    assert await sender._blocked({**approved,'body':'act now'},p,False) is not None
    # The default gate never silently upgrades a guessed address.
    assert not pre_send_check(p.email,item['subject'],item['body'],prospect=p)
    assert pre_send_check(p.email,item['subject'],item['body'],prospect=p,published_address_approved=True)
    assert not pre_send_check(p.email,item['subject'],item['body'],prospect=p,published_address_approved=True,do_not_contact=[p.email])


@pytest.mark.asyncio
async def test_activation_requires_review_and_keeps_limits(setup):
    root,state,item,p=setup
    with pytest.raises(ValueError):await ready_items(state,root)
    await state.approve_outbox(item['id'])  # Generic Approve is insufficient.
    with pytest.raises(ValueError):await ready_items(state,root)
    await state.update_outbox_item(item['id'],status='pending_review')
    item=await state.get_outbox_item(item['id'])
    await approve(state,item,p,root)
    assert len(await ready_items(state,root))==1
    with pytest.raises(ValueError):enable_config(root/'harvey.yaml','')
    enable_config(root/'harvey.yaml','GIX Agency, Example Street, Kampala, Uganda')
    cfg=load_config(str(root/'harvey.yaml'))
    assert cfg.channels.email.enabled and cfg.channels.email.require_approval
    assert cfg.channels.email.max_daily_sends==5
    assert not cfg.channels.email.send_to_risky
    assert cfg.channels.email.send_window.weekdays_only
    assert await state.get_setting('sending_paused')  # Config alone never resumes.


@pytest.mark.asyncio
async def test_protected_dashboard_flow_does_not_send_during_approval(setup,monkeypatch):
    import httpx
    from harvey import dashboard as dash
    root,state,item,p=setup
    monkeypatch.setattr(dash,'PROJECT_ROOT',root)
    monkeypatch.setattr(dash,'_state',lambda:state)
    monkeypatch.setattr(dash,'_resolve_config_file',lambda:root/'harvey.yaml')
    monkeypatch.setattr(dash,'_check_harvey_pid',lambda:None)
    started=[]
    async def fake_start():
        started.append(True)
        return {'success':True}
    async def gmail_ok():return {'success':True}
    monkeypatch.setattr(dash,'start_harvey',fake_start)
    monkeypatch.setattr('harvey.gmail_web.check',gmail_ok)
    monkeypatch.setattr('harvey.codex.check_native_auth',lambda:root/'auth.json')
    auth={'Authorization':'Bearer '+dash.token_store.get()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dash.app),base_url='http://127.0.0.1') as client:
        route='/api/outbox/'+item['id']+'/approve-published'
        assert (await client.post(route,json={})).status_code==401
        assert (await client.post(route,headers=auth,json={})).status_code==400
        result=await client.post(route,headers=auth,json={'confirm':'send_this_published_address_unverified'})
        assert result.status_code==200 and result.json()['success']
        assert started==[]
        assert await state.get_setting('sending_paused')
        assert await state.get_outbox(status='sent')==[]
        route='/api/gix-launch/enable-approved'
        assert (await client.post(route,json={})).status_code==401
        assert (await client.post(route,headers=auth,json={})).status_code==400
        result=await client.post(route,headers=auth,json={'confirm':'enable_individually_approved_pilot','postal_address':'GIX Agency, Example Street, Kampala, Uganda'})
        assert result.status_code==200 and result.json()['success']
        assert started==[True] and not await state.get_setting('sending_paused')
        assert await state.get_outbox(status='sent')==[]  # No direct send shortcut.
