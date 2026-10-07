"""Yahoo daily DXY observations; shares the existing securities concurrency limit."""
import yfinance as yf


def dxy_history(start):
    from backend.services.securities import LIMIT
    with LIMIT:
        frame = yf.Ticker('DX-Y.NYB').history(start=start, interval='1d', auto_adjust=False, timeout=30)
    return [{'date': d.date().isoformat(), 'value': float(row['Close'])}
            for d, row in frame.iterrows() if row['Close'] == row['Close']]
