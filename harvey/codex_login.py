"""Dashboard-owned device login. Credentials stay in Codex's native store."""
import asyncio
import os
import re
import shutil

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
DEVICE_URL = 'https://auth.openai.com/codex/device'
CODE = re.compile(r'^[A-Z0-9]{3,8}-[A-Z0-9]{3,8}$')


def parse_prompt(text):
    lines = ANSI.sub('', text).splitlines()
    url = DEVICE_URL if DEVICE_URL in lines or any(x.strip() == DEVICE_URL for x in lines) else ''
    code = next((x.strip() for x in lines if CODE.fullmatch(x.strip())), '')
    return url, code


class CodexLogin:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.task = None
        self.proc = None
        self.view = {'state': 'idle', 'message': 'Connect your ChatGPT subscription to Codex.'}

    def snapshot(self):
        return dict(self.view)

    async def status(self):
        result = self.snapshot()
        if result['state'] in ('starting', 'waiting', 'checking'):
            return result
        from harvey.codex import check_native_auth, CodexError
        try:
            await asyncio.to_thread(check_native_auth)
            result['credentials_present'] = True
            if result['state'] in ('idle', 'cancelled'):
                result.update(state='signed_in', message='Signed in. Check connection to verify Harvey can use Codex.')
        except (CodexError, OSError):
            result['credentials_present'] = False
        return result

    async def start(self):
        async with self.lock:
            if self.task and not self.task.done():
                return self.snapshot()
            cli = shutil.which('codex')
            if not cli:
                self.view = {'state': 'error', 'message': 'Codex CLI is missing. Deploy the Railway Codex image first.'}
                return self.snapshot()
            self.view = {'state': 'starting', 'message': 'Requesting a one-time sign-in code…'}
            self.task = asyncio.create_task(self._login(cli))
            return self.snapshot()

    async def _login(self, cli):
        try:
            env = dict(os.environ)
            for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL'):
                env.pop(key, None)
            # Fixed executable arguments; never a shell or browser-supplied command.
            self.proc = await asyncio.create_subprocess_exec(
                cli, '-c', 'cli_auth_credentials_store="file"', 'login', '--device-auth',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, env=env,
            )
            async with asyncio.timeout(16 * 60):
                buffer = ''
                while True:
                    line = await self.proc.stdout.readline()
                    if not line:
                        break
                    # Only a short-lived code and allowlisted URL may reach the UI.
                    # Raw CLI output is never logged or returned to the browser.
                    buffer = (buffer + line.decode('utf-8', 'replace'))[-12000:]
                    url, code = parse_prompt(buffer)
                    if url and code:
                        self.view = {'state': 'waiting', 'message': 'Open OpenAI, sign in and enter this code. It expires in 15 minutes.',
                                     'verification_url': url, 'user_code': code}
                rc = await self.proc.wait()
                if rc != 0:
                    self.view = {'state': 'error', 'message': 'Sign-in failed or expired. Enable device-code authorization in your ChatGPT security settings if required, then try again.'}
                    return
                from harvey.codex import check_native_auth
                await asyncio.to_thread(check_native_auth)
                self.view = {'state': 'signed_in', 'message': 'Signed in successfully. Click Check connection to verify Harvey can use Codex.'}
        except asyncio.CancelledError:
            self.view = {'state': 'cancelled', 'message': 'Sign-in cancelled. Existing credentials were kept.'}
            raise
        except TimeoutError:
            self.view = {'state': 'error', 'message': 'The sign-in code expired. Click Connect Codex to request a new one.'}
        except Exception:
            self.view = {'state': 'error', 'message': 'Could not complete Codex sign-in. Check the deployment and try again.'}
        finally:
            if self.proc and self.proc.returncode is None:
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
                await self.proc.wait()
            self.proc = None

    async def cancel(self):
        async with self.lock:
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            return self.snapshot()

    async def check(self):
        async with self.lock:
            if self.task and not self.task.done():
                return self.snapshot()
            self.view = {'state': 'checking', 'message': 'Checking Codex login, supported version and isolation. No sales message is sent.'}
            self.task = asyncio.create_task(self._check())
            return self.snapshot()

    async def _check(self):
        try:
            from harvey.codex import CodexClient
            await CodexClient().preflight(timeout=90)
            self.view = {'state': 'ready', 'message': 'Connected. Harvey can use your Codex subscription. Sending remains unchanged.'}
        except asyncio.CancelledError:
            self.view = {'state': 'cancelled', 'message': 'Connection check cancelled.'}
            raise
        except Exception:
            self.view = {'state': 'error', 'message': 'Connection check failed. Reconnect Codex; if it continues, check the supported CLI version, account access and server network.'}


login = CodexLogin()
