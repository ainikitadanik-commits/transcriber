import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import transcriber.web as web
from transcriber.realtime import RealtimeCaptureManager


class ReleaseRuntimeTests(unittest.TestCase):
    def test_health_echoes_stable_runtime_identity(self):
        with patch.dict(
            os.environ,
            {
                "TRANSCRIBER_BUILD_ID": "release-commit",
                "TRANSCRIBER_INSTANCE_ID": "native-shell-instance",
            },
        ):
            response = web.app.test_client().get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["product"], "transcriber")
        self.assertEqual(
            payload["bundle_id"],
            "com.ainikitadanik.transcriber",
        )
        self.assertEqual(payload["build_id"], "release-commit")
        self.assertEqual(payload["instance_id"], "native-shell-instance")
        self.assertIsInstance(payload["pid"], int)

    def test_structured_permission_error_updates_source_state(self):
        manager = RealtimeCaptureManager()
        events = [
            {
                "event": "permission_state",
                "source": "microphone",
                "state": "denied",
            },
            {
                "event": "error",
                "error_code": "permission_denied",
                "error_domain": "AVFoundation",
                "native_code": -1,
                "source": "microphone",
                "retryable": True,
                "message": "authorization denied",
            },
        ]
        process = SimpleNamespace(
            stdout=io.StringIO(
                "".join(json.dumps(event) + "\n" for event in events)
            )
        )
        manager._process = process

        manager._read_events(process)
        state = manager.snapshot()

        self.assertEqual(state["status"], "error")
        self.assertEqual(state["permissions"]["microphone"], "denied")
        self.assertEqual(state["permissions"]["system"], "unknown")
        self.assertEqual(state["error"]["code"], "permission_denied")
        self.assertEqual(state["error"]["source"], "microphone")
        self.assertIn("микрофону", state["message"])

    def test_managed_denial_is_not_presented_as_bypassable(self):
        message = RealtimeCaptureManager._error_message(
            {
                "code": "permission_managed_denied",
                "source": "system",
                "details": "",
            }
        )

        self.assertIn("политикой устройства", message)
        self.assertIn("не может обойти", message)


if __name__ == "__main__":
    unittest.main()
