import time
import unittest

from shadow_ai.models import EchoModel


def _req(user: str, max_tokens: int = 10_000, deadline_ms: int = 120_000) -> dict:
    return {
        "session_id": "s1",
        "messages": [{"role": "user", "content": user}],
        "params": {"temperature": 0.7, "top_p": 0.95, "max_tokens": max_tokens},
        "constraints": {"deadline_ms": deadline_ms, "stop_sequences": []},
    }


class EchoModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = EchoModel(token_delay_s=0.0)
        self.m.load({})

    def test_deterministic(self) -> None:
        def run() -> list:
            evs = []
            self.m.stream(_req("Hallo Shadow"), evs.append)
            return evs
        self.assertEqual(run(), run())

    def test_max_tokens(self) -> None:
        evs = []
        reason = self.m.stream(_req("eins zwei drei vier fuenf", max_tokens=2), evs.append)
        self.assertEqual(reason, "length")

    def test_deadline(self) -> None:
        m = EchoModel(token_delay_s=0.05)
        m.load({})
        evs = []
        t0 = time.monotonic()
        reason = m.stream(_req("a b c d e f g h i j", deadline_ms=30), evs.append)
        self.assertEqual(reason, "cancelled")
        self.assertLess(time.monotonic() - t0, 0.5)

    def test_not_loaded_raises(self) -> None:
        m = EchoModel(token_delay_s=0.0)
        with self.assertRaises(RuntimeError):
            m.stream(_req("x"), lambda ev: None)


if __name__ == "__main__":
    unittest.main()
