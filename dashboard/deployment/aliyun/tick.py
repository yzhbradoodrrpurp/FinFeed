"""Local scheduler client. Never prints credentials or response payloads."""
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    origin = os.environ.get('PUBLIC_ORIGIN', '')
    host = urlsplit(origin).netloc
    token = os.environ.get('FINFEED_NOTIFICATION_CRON_TOKEN', '')
    if not host or len(token) < 32:
        raise SystemExit('Notification scheduler configuration is incomplete')
    request = Request('http://127.0.0.1:10000/api/notifications/tick', data=b'{}',
                      headers={'Host': host, 'Authorization': 'Bearer ' + token,
                               'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 202:
                raise ValueError()
    except Exception:
        raise SystemExit('Notification check failed; inspect backend service status') from None
    print('Notification check accepted')


if __name__ == '__main__':
    main()
