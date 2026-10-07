"""Refresh the public US symbol search snapshot from Nasdaq Trader (no prices)."""
import csv
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

rows = {}
sources = []
for filename, field in [('nasdaqlisted.txt', 'Symbol'), ('otherlisted.txt', 'NASDAQ Symbol')]:
    url = 'https://www.nasdaqtrader.com/dynamic/SymDir/' + filename
    text = urllib.request.urlopen(url, timeout=30).read().decode('utf-8-sig')
    sources.append(url)
    for row in csv.DictReader(io.StringIO(text), delimiter='|'):
        symbol = row.get(field, '')
        # Only directly supported Yahoo common stock / ETF symbol notation.
        if row.get('Test Issue') != 'N' or not re.fullmatch(r'[A-Z0-9]+(?:\.[A-Z])?', symbol):
            continue
        symbol = symbol.replace('.', '-')
        rows[symbol] = [symbol, row['Security Name'], row.get('ETF') == 'Y']
assert len(rows) > 5000, 'Incomplete directory; keep the previous snapshot'
data = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'sources': sources, 'securities': sorted(rows.values())}
path = Path(__file__).resolve().parents[1] / 'dashboard/frontend/assets/symbol-directory.json'
path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
print(f'Saved {len(rows)} symbols; {path.stat().st_size} bytes')
