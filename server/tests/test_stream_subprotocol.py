"""WSS subprotocol `screen-translation.v1`(契約)の折衝。クライアントが提示したときだけ選択する。"""

import unittest

from starlette.testclient import TestClient

from _api_support import DEVICE, make_app

URL = "wss://server.example/api/v1/stream"
SUBPROTOCOL = "screen-translation.v1"
# TestClientは渡されたheadersを書き換えるため、共有のDEVICEは必ずコピーして渡す


class StreamSubprotocolTest(unittest.TestCase):
	def setUp(self) -> None:
		self.client = TestClient(make_app(None), base_url="https://server.example")

	def test_selects_the_contract_subprotocol_when_the_client_offers_it(self) -> None:
		with self.client.websocket_connect(URL, subprotocols=[SUBPROTOCOL], headers=dict(DEVICE)) as websocket:
			self.assertEqual(websocket.accepted_subprotocol, SUBPROTOCOL)

	def test_selects_it_among_other_offered_subprotocols(self) -> None:
		with self.client.websocket_connect(URL, subprotocols=["other.v9", SUBPROTOCOL], headers=dict(DEVICE)) as websocket:
			self.assertEqual(websocket.accepted_subprotocol, SUBPROTOCOL)

	def test_does_not_invent_a_subprotocol_the_client_did_not_offer(self) -> None:
		with self.client.websocket_connect(URL, headers=dict(DEVICE)) as websocket:
			self.assertIsNone(websocket.accepted_subprotocol)

	def test_does_not_select_an_unknown_subprotocol(self) -> None:
		with self.client.websocket_connect(URL, subprotocols=["other.v9"], headers=dict(DEVICE)) as websocket:
			self.assertIsNone(websocket.accepted_subprotocol)


if __name__ == "__main__":
	unittest.main()
