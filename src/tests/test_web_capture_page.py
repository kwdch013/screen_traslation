from __future__ import annotations

import unittest

from app.web_capture_page import render_capture_page


class WebCapturePageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.page = render_capture_page("test-token")

    def test_initializes_controls_from_service_status(self) -> None:
        self.assertIn('fetch("/api/status")', self.page)
        self.assertIn('serviceState === "running" || serviceState === "awaiting_frame"', self.page)
        self.assertIn("syncStatus();", self.page)

    def test_pagehide_requests_service_stop_with_keepalive(self) -> None:
        self.assertIn('window.addEventListener("pagehide"', self.page)
        self.assertIn(
            'fetch("/api/control/stop", {\n'
            '      method: "POST",\n'
            '      headers: { "X-Capture-Token": sessionToken },\n'
            "      keepalive: true,",
            self.page,
        )

    def test_control_rejects_error_state_response(self) -> None:
        self.assertIn('body.state === "error"', self.page)
        self.assertIn("body.error_message", self.page)

    def test_control_buttons_are_guarded_during_async_operation(self) -> None:
        self.assertIn("let operationInProgress = false", self.page)
        self.assertIn("startButton.disabled = true", self.page)
        self.assertIn("reselectButton.disabled = true", self.page)
        self.assertIn("stopButton.disabled = true", self.page)

    def test_error_state_enables_only_stop_and_displays_initial_error(self) -> None:
        self.assertIn('startButton.disabled = active || serviceState === "error"', self.page)
        self.assertIn('stopButton.disabled = !active && serviceState !== "error"', self.page)
        self.assertIn('setStatus(body.error_message || "翻訳処理でエラーが発生しました。")', self.page)

    def test_pageshow_syncs_and_transitional_state_is_polled(self) -> None:
        self.assertIn('window.addEventListener("pageshow", syncStatus)', self.page)
        self.assertIn("STATUS_POLL_INTERVAL_MS", self.page)
        self.assertIn('serviceState === "starting" || serviceState === "stopping"', self.page)
        self.assertIn("statusSyncTimer = setTimeout(syncStatus, STATUS_POLL_INTERVAL_MS)", self.page)


if __name__ == "__main__":
    unittest.main()
