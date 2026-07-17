from io import BytesIO
import socket
from time import monotonic
import unittest
from unittest import mock

from PIL import Image
from uvicorn.protocols.http.h11_impl import H11Protocol

from app.web_capture import TOKEN_HEADER, WebCaptureServer
from app.web_capture_protocol import create_header_timeout_protocol


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (16, 10), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _receive_http_statuses(connection: socket.socket, count: int) -> list[int]:
    """Content-Length付きHTTP応答を指定数だけ受信する。"""
    buffer = b""
    statuses: list[int] = []
    while len(statuses) < count:
        chunk = connection.recv(65536)
        if not chunk:
            raise AssertionError(f"HTTP応答を{count}件受信する前に接続が閉じられました")
        buffer += chunk
        while b"\r\n\r\n" in buffer and len(statuses) < count:
            raw_headers, body = buffer.split(b"\r\n\r\n", 1)
            header_lines = raw_headers.split(b"\r\n")
            content_length = 0
            for line in header_lines[1:]:
                name, _, value = line.partition(b":")
                if name.lower() == b"content-length":
                    content_length = int(value.strip())
                    break
            if len(body) < content_length:
                break
            statuses.append(int(header_lines[0].split(b" ", 2)[1]))
            buffer = body[content_length:]
    return statuses


class HeaderTimeoutProtocolServerTest(unittest.TestCase):
    def _server(self, read_timeout: float) -> tuple[WebCaptureServer, int]:
        port = _free_port()
        server = WebCaptureServer(port=port, read_timeout_seconds=read_timeout)
        server.start()
        self.addCleanup(server.stop)
        return server, port

    def test_second_partial_headers_are_closed_at_request_deadline(self) -> None:
        read_timeout = 0.2
        _, port = self._server(read_timeout)

        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(b"GET /missing HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            connection.settimeout(2)
            self.assertEqual(_receive_http_statuses(connection, 1), [404])

            started_at = monotonic()
            connection.sendall(b"GET /missing HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: ")
            connection.settimeout(read_timeout + 1.0)
            received = connection.recv(1)
            elapsed = monotonic() - started_at

        self.assertEqual(received, b"")
        self.assertGreaterEqual(elapsed, read_timeout * 0.5)
        self.assertLess(elapsed, read_timeout + 0.8)

    def test_two_pipelined_requests_both_receive_responses(self) -> None:
        read_timeout = 0.2
        _, port = self._server(read_timeout)
        request = b"GET /missing HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"

        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.settimeout(read_timeout + 1.0)
            connection.sendall(request + request)
            statuses = _receive_http_statuses(connection, 2)

        self.assertEqual(statuses, [404, 404])

    def test_repeated_frames_on_keep_alive_connection_are_not_closed(self) -> None:
        read_timeout = 0.3
        server, port = self._server(read_timeout)
        frame = _jpeg_bytes()
        request = (
            b"POST /frame HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: image/jpeg\r\n"
            + TOKEN_HEADER.encode("ascii")
            + b": "
            + server.session_token.encode("ascii")
            + b"\r\nContent-Length: "
            + str(len(frame)).encode("ascii")
            + b"\r\n\r\n"
            + frame
        )

        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.settimeout(read_timeout + 1.0)
            statuses = []
            for _ in range(3):
                connection.sendall(request)
                statuses.extend(_receive_http_statuses(connection, 1))

        self.assertEqual(statuses, [204, 204, 204])
        self.assertTrue(server.store.has_frame())


class HeaderTimeoutProtocolCompatibilityTest(unittest.TestCase):
    def test_missing_uvicorn_internal_attributes_fail_during_creation(self) -> None:
        protocol_type = create_header_timeout_protocol(0.2)

        with mock.patch.object(H11Protocol, "__init__", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "uvicornの内部API"):
                protocol_type(mock.sentinel.config, mock.sentinel.server_state, {})


if __name__ == "__main__":
    unittest.main()
