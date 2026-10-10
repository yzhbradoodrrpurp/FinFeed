"""Run the project PostgreSQL as an unprivileged numeric identity.

No system user, system service, global configuration, or public listener is created.
The installation and initialized cluster must already exist; never initialize here.
"""
import json
import os
from pathlib import Path

root = Path(os.environ.get('FINFEED_H20_ROOT', '/mnt/data/users/shx/FinFeed')).resolve()
config = json.loads((root / '.private/postgresql.json').read_text())
engine = root / '.postgres/engine/bin/postgres'
data = root / '.postgres/data'
if not (data / 'PG_VERSION').is_file():
    raise RuntimeError('PostgreSQL cluster is not initialized')
os.chdir(data)
if os.getuid() == 0:
    os.setgroups([])
    os.setgid(int(config['gid']))
    os.setuid(int(config['uid']))
os.execv(str(engine), [str(engine), '-D', str(data)])
