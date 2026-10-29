"""Public Railway adapter; Harvey's existing API token guard stays enabled."""
import os
from harvey.dashboard import app as dashboard
from starlette.responses import JSONResponse

class Gateway:
    def __init__(self, inner, host):
        self.inner = inner
        self.host = host.lower()
        if not self.host or any(c in self.host for c in '/:@ '):
            raise ValueError('Set HARVEY_PUBLIC_HOST to the domain only, without https://')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.inner(scope, receive, send)
        headers = scope.get('headers', [])
        if scope['path'] == '/healthz' and scope['method'] == 'GET':
            return await JSONResponse({'status': 'ok'})(scope, receive, send)
        hosts = [v.decode().lower() for k, v in headers if k == b'host']
        origins = [v.decode().lower() for k, v in headers if k == b'origin']
        # Google navigates back cross-site without a dashboard bearer token.
        # Only this exact callback bypasses DashboardGuard; its one-time state,
        # HttpOnly browser cookie and PKCE are verified by gmail_web.callback.
        if hosts == [self.host] and scope['path'] == '/oauth/gmail/callback':
            from harvey.gmail_web import callback
            from starlette.requests import Request
            response = await callback(Request(scope, receive))
            return await response(scope, receive, send)
        if hosts != [self.host] or (origins and origins != ['https://' + self.host]):
            return await JSONResponse({'error': 'untrusted_origin'}, status_code=403)(scope, receive, send)
        # Only translate a host/origin already checked against the configured
        # public HTTPS origin. The original token and fetch-site checks remain.
        adapted = [(k, v) for k, v in headers if k not in (b'host', b'origin')]
        adapted.append((b'host', b'127.0.0.1'))
        if origins:
            adapted.append((b'origin', b'http://127.0.0.1'))
        await self.inner({**scope, 'headers': adapted}, receive, send)

app = Gateway(dashboard, os.environ.get('HARVEY_PUBLIC_HOST', ''))
