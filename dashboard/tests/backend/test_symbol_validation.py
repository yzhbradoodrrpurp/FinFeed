"""Verified identity admission, transient failures and cache reuse."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.services.symbol_validation import validate_symbols, UnknownTicker, ValidationUnavailable
from backend.storage.store import Store


class SymbolValidationCases(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.store=Store(sqlite_path=str(Path(self.directory.name)/'state.sqlite'))

    def test_unknown_symbol_rejected_and_negative_lookup_coalesced_by_cache(self):
        with patch('backend.services.symbol_validation._lookup',return_value={'ticker':'MCX','valid':False}) as lookup:
            for _ in range(2):
                with self.assertRaisesRegex(UnknownTicker,'没有该 Ticker：MCX'):
                    validate_symbols(['MCX'],self.store)
            self.assertEqual(lookup.call_count,1)

    def test_provider_outage_never_becomes_a_negative_identity(self):
        with patch('backend.services.symbol_validation._lookup',side_effect=OSError('offline')):
            with self.assertRaises(ValidationUnavailable):validate_symbols(['TEST'],self.store)
        self.assertIsNone(self.store.get_cache('ticker-validation:v1:TEST'))
        with patch('backend.services.symbol_validation._lookup',return_value={'ticker':'TEST','valid':True}):
            self.assertEqual(validate_symbols(['TEST'],self.store),{'TEST'})

    def test_new_provider_symbol_does_not_require_autocomplete_membership(self):
        with patch('backend.services.symbol_validation._lookup',return_value={'ticker':'NOTINDIR','valid':True}) as lookup:
            self.assertEqual(validate_symbols(['NOTINDIR','NOTINDIR'],self.store),{'NOTINDIR'})
            validate_symbols(['NOTINDIR'],self.store)
            self.assertEqual(lookup.call_count,1)
        with self.assertRaises(UnknownTicker):validate_symbols(['BAD!'],self.store)

    def test_cached_static_identity_reused_and_concurrent_state_rechecked(self):
        self.store.set_cache('longbridge:v1:static:AAPL',{'data':{'symbol':'AAPL.US','name_en':'Apple','currency':'USD','exchange':'NASD'}})
        with patch('backend.services.symbol_validation._lookup') as lookup:
            validate_symbols(['AAPL'],self.store);lookup.assert_not_called()
        self.store.update_state({'watchlist':['AAPL'],'positions':[]})
        with self.assertRaisesRegex(ValueError,'重新添加'):
            self.store.update_state({'watchlist':['AAPL','MCX']},validated_watchlist=set())
        self.assertEqual(self.store.read_state()['watchlist'],['AAPL'])
