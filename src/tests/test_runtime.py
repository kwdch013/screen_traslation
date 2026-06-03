import unittest

from app.runtime import PipelineRunner


class FakePipeline:
    def __init__(self) -> None:
        self.ticks = 0

    def tick(self) -> bool:
        self.ticks += 1
        return True


class FailingPipeline:
    def tick(self) -> bool:
        raise ValueError("target lost")


class RuntimeTest(unittest.TestCase):
    def test_runner_start_and_stop(self) -> None:
        pipeline = FakePipeline()
        runner = PipelineRunner(pipeline, poll_interval_seconds=0.001)

        runner.start()
        runner.stop()

        self.assertFalse(runner.is_running)
        self.assertGreaterEqual(pipeline.ticks, 0)

    def test_runner_reports_pipeline_errors_without_traceback(self) -> None:
        errors: list[Exception] = []
        runner = PipelineRunner(FailingPipeline(), poll_interval_seconds=0.001, on_error=errors.append)

        runner.start()
        runner.stop()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)


if __name__ == "__main__":
    unittest.main()
