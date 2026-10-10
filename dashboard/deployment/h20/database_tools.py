"""Consistent FinFeed database archives and exact row verification.

Credentials are supplied only through the project's private configuration.
Dump files contain private records and must never be committed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote

import psycopg
from psycopg import sql

ROOT = Path(os.environ.get('FINFEED_H20_ROOT', '/mnt/data/users/shx/FinFeed')).resolve()


def connection_environment(url):
    config = psycopg.conninfo.conninfo_to_dict(url)
    env = dict(os.environ)
    for key, name in {'host': 'PGHOST', 'port': 'PGPORT', 'user': 'PGUSER',
                      'password': 'PGPASSWORD', 'dbname': 'PGDATABASE'}.items():
        if key in config:
            env[name] = config[key]
    env.pop('PGOPTIONS', None)
    env.update(PGSSLMODE='require', PGCONNECT_TIMEOUT='15')
    return env


def fingerprint(connection):
    connection.execute("SET TIME ZONE 'UTC'")
    connection.execute("SET extra_float_digits=3")
    tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='finfeed_private' ORDER BY 1").fetchall()
    result = {}
    for (table,) in tables:
        digest = hashlib.sha256()
        count = 0
        query = sql.SQL('SELECT to_jsonb(t)::text FROM finfeed_private.{} t ORDER BY to_jsonb(t)::text COLLATE "C"').format(sql.Identifier(table))
        for (row,) in connection.execute(query):
            value = row.encode('utf-8')
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
            count += 1
        result[table] = {'rows': count, 'sha256': digest.hexdigest()}
    sequences = connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='finfeed_private' ORDER BY 1").fetchall()
    result['_sequences'] = {}
    for (name,) in sequences:
        result['_sequences'][name] = list(connection.execute(sql.SQL('SELECT last_value,is_called FROM finfeed_private.{}').format(sql.Identifier(name))).fetchone())
    return result


def snapshot(url, archive):
    archive = Path(archive)
    archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if archive.exists():
        raise FileExistsError('Refusing to replace an existing database archive')
    with psycopg.connect(url, sslmode='require') as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        exported = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
        manifest = fingerprint(connection)
        with archive.with_suffix('.log').open('wb') as log:
            subprocess.run([str(ROOT / '.postgres/engine/bin/pg_dump'), '--format=custom',
                            '--no-owner', '--no-acl', '--schema=finfeed_private',
                            '--snapshot=' + exported, '--file=' + str(archive)],
                           env=connection_environment(url), stdout=log, stderr=log, check=True, timeout=600)
    manifest_file = archive.with_suffix('.manifest.json')
    manifest_file.write_text(json.dumps(manifest, indent=2))
    for path in (archive, manifest_file, archive.with_suffix('.log')):
        path.chmod(0o600)
    return manifest


def verify(url, manifest):
    with psycopg.connect(url, sslmode='require') as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        actual = fingerprint(connection)
    if actual != manifest:
        raise RuntimeError('Database content differs from the saved consistent snapshot')
    return actual


def admin_url(database='postgres'):
    config = json.loads((ROOT / '.private/postgresql.json').read_text())
    return 'postgresql://finfeed_admin:' + quote(config['admin_password'], safe='') + '@127.0.0.1:18766/' + database
