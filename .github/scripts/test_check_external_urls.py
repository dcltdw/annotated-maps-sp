"""Tests for the scheduled external-URL liveness check (ADR-0011)."""
import contextlib
import io
import unittest
import urllib.error
from unittest import mock

import check_external_urls as mod


class AliveTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        patcher = mock.patch.object(mod.time, "sleep", self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_alive(self, side_effect):
        with mock.patch.object(mod.urllib.request, "urlopen",
                               side_effect=side_effect), \
                contextlib.redirect_stdout(io.StringIO()):
            return mod.alive("https://example.test/")

    def test_success_returns_true_without_sleeping(self):
        self.assertTrue(self.run_alive([mock.MagicMock()]))
        self.assertEqual(self.sleeps, [])

    def test_retries_then_succeeds_sleeps_once(self):
        ok = mock.MagicMock()
        self.assertTrue(self.run_alive([urllib.error.URLError("down"), ok]))
        self.assertEqual(self.sleeps, [mod.SLEEP_BETWEEN_S])

    def test_no_sleep_after_the_final_failed_attempt(self):
        errs = [urllib.error.URLError("down")] * mod.ATTEMPTS
        self.assertFalse(self.run_alive(errs))
        self.assertEqual(len(self.sleeps), mod.ATTEMPTS - 1)

    def test_http_error_counts_as_dead(self):
        err = urllib.error.HTTPError(
            "https://example.test/", 500, "boom", {}, None)
        self.assertFalse(self.run_alive([err] * mod.ATTEMPTS))

    def test_timeout_counts_as_dead(self):
        self.assertFalse(self.run_alive([TimeoutError("slow")] * mod.ATTEMPTS))

    def test_unexpected_exception_is_not_swallowed(self):
        """The handler is narrow on purpose: a bug in this script should
        surface, not be reported as a dead URL."""
        with self.assertRaises(ValueError):
            self.run_alive([ValueError("programming error")])


if __name__ == "__main__":
    unittest.main()
