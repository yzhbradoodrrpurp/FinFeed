"""Exercise a silent PostgreSQL socket without a live database or credentials."""
import socket
import struct
import threading
import time
import unittest
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool
from backend.storage.store import BoundedConnection


def packet(kind, payload):
    return kind + struct.pack('!I', len(payload) + 4) + payload


def read_exact(sock, length):
    value = b''
    while len(value) < length:
        chunk = sock.recv(length - len(value))
        if not chunk:
            raise EOFError
        value += chunk
    return value


class FastConnection(BoundedConnection):
    response_timeout = 0.25


@contextmanager
def database_stub():
    # Minimal simple-query protocol: authenticate; acknowledge queries unless
    # explicitly blackholed. This tests the real libpq socket wait, not a mock.
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    server.settimeout(0.1)
    stopped = threading.Event()
    blackhole = threading.Event()
    sockets = []
    workers = []
    queries = []

    def serve(client):
        try:
            length = struct.unpack('!I', read_exact(client, 4))[0]
            read_exact(client, length - 4)
            client.sendall(packet(b'R', struct.pack('!I', 0)) +
                packet(b'S', b'server_version\x0015.0\x00') +
                packet(b'S', b'client_encoding\x00UTF8\x00') + packet(b'Z', b'I'))
            while not stopped.is_set():
                kind = read_exact(client, 1)
                length = struct.unpack('!I', read_exact(client, 4))[0]
                body = read_exact(client, length - 4)
                if kind == b'X':
                    break
                queries.append(body)
                if blackhole.is_set():
                    # TCP remains open and ACKs bytes; no PostgreSQL reply.
                    # Only the client response deadline can recover this case.
                    continue
                client.sendall((packet(b'I', b'') if body == b'\x00' else
                    packet(b'C', b'SET\x00')) + packet(b'Z', b'I'))
        except (EOFError, OSError):
            pass
        finally:
            client.close()

    def accept():
        while not stopped.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sockets.append(client)
            worker = threading.Thread(target=serve, args=(client,), daemon=True)
            workers.append(worker)
            worker.start()

    worker = threading.Thread(target=accept, daemon=True)
    worker.start()
    try:
        yield dict(host='127.0.0.1', port=server.getsockname()[1], user='test',
                   dbname='test', sslmode='disable', autocommit=True), blackhole, queries
    finally:
        stopped.set()
        server.close()
        for client in sockets:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        worker.join(1)
        for child in workers:
            child.join(1)


class ConnectionRecoveryCases(unittest.TestCase):
    def test_silent_query_closes_connection_without_replaying_write(self):
        with database_stub() as (kwargs, blackhole, queries):
            with FastConnection.connect(**kwargs) as connection:
                blackhole.set()
                started = time.monotonic()
                with self.assertRaises(psycopg.OperationalError):
                    connection.execute('UPDATE test SET value=1')
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertTrue(connection.closed)
                self.assertEqual(len(queries), 1)

    def test_pool_recovers_after_silent_checkout_probe(self):
        with database_stub() as (kwargs, blackhole, queries):
            with ConnectionPool(connection_class=FastConnection, kwargs=kwargs,
                    min_size=1, max_size=1, timeout=0.7,
                    check=ConnectionPool.check_connection) as pool:
                pool.wait()
                blackhole.set()
                with self.assertRaises(psycopg.OperationalError):
                    with pool.connection():
                        self.fail('a silent connection must not reach business code')
                blackhole.clear()
                with pool.connection(timeout=3) as connection:
                    connection.execute('SET test = 1')
                self.assertEqual(pool.get_stats()['pool_available'], 1)
                self.assertGreater(pool.get_stats().get('connections_num', 0), 1)


if __name__ == '__main__':
    unittest.main()
