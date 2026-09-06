import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
os.environ["TEST_ROLE_HEADER_ENABLED"] = "1"

from fastapi.testclient import TestClient
import main

class TestScenarioBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(cls.temp_dir.name, "builder.sqlite3")
        os.environ["COMMAND_HISTORY_DB"] = db_path
        main.COMMAND_HISTORY_DB = db_path
        main.init_command_history()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_01_schema_endpoint(self):
        resp = self.client.get("/api/v1/scenario-builder/schema")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("voice_profiles", data)
        self.assertIn("faces", data)
        self.assertIn("limits", data)
        self.assertIn("L0", data["limits"]["risk_levels_allowed"])
        self.assertIn("L5", data["limits"]["risk_levels_allowed"])

    def test_02_draft_auth_required(self):
        payload = {
            "scenario_id": "user-test-unauth",
            "version": "1.0.0",
            "title": "Unauth Test",
            "description": "desc",
            "risk_level": "L0",
            "required_capabilities": ["SPEAK"],
            "command": {"text": "hello", "face": "DEFAULT_STILL"}
        }
        resp = self.client.post("/api/v1/scenario-drafts", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"]["code"], "LOGIN_REQUIRED")

    def test_03_save_and_retrieve_draft(self):
        payload = {
            "scenario_id": "user-builder-test-01",
            "version": "1.0.0",
            "title": "Builder Unit Test",
            "description": "Testing builder save",
            "risk_level": "L1",
            "required_capabilities": ["SPEAK"],
            "command": {
                "steps": [
                    {"text": "สวัสดีครับ", "face": "HAPPY"},
                    {"text": "ยินดีให้บริการครับ", "face": "DEFAULT_STILL"}
                ]
            }
        }
        # 1. Operator creates draft
        res_op = self.client.post("/api/v1/scenario-drafts", json=payload, headers={"x-test-role": "operator"})
        self.assertEqual(res_op.status_code, 201)
        data = res_op.json()
        self.assertEqual(data["id"], "user-builder-test-01")
        self.assertEqual(data["source"], "builder")

        # 2. Reject non-user- prefix
        bad_id_payload = dict(payload, scenario_id="invalid-id-prefix")
        res_bad_id = self.client.post("/api/v1/scenario-drafts", json=bad_id_payload, headers={"x-test-role": "operator"})
        self.assertEqual(res_bad_id.status_code, 409)
        self.assertEqual(res_bad_id.json()["detail"]["code"], "DRAFT_ID_RESERVED")

        # 3. Reject risk level L8 in builder (even if valid L8 definition)
        bad_risk_payload = {
            "scenario_id": "user-danger-l8",
            "version": "1.0.0",
            "title": "L8 Motion Test",
            "description": "L8 test",
            "risk_level": "L8",
            "required_capabilities": ["SAFETY_SONAR", "SAFETY_DROP_LASER"],
            "command": {
                "autonomous_motion": {
                    "text": "ผมจะขยับเล็กน้อยครับ",
                    "voice_profile": "male_child",
                    "face": "CONFIDENT",
                    "safety": {
                        "base_motion_enabled": True,
                        "collision_guard_enabled": True,
                        "fall_guard_enabled": True,
                        "max_distance_m": 0.15,
                        "max_speed": 1,
                        "auto_stop_ms": 1500,
                    },
                    "motion": {"x": 0.15, "y": 0, "theta": 0, "speed": 1},
                }
            },
        }
        res_bad_risk = self.client.post("/api/v1/scenario-drafts", json=bad_risk_payload, headers={"x-test-role": "operator"})
        self.assertEqual(res_bad_risk.status_code, 422)
        self.assertEqual(res_bad_risk.json()["detail"]["code"], "DRAFT_RISK_LEVEL_NOT_ALLOWED")

        # 4. List drafts as operator
        res_list = self.client.get("/api/v1/scenario-drafts", headers={"x-test-role": "operator"})
        self.assertEqual(res_list.status_code, 200)
        drafts = res_list.json()["drafts"]
        self.assertTrue(any(d["id"] == "user-builder-test-01" for d in drafts))

        # 5. Viewer cannot delete draft
        res_del_viewer = self.client.delete("/api/v1/scenario-drafts/user-builder-test-01", headers={"x-test-role": "viewer"})
        self.assertEqual(res_del_viewer.status_code, 403)

        # 6. Admin can delete draft
        res_del_admin = self.client.delete("/api/v1/scenario-drafts/user-builder-test-01", headers={"x-test-role": "admin"})
        self.assertEqual(res_del_admin.status_code, 204)

if __name__ == "__main__":
    unittest.main()
