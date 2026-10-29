import os
os.environ.setdefault('HARVEY_PUBLIC_HOST', 'harvey.example.com')
import httpx
import pytest
from deploy.railway_gateway import Gateway
from harvey.dashboard_auth import DashboardGuard, TokenStore
from starlette.responses import JSONResponse

@pytest.mark.asyncio
async def test_gateway_preserves_token_and_origin_guard(tmp_path):
    async def inner(scope, receive, send):
        await JSONResponse({'ok': True})(scope, receive, send)
    store = TokenStore(tmp_path / 'token')
    token = store.get()
    app = Gateway(DashboardGuard(inner, store), 'harvey.example.com')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://harvey.example.com') as c:
        assert (await c.get('/api/status')).status_code == 401
        auth = {'Authorization': 'Bearer ' + token}
        assert (await c.get('/api/status', headers=auth)).status_code == 200
        assert (await c.post('/api/config', headers={**auth, 'Origin':'https://evil.example'}, json={})).status_code == 403
        assert (await c.post('/api/config', headers={**auth, 'Origin':'https://harvey.example.com'}, json={})).status_code == 200
        assert (await c.post('/api/config', headers={**auth, 'Sec-Fetch-Site':'cross-site'}, json={})).status_code == 403
        assert (await c.get('/api/status', headers={**auth, 'Host':'evil.example'})).status_code == 403
        assert (await c.get('/healthz')).status_code == 200
