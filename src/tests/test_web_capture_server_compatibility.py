import socket
import threading
import time
import unittest
from collections.abc import Callable
from unittest import mock

from PIL import Image

from app.web_capture import WebCaptureServer


class WebCaptureServerCompatibilityTest(unittest.TestCase):
    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WebCaptureServer(host="0.0.0.0")

    def test_start_stop_and_properties_remain_compatible(self) -> None:
        port = _free_port()
        server = WebCaptureServer(port=port)
        self.assertFalse(server.is_running)

        server.start()
        try:
            self.assertTrue(server.is_running)
            self.assertEqual(server.url, f"http://127.0.0.1:{port}/")
            server.start()
            self.assertTrue(server.is_running)
        finally:
            server.stop()

        self.assertFalse(server.is_running)

    def test_run_forever_uses_same_secure_single_worker_config(self) -> None:
        server = WebCaptureServer(port=8765)
        config_values: dict[str, object] = {}

        class FakeUvicornServer:
            def __init__(self, config: object) -> None:
                self.config = config

            def run(self) -> None:
                return None

        def capture_config(*args: object, **kwargs: object) -> object:
            config_values.update(kwargs)
            return object()

        with mock.patch("app.web_capture.uvicorn.Config", side_effect=capture_config), mock.patch(
            "app.web_capture.uvicorn.Server", FakeUvicornServer
        ):
            server.run_forever()

        self.assertEqual(config_values["host"], "127.0.0.1")
        self.assertEqual(config_values["workers"], 1)
        self.assertTrue(callable(config_values["http"]))

    def test_new_session_clears_stored_frame(self) -> None:
        server = WebCaptureServer(port=_free_port())
        self.assertTrue(server.accept_frame(server.session_token, Image.new("RGB", (2, 2))))

        server.new_session()

        self.assertFalse(server.store.has_frame())

    def test_stop_invalidates_previous_session_token(self) -> None:
        server = WebCaptureServer(port=_free_port())
        stale_token = server.session_token
        server.start()
        server.stop()

        self.assertNotEqual(server.session_token, stale_token)
        self.assertFalse(server.store.has_frame())

    def test_concurrent_start_creates_only_one_server(self) -> None:
        constructor_entered = threading.Event()
        constructor_release = threading.Event()
        run_release = threading.Event()
        instances: list[object] = []
        instances_lock = threading.Lock()

        class FakeServer:
            def __init__(self, config: object) -> None:
                self.started = False
                self.should_exit = False
                self.force_exit = False
                with instances_lock:
                    instances.append(self)
                    first = len(instances) == 1
                if first:
                    constructor_entered.set()
                if first and not constructor_release.wait(timeout=2):
                    raise AssertionError("サーバー生成の待機を解除できませんでした")

            def run(self) -> None:
                self.started = True
                while not self.should_exit and not self.force_exit and not run_release.wait(0.01):
                    pass

        server = WebCaptureServer(port=8765)
        errors: list[BaseException] = []

        def start() -> None:
            try:
                server.start()
            except BaseException as error:
                errors.append(error)

        with mock.patch("app.web_capture.uvicorn.Config", return_value=object()), mock.patch(
            "app.web_capture.uvicorn.Server", FakeServer
        ):
            first = threading.Thread(target=start)
            second = threading.Thread(target=start)
            first.start()
            self.assertTrue(constructor_entered.wait(timeout=2))
            second.start()
            time.sleep(0.05)
            constructor_release.set()
            first.join(timeout=2)
            second.join(timeout=2)
            try:
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(instances), 1)
            finally:
                run_release.set()
                server.stop()

    def test_stop_waits_for_startup_to_finish(self) -> None:
        run_entered = threading.Event()
        allow_start = threading.Event()

        class DelayedServer:
            def __init__(self, config: object) -> None:
                self.started = False
                self.should_exit = False
                self.force_exit = False

            def run(self) -> None:
                run_entered.set()
                while not allow_start.wait(0.01):
                    if self.should_exit:
                        return
                self.started = True
                while not self.should_exit and not self.force_exit:
                    time.sleep(0.01)

        server = WebCaptureServer(port=8765)
        errors: list[BaseException] = []

        def call(method: Callable[[], None]) -> None:
            try:
                method()
            except BaseException as error:
                errors.append(error)

        with mock.patch("app.web_capture.uvicorn.Config", return_value=object()), mock.patch(
            "app.web_capture.uvicorn.Server", DelayedServer
        ):
            start_thread = threading.Thread(target=call, args=(server.start,))
            stop_thread = threading.Thread(target=call, args=(server.stop,))
            start_thread.start()
            self.assertTrue(run_entered.wait(timeout=2))
            stop_thread.start()
            time.sleep(0.05)
            stop_was_serialized = stop_thread.is_alive()
            allow_start.set()
            start_thread.join(timeout=2)
            stop_thread.join(timeout=2)

        self.assertTrue(stop_was_serialized)
        self.assertFalse(start_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(server.is_running)

    def test_stop_preserves_state_when_thread_join_times_out(self) -> None:
        release = threading.Event()

        class StuckServer:
            def __init__(self, config: object) -> None:
                self.started = False
                self.should_exit = False
                self.force_exit = False

            def run(self) -> None:
                self.started = True
                release.wait(timeout=2)

        server = WebCaptureServer(port=8765)
        with mock.patch("app.web_capture.uvicorn.Config", return_value=object()), mock.patch(
            "app.web_capture.uvicorn.Server", StuckServer
        ):
            server.start()
            tracked_server = server._uvicorn_server
            tracked_thread = server._thread
            assert tracked_thread is not None
            original_join = tracked_thread.join
            tracked_thread.join = mock.Mock()  # type: ignore[method-assign]
            try:
                with self.assertRaises(RuntimeError):
                    server.stop()
                self.assertIs(server._uvicorn_server, tracked_server)
                self.assertIs(server._thread, tracked_thread)
            finally:
                release.set()
                original_join(timeout=2)
                server.stop()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
