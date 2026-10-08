"""One-time, send-only Gmail OAuth bootstrap on the operator's own computer.

Run with --client /path/to/downloaded-client.json --sender sender@gmail.com.
Open the printed loopback URL in Safari; secrets are written only to --output.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

SCOPE = 'https://www.googleapis.com/auth/gmail.send'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--sender', required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'.local/gmail-mailer.json')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; use a new private output path.')
    client = json.loads(args.client.read_text())['installed']
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    result = {'done': False}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log authorization codes in callback URLs.

        def reply(self, status, message):
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(message.encode())

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/start':
                self.send_response(302)
                self.send_header('Location', auth_url)
                self.end_headers()
                return
            query = parse_qs(url.query)
            if url.path != '/' or not secrets.compare_digest(query.get('state', [''])[0], state):
                self.reply(400, 'Invalid authorization callback.')
                return
            if query.get('error') or not query.get('code'):
                self.reply(400, 'Authorization was not granted. No credentials saved.')
                result['done'] = True
                return
            try:
                request = Request('https://oauth2.googleapis.com/token', data=urlencode({
                    'client_id': client['client_id'], 'client_secret': client['client_secret'],
                    'code': query['code'][0], 'code_verifier': verifier,
                    'redirect_uri': redirect, 'grant_type': 'authorization_code',
                }).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
                with urlopen(request, timeout=20) as response:
                    token = json.load(response)
                if not token.get('refresh_token') or SCOPE not in token.get('scope', '').split():
                    raise ValueError('Missing offline send permission')
                config = {'FINFEED_EMAIL_PROVIDER': 'gmail', 'FINFEED_EMAIL_FROM': args.sender,
                          'GMAIL_CLIENT_ID': client['client_id'], 'GMAIL_CLIENT_SECRET': client['client_secret'],
                          'GMAIL_REFRESH_TOKEN': token['refresh_token']}
                args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as output:
                    json.dump(config, output)
                self.reply(200, 'Gmail 发信授权已保存。可以关闭此页面。')
                print('Authorization saved to private output file.', flush=True)
            except Exception:
                self.reply(502, 'Authorization could not be saved. Restart the setup tool to retry.')
                print('Authorization failed; no credential values logged.', flush=True)
            result['done'] = True

    server = HTTPServer(('127.0.0.1', 0), Callback)
    server.timeout = 1
    redirect = 'http://127.0.0.1:%s/' % server.server_port
    auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
        'scope': SCOPE, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
        'access_type': 'offline', 'prompt': 'consent', 'login_hint': args.sender,
    })
    print('Open in Safari: ' + redirect + 'start', flush=True)
    deadline = time.monotonic() + 900
    try:
        while not result['done'] and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
