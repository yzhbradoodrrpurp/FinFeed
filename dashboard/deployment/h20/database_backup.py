"""Daily consistent project database backup, independent of browser sessions.

Archives contain private records. Keep an additional copy off this server.
No archive is automatically deleted by this program.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from database_tools import ROOT, snapshot

state = ROOT / '.runtime/database-backup.json'
while True:
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        previous = json.loads(state.read_text()) if state.exists() else {}
        if previous.get('successful_day') != day:
            config = json.loads((ROOT / '.private/backend.json').read_text())
            name = datetime.now(timezone.utc).strftime('finfeed-%Y%m%dT%H%M%SZ.dump')
            archive = ROOT / '.postgres/backups' / name
            snapshot(config['DATABASE_URL'], archive)
            temporary = state.with_suffix('.next.json')
            temporary.write_text(json.dumps({'successful_day': day, 'archive': name}))
            temporary.chmod(0o600)
            temporary.replace(state)
            print('Daily database archive completed', day, flush=True)
    except Exception as error:
        print('Database archive failed: ' + type(error).__name__, flush=True)
    time.sleep(3600)
