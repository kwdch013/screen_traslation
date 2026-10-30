import unittest

from screen_translation_server.app import main


class ServerBootstrapTest(unittest.TestCase):
	def test_application_entrypoint_returns_success(self) -> None:
		self.assertEqual(main(), 0)


if __name__ == "__main__":
	unittest.main()
