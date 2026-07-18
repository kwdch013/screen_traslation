import unittest
import threading
from unittest import mock

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

    def test_stop_keeps_running_thread_when_join_times_out(self) -> None:
        release = threading.Event()

        class BlockingPipeline:
            def tick(self) -> bool:
                release.wait(timeout=2)
                return True

        runner = PipelineRunner(BlockingPipeline(), poll_interval_seconds=0.001)
        runner.start()
        assert runner._thread is not None
        original_join = runner._thread.join
        runner._thread.join = mock.Mock()  # type: ignore[method-assign]
        try:
            runner.stop()

            self.assertTrue(runner.is_running)
        finally:
            release.set()
            original_join(timeout=2)
            runner.stop()

    def test_error_callback_can_be_replaced_for_next_tick(self) -> None:
        first_errors: list[Exception] = []
        second_errors: list[Exception] = []
        runner = PipelineRunner(FailingPipeline(), on_error=first_errors.append)

        runner.set_on_error(second_errors.append)
        runner.start()
        runner.stop()

        self.assertEqual(first_errors, [])
        self.assertEqual(len(second_errors), 1)


if __name__ == "__main__":
    unittest.main()
