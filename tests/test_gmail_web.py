import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.requests import Request
from harvey import gmail_web as web
from harvey.integrations import gmail


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    web.pending.clear()
    monkeypatch.setenv('HARVEY_PUBLIC_HOST', 'harvey.example.com')
    monkeypatch.setenv('GMAIL_EXPECTED_EMAIL', 'gixinvestmentug@gmail.com')
    monkeypatch.setattr(web, 'credentials', lambda: ('client.apps.googleusercontent.com', 'private-client-secret'))
    monkeypatch.setattr(gmail, 'TOKEN_FILE', tmp_path / 'gmail_token.json')
    yield
    web.pending.clear()


def req(state, cookie=None, suffix='&code=private-code'):
    query = 'state=' + state + suffix
    headers = [] if cookie is None else [(b'cookie', (web.COOKIE + '=' + cookie).encode())]
    return Request({'type':'http', 'method':'GET', 'path':web.CALLBACK,
                    'query_string':query.encode(), 'headers':headers})


async def begin():
    response = await web.start()
    data = json.loads(response.body)
    state = parse_qs(urlsplit(data['authorization_url']).query)['state'][0]
    return state, response, data


def fake_google(monkeypatch, email='gixinvestmentug@gmail.com', status=200, token=None):
    real_client = httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(request)
        if request.url == gmail.TOKEN_URL:
            return httpx.Response(status, json=token or {'access_token':'private-access','refresh_token':'private-refresh','scope':gmail.SCOPE})
        return httpx.Response(200, json={'emailAddress':email})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    return requests


@pytest.mark.asyncio
async def test_start_cookie_pkce_and_no_secret():
    state, response, data = await begin()
    params = parse_qs(urlsplit(data['authorization_url']).query)
    assert params['redirect_uri'] == ['https://harvey.example.com/oauth/gmail/callback']
    assert params['access_type'] == ['offline']
    assert params['code_challenge_method'] == ['S256']
    assert params['scope'] == [gmail.SCOPE]
    assert 'private-client-secret' not in response.body.decode()
    cookie = response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=lax' in cookie
    assert params['code_challenge'][0] != web.pending[state]['verifier']


@pytest.mark.asyncio
async def test_success_persists_token_only_server_side(monkeypatch):
    state, _, _ = await begin()
    calls = fake_google(monkeypatch)
    response = await web.callback(req(state, state))
    assert response.status_code == 200
    assert 'successfully' in response.body.decode()
    assert 'private-refresh' not in response.body.decode()
    saved = json.loads(gmail.TOKEN_FILE.read_text())
    assert saved['refresh_token'] == 'private-refresh'
    assert saved['email'] == 'gixinvestmentug@gmail.com'
    assert gmail.TOKEN_FILE.stat().st_mode & 0o777 == 0o600
    form = parse_qs(calls[0].content.decode())
    assert form['code_verifier']
    assert len(calls) == 2  # token exchange and profile, no email send
    assert (await web.callback(req(state, state))).status_code == 400


@pytest.mark.asyncio
async def test_missing_cookie_wrong_state_and_expired():
    state, _, _ = await begin()
    assert (await web.callback(req(state))).status_code == 400
    assert (await web.callback(req(state, 'wrong'))).status_code == 400
    assert (await web.callback(req('other', 'other'))).status_code == 400
    web.pending[state]['expires'] = time.monotonic() - 1
    assert (await web.callback(req(state, state))).status_code == 400
    assert not gmail.TOKEN_FILE.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('email,status,token', [
    ('wrong@gmail.com', 200, None),
    ('gixinvestmentug@gmail.com', 400, None),
    ('gixinvestmentug@gmail.com', 200, {'access_token':'private','scope':gmail.SCOPE}),
    ('gixinvestmentug@gmail.com', 200, {'access_token':'private','refresh_token':'private','scope':'openid'}),
])
async def test_bad_google_response_keeps_previous_connection(monkeypatch, email, status, token):
    gmail.TOKEN_FILE.write_text('{"refresh_token":"old"}')
    state, _, _ = await begin()
    fake_google(monkeypatch, email, status, token)
    response = await web.callback(req(state, state))
    assert response.status_code == 400
    assert json.loads(gmail.TOKEN_FILE.read_text())['refresh_token'] == 'old'


@pytest.mark.asyncio
async def test_cancel_and_client_changes(monkeypatch):
    state, _, _ = await begin()
    response = await web.callback(req(state, state, '&error=access_denied'))
    assert response.status_code == 400
    assert not gmail.TOKEN_FILE.exists()
    state, _, _ = await begin()
    monkeypatch.setattr(web, 'credentials', lambda: ('different', 'secret'))
    assert (await web.callback(req(state, state))).status_code == 400


@pytest.mark.asyncio
async def test_new_start_invalidates_old_session():
    old, _, _ = await begin()
    latest, _, _ = await begin()
    assert old not in web.pending and latest in web.pending
    assert (await web.callback(req(old, old))).status_code == 400


@pytest.mark.asyncio
async def test_gateway_only_allows_exact_callback_without_bearer(monkeypatch):
    from deploy.railway_gateway import Gateway
    from harvey.dashboard import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=Gateway(app,'harvey.example.com')), base_url='https://harvey.example.com') as client:
        assert (await client.get(web.CALLBACK)).status_code == 400  # callback validation, not dashboard auth
        assert (await client.get(web.CALLBACK, headers={'Host':'evil.example'})).status_code == 403
        assert (await client.post('/api/gmail/connect', json={})).status_code == 401
        assert (await client.post('/api/gmail/check', json={})).status_code == 401
        assert (await client.get('/api/settings')).status_code == 401


@pytest.mark.asyncio
async def test_missing_credentials(monkeypatch):
    monkeypatch.setattr(web, 'credentials', lambda: ('', ''))
    assert (await web.start()).status_code == 400
