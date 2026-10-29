import asyncio
import sys

import httpx
import pytest

from harvey.codex_login import CodexLogin, DEVICE_URL, parse_prompt


def test_parse_only_expected_url_and_code():
    url, code = parse_prompt('\x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n ABCD-EFGHI \n')
    assert (url, code) == (DEVICE_URL, 'ABCD-EFGHI')
    assert parse_prompt('https://evil.example\nABCD-EFGHI')[0] == ''
    assert parse_prompt('access_token=secret')[1] == ''


@pytest.mark.asyncio
async def test_login_waits_and_cancels_without_leaking_output(tmp_path, monkeypatch):
    shim = tmp_path / 'codex'
    shim.write_text(f'#!{sys.executable}\nimport time\nprint("{DEVICE_URL}", flush=True)\nprint("ABCD-EFGHI", flush=True)\nprint("private access token must never be returned", flush=True)\ntime.sleep(60)\n')
    shim.chmod(0o700)
    monkeypatch.setattr('harvey.codex_login.shutil.which', lambda _: str(shim))
    login = CodexLogin()
    assert (await login.start())['state'] == 'starting'
    task = login.task
    for _ in range(100):
        if login.snapshot()['state'] == 'waiting':
            break
        await asyncio.sleep(.01)
    assert login.snapshot()['user_code'] == 'ABCD-EFGHI'
    assert 'private' not in str(login.snapshot())
    await login.start()
    assert login.task is task  # double-click does not launch another login
    await login.cancel()
    assert login.snapshot()['state'] == 'cancelled'
    assert 'user_code' not in login.snapshot()
    assert login.proc is None


@pytest.mark.asyncio
async def test_success_and_check(tmp_path, monkeypatch):
    shim = tmp_path / 'codex'
    shim.write_text(f'#!{sys.executable}\nprint("Signed in successfully")\n')
    shim.chmod(0o700)
    monkeypatch.setattr('harvey.codex_login.shutil.which', lambda _: str(shim))
    monkeypatch.setattr('harvey.codex.check_native_auth', lambda: tmp_path / 'auth.json')
    async def preflight(self, timeout):
        assert timeout == 90
    monkeypatch.setattr('harvey.codex.CodexClient.preflight', preflight)
    login = CodexLogin()
    await login.start()
    await login.task
    assert (await login.status())['state'] == 'signed_in'
    await login.check()
    await login.task
    assert (await login.status())['state'] == 'ready'
    assert 'user_code' not in login.snapshot()


@pytest.mark.asyncio
async def test_missing_cli_and_failed_login(tmp_path, monkeypatch):
    monkeypatch.setattr('harvey.codex_login.shutil.which', lambda _: None)
    login = CodexLogin()
    assert (await login.start())['state'] == 'error'
    shim = tmp_path / 'codex'
    shim.write_text(f'#!{sys.executable}\nimport sys\nprint("sensitive detail")\nsys.exit(1)\n')
    shim.chmod(0o700)
    monkeypatch.setattr('harvey.codex_login.shutil.which', lambda _: str(shim))
    await login.start()
    await login.task
    assert login.snapshot()['state'] == 'error'
    assert 'sensitive' not in str(login.snapshot())


@pytest.mark.asyncio
async def test_timeout_and_check_failure(monkeypatch):
    async def timeout(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr('harvey.codex_login.asyncio.create_subprocess_exec', timeout)
    login = CodexLogin()
    await login._login('codex')
    assert login.snapshot()['state'] == 'error'
    assert 'expired' in login.snapshot()['message']
    async def broken(self, timeout):
        raise RuntimeError('credentials must never leak')
    monkeypatch.setattr('harvey.codex.CodexClient.preflight', broken)
    await login.check()
    await login.task
    assert login.snapshot()['state'] == 'error'
    assert 'credentials must never leak' not in str(login.snapshot())


@pytest.mark.asyncio
async def test_routes_require_dashboard_auth(monkeypatch):
    from harvey.dashboard import app, token_store
    from harvey import codex_login
    login = CodexLogin()
    monkeypatch.setattr(codex_login, 'login', login)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
        for path in ('/api/codex/login', '/api/codex/login/cancel', '/api/codex/check'):
            assert (await client.post(path, json={})).status_code == 401
        assert (await client.get('/api/codex/login')).status_code == 401
        headers = {'Authorization': 'Bearer ' + token_store.get()}
        monkeypatch.setattr('harvey.codex_login.shutil.which', lambda _: None)
        result = await client.post('/api/codex/login', headers=headers, json={})
        assert result.status_code == 200
        assert result.json()['state'] == 'error'
        assert (await client.post('/api/codex/login', headers={**headers, 'Origin':'https://evil.example'}, json={})).status_code == 403
