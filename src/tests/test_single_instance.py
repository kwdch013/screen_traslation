import tempfile
import unittest
from pathlib import Path

from app.single_instance import SingleInstanceLock


class SingleInstanceLockTest(unittest.TestCase):
    def test_second_lock_cannot_acquire_until_first_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "screen_translation.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()


if __name__ == "__main__":
    unittest.main()
