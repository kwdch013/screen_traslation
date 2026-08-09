import unittest

from app.web_capture_security import host_allowed, origin_allowed


class HostAllowedTest(unittest.TestCase):
    def test_hostの許可判定(self) -> None:
        cases = (
            ("IPv6ループバック", "[::1]", True),
            ("ポート付きIPv6ループバック", "[::1]:8765", True),
            ("最小ポート", "localhost:0", True),
            ("最大ポート", "localhost:65535", True),
            ("IPv6の空ポート", "[::1]:", False),
            ("空ポート", "localhost:", False),
            ("範囲外ポート", "localhost:65536", False),
            ("過長な数字ポート", "localhost:" + "1" * 5_000, False),
            ("非ASCII数字ポート", "localhost:８７６５", False),
        )
        for name, host, expected in cases:
            with self.subTest(name=name, host=host):
                self.assertIs(host_allowed(host), expected)


class OriginAllowedTest(unittest.TestCase):
    def test_originの許可判定(self) -> None:
        cases = (
            ("IPv6ループバック", "http://[::1]", True),
            ("ポート付きIPv6ループバック", "http://[::1]:8765", True),
            ("最小ポート", "http://localhost:0", True),
            ("最大ポート", "https://127.0.0.1:65535", True),
            ("IPv6の空ポート", "http://[::1]:", False),
            ("空ポート", "http://localhost:", False),
            ("範囲外ポート", "http://localhost:65536", False),
            ("非ASCII数字ポート", "http://localhost:８７６５", False),
            ("null", "null", False),
            ("userinfo付き", "http://user:password@localhost", False),
            ("パス付き", "http://localhost/capture", False),
        )
        for name, origin, expected in cases:
            with self.subTest(name=name, origin=origin):
                self.assertIs(origin_allowed(origin), expected)


if __name__ == "__main__":
    unittest.main()
