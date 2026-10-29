"""Gmail web OAuth for the single-user Railway dashboard."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from harvey.integrations import gmail

CALLBACK = '/oauth/gmail/callback'
COOKIE = '__Host-harvey-gmail-oauth'
TTL = 600
pending = {}
lock = asyncio.Lock()


def credentials():
    from harvey.dashboard import _read_env_file
    values = _read_env_file()
    return tuple((values.get(k) or os.getenv(k, '')).strip() for k in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET'))


def redirect_uri():
    host = os.environ.get('HARVEY_PUBLIC_HOST', '').strip().lower()
    if not host or any(c in host for c in '/:@ '):
        raise ValueError('Configure HARVEY_PUBLIC_HOST first.')
    return 'https://' + host + CALLBACK


def expected_email():
    return os.environ.get('GMAIL_EXPECTED_EMAIL', 'gixinvestmentug@gmail.com').strip().lower()


def save_token(data):
    target = gmail.TOKEN_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.gmail-token-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


async def start():
    client_id, secret = credentials()
    if not client_id or not secret:
        return JSONResponse({'success': False, 'message': 'Save your Google Web application Client ID and Client secret first.'}, status_code=400)
    try:
        redirect = redirect_uri()
    except ValueError:
        return JSONResponse({'success': False, 'message': 'Set HARVEY_PUBLIC_HOST in Railway first.'}, status_code=400)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    async with lock:
        pending.clear()  # A single operator connects one mailbox; newest request wins.
        pending[state] = {'expires': time.monotonic() + TTL, 'verifier': verifier,
                          'client_id': client_id, 'secret': secret, 'redirect': redirect}
    url = gmail.AUTH_URL + '?' + urlencode({'client_id': client_id, 'redirect_uri': redirect,
        'response_type': 'code', 'scope': gmail.SCOPE, 'access_type': 'offline',
        'prompt': 'consent', 'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'login_hint': expected_email()})
    response = JSONResponse({'success': True, 'authorization_url': url,
                             'message': 'Open Google to connect ' + expected_email()})
    response.set_cookie(COOKIE, state, max_age=TTL, secure=True, httponly=True, samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return response


def result_page(message, status=200):
    # All messages are fixed server text, never query strings or provider output.
    response = HTMLResponse('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Harvey Gmail connection</title></head><body><h1>Harvey Gmail connection</h1><p>' + message + '</p><p>Close this tab and return to Harvey Settings. Click Check Gmail connection.</p></body></html>', status_code=status,
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                 'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                 'X-Content-Type-Options': 'nosniff'})
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax', path='/')
    return response


async def callback(request: Request):
    if request.method != 'GET':
        return result_page('This callback only accepts the Google sign-in return.', 405)
    params = request.query_params
    if len(params.getlist('state')) != 1 or len(params.getlist('code')) > 1:
        return result_page('Invalid sign-in response. Start again from Harvey Settings.', 400)
    state = params.get('state', '')
    cookie = request.cookies.get(COOKIE, '')
    if not state or len(state) > 128 or not hmac.compare_digest(state.encode(), cookie.encode()):
        return result_page('Sign-in could not be matched to this browser. Start again from Harvey Settings.', 400)
    async with lock:
        flow = pending.pop(state, None)
    if not flow or flow['expires'] < time.monotonic():
        return result_page('Sign-in expired or was already used. Start again from Harvey Settings.', 400)
    if params.get('error') or not params.get('code'):
        return result_page('Google sign-in was cancelled or access was denied. Nothing was changed.', 400)
    if credentials() != (flow['client_id'], flow['secret']):
        return result_page('Google client settings changed during sign-in. Start again.', 400)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(gmail.TOKEN_URL, data={'client_id': flow['client_id'],
                'client_secret': flow['secret'], 'code': params['code'],
                'grant_type': 'authorization_code', 'redirect_uri': flow['redirect'],
                'code_verifier': flow['verifier']})
            if response.status_code != 200:
                return result_page('Google could not complete sign-in. Check the Web client credentials and exact redirect URI, then reconnect.', 400)
            token = response.json()
            access = token.get('access_token')
            refresh = token.get('refresh_token')
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                return result_page('Google did not return offline access. Reconnect and approve the requested Gmail access.', 400)
            scopes = token.get('scope', '').split()
            if gmail.SCOPE not in scopes:
                return result_page('Required Gmail permission was not granted. Reconnect and approve Gmail access.', 400)
            profile = await client.get(gmail.API_BASE + '/profile', headers={'Authorization': 'Bearer ' + access})
            if profile.status_code != 200 or profile.json().get('emailAddress', '').lower() != expected_email():
                return result_page('The connected account does not match the configured GIX Gmail address, or Gmail access failed. Reconnect using the correct account.', 400)
        save_token({'refresh_token': refresh, 'scope': token['scope'],
                    'obtained_at': int(time.time()), 'email': expected_email()})
        return result_page('Gmail connected successfully. No email has been sent and sending settings have not changed.')
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, OSError):
        return result_page('Gmail connection could not be saved or Google could not be reached. Return to Settings and try again.', 502)


async def check():
    client_id, secret = credentials()
    from harvey.config import load_config, EnvConfig
    try:
        config = load_config()
        provider = gmail.GmailProvider(config, EnvConfig(gmail_client_id=client_id, gmail_client_secret=secret))
        profile = await provider._request('GET', '/profile')
        if profile and profile.get('emailAddress', '').lower() == expected_email():
            return {'success': True, 'message': 'Connected as ' + expected_email() + '. Sending settings are unchanged.'}
    except Exception:
        pass
    return {'success': False, 'message': 'Gmail is not connected or the sign-in has expired. Save your client credentials and connect Gmail again.'}
