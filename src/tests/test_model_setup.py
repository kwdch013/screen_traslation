import unittest

from app.model_setup import find_argos_package


class FakePackage:
    def __init__(self, from_code: str, to_code: str) -> None:
        self.from_code = from_code
        self.to_code = to_code


class ModelSetupTest(unittest.TestCase):
    def test_find_argos_package(self) -> None:
        selected = find_argos_package(
            [FakePackage("en", "es"), FakePackage("en", "ja")],
            "en",
            "ja",
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.to_code, "ja")


if __name__ == "__main__":
    unittest.main()
