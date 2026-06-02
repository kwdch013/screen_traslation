import unittest

from app.runtime import PipelineRunner


class FakePipeline:
    def __init__(self) -> None:
        self.ticks = 0

    def tick(self) -> bool:
        self.ticks += 1
        return True


class RuntimeTest(unittest.TestCase):
    def test_runner_start_and_stop(self) -> None:
        pipeline = FakePipeline()
        runner = PipelineRunner(pipeline, poll_interval_seconds=0.001)

        runner.start()
        runner.stop()

        self.assertFalse(runner.is_running)
        self.assertGreaterEqual(pipeline.ticks, 0)


if __name__ == "__main__":
    unittest.main()
