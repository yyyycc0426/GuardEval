import unittest
from fastapi.testclient import TestClient

from llm_security_platform.app.api import app
from llm_security_platform.app.security import encode_jwt


class WebSocketRBACTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_websocket_unauthenticated_connection_rejected(self):
        # 1. No token -> Rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws") as websocket:
                pass

    def test_websocket_invalid_token_rejected(self):
        # 2. Invalid JWT token -> Rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws?token=invalid_token_string") as websocket:
                pass

    def test_websocket_insufficient_permissions_rejected(self):
        # 3. Valid token but lacks 'run:read' permission
        # A role like 'guest' has no entries in ROLE_PERMISSIONS and is rejected
        token = encode_jwt("guest-user", "guest", "tenant_a")
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/ws?token={token}") as websocket:
                pass

    def test_websocket_authorized_connection_success(self):
        # 4. Valid token for 'analyst' -> Accepted and echos
        token = encode_jwt("demo-analyst", "analyst", "tenant_a")
        with self.client.websocket_connect(f"/ws?token={token}") as websocket:
            websocket.send_text("Hello World!")
            response = websocket.receive_text()
            self.assertEqual(response, "Echo [tenant_a] to demo-analyst (analyst): Hello World!")


if __name__ == "__main__":
    unittest.main()
