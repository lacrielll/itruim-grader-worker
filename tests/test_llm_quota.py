from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from grader_worker.llm_quota import CapacityUnavailable, QuotaLedger


class QuotaTests(unittest.TestCase):
    def test_reserves_pessimistically_and_releases(self):
        with TemporaryDirectory() as directory:
            ledger = QuotaLedger(Path(directory) / "quota.db")
            ledger.reserve("one", 40, 50)
            with self.assertRaises(CapacityUnavailable): ledger.reserve("two", 20, 50)
            ledger.finish("one", False)
            ledger.reserve("two", 20, 50)

    def test_repeated_active_reservation_is_idempotent(self):
        with TemporaryDirectory() as directory:
            ledger = QuotaLedger(Path(directory) / "quota.db")
            ledger.reserve("same-step", 40, 50)
            ledger.reserve("same-step", 40, 50)
            with self.assertRaises(CapacityUnavailable):
                ledger.reserve("other-step", 20, 50)
