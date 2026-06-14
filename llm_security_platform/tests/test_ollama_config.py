import unittest

from llm_security_platform.app.config import normalize_http_base_url


class OllamaConfigTests(unittest.TestCase):
    def test_preserves_explicit_http_url(self):
        self.assertEqual(
            normalize_http_base_url("http://127.0.0.1:11434/"),
            "http://127.0.0.1:11434",
        )

    def test_adds_http_scheme_for_host_port(self):
        self.assertEqual(
            normalize_http_base_url("127.0.0.1:11434"),
            "http://127.0.0.1:11434",
        )


if __name__ == "__main__":
    unittest.main()
