"""Small contract tests for the safe scenario-run vertical slice."""
import os
import sys
import tempfile
import asyncio
import unittest


class ScenarioRunContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["COMMAND_HISTORY_DB"] = os.path.join(cls.temp_dir.name, "scenario.sqlite3")
        os.environ["SCENARIO_REGISTRY_TOKEN"] = "test-registry-token"
        os.environ["ZENBO_DEVICE_PROVISIONING_TOKEN"] = "test-device-bootstrap-token"
        os.environ["MQTT_USERNAME"] = "zenbo-client"
        os.environ["MQTT_TOKEN"] = "test-mqtt-token"
        os.environ["MQTT_CLIENT_HOST"] = "mqtt.libn.kku.ac.th"
        os.environ["MQTT_CLIENT_PORT"] = "8883"
        os.environ["MQTT_CLIENT_TRANSPORT"] = "ssl"
        os.environ["ZENBO_DEVICE_ROBOT_SLUG"] = "booky-1"
        os.environ["APK_UPDATE_URL"] = ""
        os.environ["APK_UPDATE_VERSION_CODE"] = ""
        os.environ["APK_UPDATE_VERSION_NAME"] = ""
        os.environ["APK_UPDATE_SHA256"] = ""
        os.environ["LIFF_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "liff-app"))
        sys.path.insert(0, os.path.dirname(__file__))
        import main
        cls.core = main
        cls.core.db.init()
        cls.core.init_command_history()

    @classmethod
    def tearDownClass(cls):
        cls.core.db.close()
        cls.temp_dir.cleanup()

    def test_robot_discovery_reports_authoritative_core_relative_policy(self):
        from unittest.mock import patch
        with patch.object(self.core, "RELATIVE_MOTION_ENABLED", False), \
             patch.object(self.core, "RELATIVE_MOTION_MAX_SPEED", 7), \
             patch.object(self.core, "FIELD_ROLLOUT_MAX_LEVEL", 2), \
             patch.object(self.core.time, "time", return_value=100):
            result = asyncio.run(self.core.list_robots())
        policy = result["relative_motion"]
        self.assertIs(False, policy["enabled"])
        self.assertEqual(2, policy["max_body_speed_level"])
        self.assertEqual(100000, policy["reported_at_ms"])
        self.assertEqual(self.core.RELATIVE_MOTION_MAX_DISTANCE_M, policy["max_distance_m"])
        self.assertEqual(self.core.RELATIVE_MOTION_HARD_STOP_MS, policy["hard_stop_after_ms"])

    def test_motion_capability_freshness_is_not_renewed_by_ack_or_retained_heartbeat(self):
        slug = "freshness-regression"
        self.core._remember_robot(f"zenbo/{slug}/status/heartbeat", '{"robot_slug":"spoofed"}')
        self.assertEqual(slug, self.core.robot_registry[slug]["robot_slug"])
        received = self.core.robot_registry[slug]["heartbeat_received_at_ms"]
        self.assertGreater(received, 0)
        self.core.robot_registry[slug]["last_seen"] = 1
        self.core._remember_robot(f"zenbo/{slug}/status/robot_state", '{"state":"READY"}')
        self.assertEqual(1, self.core.robot_registry[slug]["last_seen"])
        self.assertEqual(received, self.core.robot_registry[slug]["heartbeat_received_at_ms"])
        self.core._remember_robot(f"zenbo/{slug}/status/heartbeat", '{"last_seen":9999999999}', retained=True)
        self.assertEqual(0, self.core.robot_registry[slug]["last_seen"])
        self.assertEqual(0, self.core.robot_registry[slug]["heartbeat_received_at_ms"])

    def test_relative_ack_is_persisted_as_apk_evidence_without_physical_claim(self):
        from unittest.mock import patch
        with patch.object(self.core, "record_command_history") as record:
            self.core._remember_robot("zenbo/ack-regression/status/motion_ack",
                '{"command_id":"trace-1","state":"SDK_STOP_REQUESTED"}')
        args = record.call_args.args
        self.assertEqual("apk_motion_ack", args[1])
        self.assertEqual("SDK_STOP_REQUESTED", args[2])
        self.assertEqual("trace-1", args[3]["acknowledgement"]["command_id"])
        self.assertFalse(args[3]["physical_velocity_verified"])

    def test_incomplete_heartbeat_withdraws_previous_readiness(self):
        slug = "incomplete-heartbeat"
        self.core._remember_robot(f"zenbo/{slug}/status/heartbeat", '''{
            "motion":{"body_relative":{"supported":true}}, "robot_api_ready":true,
            "safety_monitor":{"active":true}, "apk_sha256":"approved", "version_name":"test"
        }''')
        self.core._remember_robot(f"zenbo/{slug}/status/heartbeat", '{}')
        robot = self.core.robot_registry[slug]
        self.assertGreater(robot["heartbeat_received_at_ms"], 0)
        for key in ("motion", "robot_api_ready", "safety_monitor", "apk_sha256", "version_name"):
            self.assertNotIn(key, robot)
        self.assertFalse(self.core._field_calibration_for_permit(robot)["ready"])

    def test_trace_api_returns_correlated_receipts_and_heartbeat_timestamp(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.core.app)
        self.core.record_command_history("trace-api", "relative_motion", "MQTT_PUBLISHED", {
            "envelope": {"command_id": "api-trace-1"}})
        self.core._remember_robot("zenbo/trace-api/status/heartbeat", '{"heartbeat_received_at_ms":1}')
        self.core._remember_robot("zenbo/trace-api/status/motion_ack",
            '{"command_id":"api-trace-1","state":"SDK_SUBMITTED"}')
        trace = client.get("/api/v1/robots/trace-api/commands/api-trace-1/trace")
        self.assertEqual(200, trace.status_code)
        self.assertEqual(["MQTT_PUBLISHED", "SDK_SUBMITTED"],
                         [event["status"] for event in trace.json()["events"]])
        self.assertFalse(trace.json()["physical_motion_verified"])
        self.assertEqual(404, client.get("/api/v1/robots/wrong/commands/api-trace-1/trace").status_code)
        robots = client.get("/api/v1/robots").json()["robots"]
        robot = next(item for item in robots if item["robot_slug"] == "trace-api")
        self.assertGreater(robot["heartbeat_received_at_ms"], 1)

    def test_intro_scenario_requires_confirmation_and_is_idempotent(self):
        request = self.core.ScenarioRunRequest(
            scenario_id="intro_booky",
            robot_slug="booky-1",
            idempotency_key="voice-session-7",
            source="voice_client",
        )

        first = self.core.create_scenario_run_record(request)
        second = self.core.create_scenario_run_record(request)

        self.assertEqual("AWAITING_CONFIRMATION", first["state"])
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual("L0", first["risk_level"])

    def test_liff_static_and_api_proxy_paths_are_available(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.core.app)
        page = client.get("/liff/control/")
        self.assertEqual(200, page.status_code)
        self.assertIn("Zenbo Joystick Control", page.text)
        scenario_page = client.get("/liff/scenarios/")
        self.assertEqual(200, scenario_page.status_code)
        self.assertIn("Booky Scenario Runner", scenario_page.text)
        supervisor_page = client.get("/liff/autonomy/")
        self.assertEqual(200, supervisor_page.status_code)
        self.assertIn("Safety monitor", supervisor_page.text)
        builder_page = client.get("/liff/scenario/builder/")
        self.assertEqual(200, builder_page.status_code)
        self.assertIn("Scenario Builder", builder_page.text)
        theme_css = client.get("/liff/shared/zenbo-theme.css")
        self.assertEqual(200, theme_css.status_code)
        actions_js = client.get("/liff/shared/zenbo-actions.js")
        self.assertEqual(200, actions_js.status_code)
        self.assertIn("Body_twist_1", actions_js.text)
        api = client.get("/liff-api/api/v1/scenarios")
        self.assertEqual(200, api.status_code)
        scenarios = {item["id"]: item for item in api.json()["scenarios"]}
        self.assertIn("intro_booky", scenarios)
        self.assertEqual("ต้อนรับ", scenarios["library_welcome"]["category"])

    def test_intro_scenario_command_is_stationary_and_carries_run_id(self):
        command = self.core.build_scenario_command("intro_booky", "run-123", "booky-1")

        self.assertEqual("run-123", command["scenario_run_id"])
        self.assertEqual("booky-1", command["robot_slug"])
        self.assertTrue(command["text"])
        self.assertNotIn("motion", command)
        self.assertNotIn("action", command)
        self.assertNotIn("behavior", command)
        self.assertTrue(command["head_sequence"])
        self.assertTrue(command["after_speech"])

    def test_builtin_scenario_pack_is_l0_and_exposes_catalog_metadata(self):
        expected_ids = {"intro_booky", "library_welcome", "library_service_help", "queue_ready", "library_goodbye"}
        self.assertTrue(expected_ids.issubset(self.core.SCENARIO_REGISTRY))
        blocked = {"motion", "action", "behavior", "vision", "youtube", "navigation", "remote_control", "emotional_action"}
        for scenario_id in expected_ids:
            scenario = self.core.SCENARIO_REGISTRY[scenario_id]
            with self.subTest(scenario_id=scenario_id):
                self.assertEqual("L0", scenario["risk_level"])
                self.assertEqual("REQUIRED", scenario["confirmation"])
                self.assertTrue(scenario["command"]["text"])
                self.assertFalse(blocked.intersection(scenario["command"]))
                metadata = self.core.scenario_public_metadata(scenario_id, scenario)
                self.assertTrue(metadata["icon"])
                self.assertTrue(metadata["category"])
                self.assertTrue(metadata["behavior"]["face_description"])
                self.assertTrue(metadata["behavior"]["gesture_description"])
                self.assertEqual("อยู่กับที่ ไม่สั่งฐานเคลื่อนที่", metadata["behavior"]["base_motion"])

    def test_every_catalog_scenario_exposes_visual_behavior_and_ready_commands_have_cues(self):
        for preset_id, preset in self.core.PRESENTATION_CATALOG.items():
            with self.subTest(preset_id=preset_id):
                metadata = self.core.presentation_public_metadata(preset_id, preset)
                behavior = metadata["behavior"]
                self.assertTrue(behavior["face_description"])
                self.assertTrue(behavior["gesture_description"])
                self.assertEqual("อยู่กับที่ ไม่สั่งฐานเคลื่อนที่", behavior["base_motion"])
                if preset["availability"] == "ready":
                    command = self.core.json.loads(self.core.json.dumps(preset.get("command", {})))
                    if command.get("steps"):
                        for step in command["steps"]:
                            self.core.apply_visual_behavior_contract(step, step["face"])
                            self.assertTrue(step.get("head_sequence"))
                            self.assertTrue(step.get("after_speech"))
                    else:
                        self.core.apply_visual_behavior_contract(command, preset.get("visual_profile"))
                        self.assertTrue(command.get("face"))
                        self.assertTrue(command.get("head_sequence"))
                        self.assertTrue(command.get("after_speech"))

    def test_story_time_is_a_stoppable_stationary_script(self):
        request = self.core.PresentationRequest(preset_id="story-time", robot_slug="booky-story")
        command = asyncio.run(self.core.build_presentation_command(request))
        self.assertEqual("booky-story", command["robot_slug"])
        self.assertGreaterEqual(len(command["script"]["steps"]), 2)
        self.assertNotIn("motion", command)
        self.assertNotIn("action", command)
        for step in command["script"]["steps"]:
            self.assertTrue(step["text"])
            self.assertTrue(step["face"])
            self.assertTrue(step["head_sequence"])

    def test_library_map_preset_is_stationary_and_uses_the_navigation_route(self):
        request = self.core.PresentationRequest(
            preset_id="library-map-open", robot_slug="booky-map",
            variables={"from_location": "1102", "to": "1401"},
        )
        original_route = self.core.get_navigation_route

        async def fake_route(from_location, to):
            self.assertEqual("1102", from_location)
            self.assertEqual("1401", to)
            return {"route": {"display_url": "http://10.101.118.149:8032/zenbo-route", "speech_text": "เริ่มจาก 1102 ไป 1401", "step_speeches": ["เดินตามเส้นทางบนจอ"]}}

        self.core.get_navigation_route = fake_route
        try:
            command = asyncio.run(self.core.build_presentation_command(request))
        finally:
            self.core.get_navigation_route = original_route
        self.assertEqual("http://10.101.118.149:8032/zenbo-route", command["navigation"]["display_url"])
        self.assertEqual("เริ่มจาก 1102 ไป 1401", command["navigation"]["speech_text"])
        self.assertTrue(command["face"])
        self.assertTrue(command["head_sequence"])
        self.assertNotIn("motion", command)
        with self.assertRaises(Exception):
            self.core.NavigationCommand(display_url="https://example.com/", speech_text="unsafe")

    def test_library_rag_preset_is_stationary_and_opens_only_the_trusted_rag_url(self):
        request = self.core.PresentationRequest(preset_id="library-rag-open", robot_slug="booky-rag")
        original_fetch = self.core.fetch_library_rag_answer

        async def fake_fetch(question):
            self.assertEqual("CDS คืออะไร?", question)
            return "CDS เป็นบริการยืมทรัพยากรระหว่างห้องสมุดครับ"

        self.core.fetch_library_rag_answer = fake_fetch
        try:
            command = asyncio.run(self.core.build_presentation_command(request))
        finally:
            self.core.fetch_library_rag_answer = original_fetch
        self.assertEqual("https://lib.kku.ac.th/rag/", command["navigation"]["display_url"])
        self.assertIn("CDS เป็นบริการ", command["text"])
        self.assertNotIn("motion", command)

    def test_custom_thai_speech_is_bounded_and_stationary(self):
        request = self.core.PresentationRequest(
            preset_id="speak-thai-message",
            robot_slug="booky-speech",
            variables={"speech_text": "ยินดีต้อนรับทุกท่านครับ"},
        )
        command = asyncio.run(self.core.build_presentation_command(request))
        self.assertEqual("ยินดีต้อนรับทุกท่านครับ", command["text"])
        self.assertEqual("booky-speech", command["robot_slug"])
        self.assertTrue(command["head_sequence"])
        self.assertNotIn("motion", command)
        self.assertNotIn("navigation", command)
        with self.assertRaises(Exception):
            asyncio.run(self.core.build_presentation_command(self.core.PresentationRequest(
                preset_id="speak-thai-message", robot_slug="booky-speech",
                variables={"speech_text": "x" * 241},
            )))

    def test_hackathon_event_name_is_the_default_for_ceremonial_presets(self):
        expected = "KKU Digital Transformation & AI Hackathon 2026 “The Great Reset of Education and Management” ปลุกพลังคน พลิกโฉมองค์กร ด้วยนวัตกรรม AI"
        for preset_id in ("judge-greeting", "event-opening"):
            preset = self.core.PRESENTATION_CATALOG[preset_id]
            field = next(field for field in preset["fields"] if field["name"] == "event_name")
            self.assertEqual(expected, field["default"])
            self.assertGreaterEqual(field["max_length"], len(expected))

    def test_presentation_batch_dispatches_each_explicit_robot_without_a_broadcast(self):
        request = self.core.PresentationBatchRequest(
            preset_id="library-map-open", robot_slugs=["booky-a", "booky-b"]
        )
        dispatched = []

        async def fake_interact(command):
            dispatched.append(command.robot_slug)
            return {"status": "dispatched", "history_id": len(dispatched)}

        async def fake_navigation_route(from_location, to):
            return {"route": {
                "display_url": "https://lib.kku.ac.th/map/",
                "speech_text": "Test library route",
                "step_speeches": ["Test first step"],
            }}

        original_interact = self.core.robot_interact
        original_navigation_route = self.core.get_navigation_route
        self.core.robot_interact = fake_interact
        self.core.get_navigation_route = fake_navigation_route
        try:
            result = asyncio.run(self.core.start_presentation_batch(request))
        finally:
            self.core.robot_interact = original_interact
            self.core.get_navigation_route = original_navigation_route

        self.assertEqual(["booky-a", "booky-b"], dispatched)
        self.assertEqual("library-map-open", result["preset_id"])
        self.assertEqual(2, result["summary"]["dispatched"])
        self.assertEqual(["booky-a", "booky-b"], [item["robot_slug"] for item in result["results"]])
        self.assertTrue(all(item["status"] == "dispatched" for item in result["results"]))

        with self.assertRaises(Exception):
            self.core.PresentationBatchRequest(
                preset_id="library-map-open", robot_slugs=["booky-a", "booky-a"]
            )

    def test_trusted_registry_import_is_l0_and_can_create_a_run(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="library-ready",
            version="1.0.0",
            title="พร้อมให้บริการ",
            description="กล่าวพร้อมให้บริการโดยไม่เคลื่อนฐาน",
            required_capabilities=["THAI_TTS", "EXPRESSION"],
            command={"text": "บุ๊คกี้พร้อมให้บริการครับ", "voice_profile": "male_child", "face": "HAPPY"},
        )
        imported = self.core.import_scenario_definition(definition)
        self.assertEqual("L0", imported["risk_level"])
        self.assertEqual("REQUIRED", imported["confirmation"])
        run = self.core.create_scenario_run_record(self.core.ScenarioRunRequest(
            scenario_id="library-ready", robot_slug="booky-3", idempotency_key="registry-import-9"
        ))
        self.assertEqual("1.0.0", run["scenario_version"])

    def test_l1_registry_script_is_multi_step_but_rejects_motion_and_media(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="library-tour-l1",
            version="1.0.0",
            title="แนะนำบริการเป็นช่วง",
            description="พูดทีละช่วงพร้อมสีหน้าและท่าศีรษะ โดยไม่เคลื่อนฐาน",
            risk_level="L1",
            required_capabilities=["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS"],
            command={"steps": [
                {"text": "เริ่มแนะนำบริการครับ", "voice_profile": "male_child", "face": "HAPPY"},
                {"text": "เลือกบริการที่ต้องการได้เลยครับ", "voice_profile": "male_child", "face": "INTERESTED",
                 "wheel_lights": {"mode": "breath", "color": "#00AEEF", "brightness": 10}},
            ]},
        )
        imported = self.core.import_scenario_definition(definition)
        self.assertEqual("L1", imported["risk_level"])
        command = self.core.build_scenario_command("library-tour-l1", "run-l1", "booky-l1")
        self.assertEqual(2, len(command["script"]["steps"]))
        self.assertTrue(all(step["head_sequence"] for step in command["script"]["steps"]))
        self.assertNotIn("motion", command)
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="unsafe-l1", version="1.0.0", title="ไม่ปลอดภัย", description="ต้องไม่ผ่าน",
                risk_level="L1", command={"steps": [
                    {"text": "ห้าม", "face": "HAPPY", "motion": {"x": 1}},
                    {"text": "ห้าม", "face": "EXPECTING"},
                ]},
            )

    def test_l2_registry_branches_on_stationary_person_detection_only(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="visitor-greeting-l2", version="1.0.0", title="ทักทายผู้ใช้", description="ทักทายเมื่อพบผู้ใช้",
            risk_level="L2", required_capabilities=["THAI_TTS", "EXPRESSION", "HEAD", "VISION_PERSON"],
            command={
                "vision_gate": {"action": "detect_person", "timeout_ms": 8000},
                "on_detect": {"steps": [{"text": "สวัสดีครับ ยินดีต้อนรับครับ", "face": "HAPPY"}]},
                "on_timeout": {"steps": [{"text": "ผมยังไม่พบผู้ใช้ครับ", "face": "EXPECTING"}]},
            },
        )
        imported = self.core.import_scenario_definition(definition)
        self.assertEqual("L2", imported["risk_level"])
        command = self.core.build_scenario_command("visitor-greeting-l2", "run-l2", "booky-l2")
        self.assertEqual("detect_person", command["interactive"]["vision_gate"]["action"])
        self.assertTrue(command["interactive"]["on_detect"]["steps"][0]["head_sequence"])
        self.assertTrue(command["interactive"]["on_timeout"]["steps"][0]["after_speech"])
        self.assertNotIn("motion", command["interactive"])
        metadata = self.core.scenario_public_metadata(
            "visitor-greeting-l2", self.core.get_scenario_definition("visitor-greeting-l2")
        )
        self.assertEqual("HAPPY", metadata["behavior"]["face"])
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="unsafe-l2", version="1.0.0", title="ไม่ปลอดภัย", description="ต้องไม่ผ่าน", risk_level="L2",
                command={"vision_gate": {"action": "recognize_person"}, "on_detect": {"steps": [{"text": "ห้าม", "face": "HAPPY"}]}, "on_timeout": {"steps": [{"text": "ห้าม", "face": "EXPECTING"}]}},
            )

    def test_l3_registry_accepts_anonymous_gesture_point_but_not_person_detection(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="gesture-ack-l3", version="1.0.0", title="ตอบรับการชี้", description="ตอบรับท่าชี้โดยไม่บันทึกพิกัด",
            risk_level="L3", required_capabilities=["THAI_TTS", "EXPRESSION", "HEAD", "GESTURE_POINT"],
            command={
                "vision_gate": {"action": "gesture_point", "timeout_ms": 7000},
                "on_detect": {"steps": [{"text": "ผมเห็นท่าชี้ของคุณแล้วครับ", "face": "INTERESTED"}]},
                "on_timeout": {"steps": [{"text": "หากพร้อมแล้ว ลองชี้อีกครั้งด้านหน้าผมครับ", "face": "EXPECTING"}]},
            },
        )
        imported = self.core.import_scenario_definition(definition)
        self.assertEqual("L3", imported["risk_level"])
        command = self.core.build_scenario_command("gesture-ack-l3", "run-l3", "booky-l3")
        self.assertEqual("gesture_point", command["interactive"]["vision_gate"]["action"])
        self.assertTrue(command["interactive"]["on_detect"]["steps"][0]["head_sequence"])
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="unsafe-l3", version="1.0.0", title="ไม่ปลอดภัย", description="ต้องไม่ผ่าน", risk_level="L3",
                command={"vision_gate": {"action": "detect_person"}, "on_detect": {"steps": [{"text": "ห้าม", "face": "HAPPY"}]}, "on_timeout": {"steps": [{"text": "ห้าม", "face": "EXPECTING"}]}},
            )

    def test_l4_registry_requires_person_then_gesture_without_motion(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="guided-gesture-l4", version="1.0.0", title="ต้อนรับและรอการชี้", description="โต้ตอบสองจังหวะแบบอยู่กับที่",
            risk_level="L4", required_capabilities=["THAI_TTS", "EXPRESSION", "HEAD", "VISION_PERSON", "GESTURE_POINT"],
            command={
                "first_gate": {"action": "detect_person", "timeout_ms": 8000},
                "prompt": {"text": "ผมเห็นคุณแล้วครับ กรุณาชี้เพื่อบอกว่าต้องการความช่วยเหลือ", "face": "INTERESTED"},
                "second_gate": {"action": "gesture_point", "timeout_ms": 7000},
                "on_first_timeout": {"steps": [{"text": "ผมยังไม่พบผู้ใช้ครับ", "face": "EXPECTING"}]},
                "on_second_detect": {"steps": [{"text": "รับทราบครับ ผมพร้อมช่วยเหลือครับ", "face": "HAPPY"}]},
                "on_second_timeout": {"steps": [{"text": "หากพร้อมแล้ว ลองชี้อีกครั้งได้เลยครับ", "face": "EXPECTING"}]},
            },
        )
        imported = self.core.import_scenario_definition(definition)
        self.assertEqual("L4", imported["risk_level"])
        command = self.core.build_scenario_command("guided-gesture-l4", "run-l4", "booky-l4")
        self.assertEqual("detect_person", command["interactive_sequence"]["first_gate"]["action"])
        self.assertEqual("gesture_point", command["interactive_sequence"]["second_gate"]["action"])
        self.assertTrue(command["interactive_sequence"]["prompt"]["head_sequence"])
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="unsafe-l4", version="1.0.0", title="ไม่ปลอดภัย", description="ต้องไม่ผ่าน", risk_level="L4",
                command={"first_gate": {"action": "gesture_point"}, "prompt": {"text": "ห้าม", "face": "HAPPY"}, "second_gate": {"action": "detect_person"}, "on_first_timeout": {"steps": [{"text": "ห้าม", "face": "EXPECTING"}]}, "on_second_detect": {"steps": [{"text": "ห้าม", "face": "HAPPY"}]}, "on_second_timeout": {"steps": [{"text": "ห้าม", "face": "EXPECTING"}]}},
            )

    def test_l5_registry_opens_only_trusted_library_map_after_gesture(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="map-after-gesture-l5", version="1.0.0", title="เปิดแผนที่หลังการชี้", description="เปิดแผนที่ที่เชื่อถือได้เท่านั้น",
            risk_level="L5", required_capabilities=["THAI_TTS", "EXPRESSION", "HEAD", "VISION_PERSON", "GESTURE_POINT", "DISPLAY_URL"],
            command={
                "first_gate": {"action": "detect_person", "timeout_ms": 8000},
                "prompt": {"text": "หากต้องการแผนที่ กรุณาชี้มาทางผมครับ", "face": "INTERESTED"},
                "second_gate": {"action": "gesture_point", "timeout_ms": 7000},
                "on_first_timeout": {"steps": [{"text": "ผมยังไม่พบผู้ใช้ครับ", "face": "EXPECTING"}]},
                "on_second_detect": {"steps": [{"text": "ผมกำลังเปิดแผนที่ห้องสมุดให้ครับ", "face": "HAPPY"}], "navigation": {"display_url": "https://lib.kku.ac.th/map/", "speech_text": "ผมกำลังเปิดแผนที่ห้องสมุดให้ครับ"}},
                "on_second_timeout": {"steps": [{"text": "หากพร้อมแล้ว ลองชี้อีกครั้งได้เลยครับ", "face": "EXPECTING"}]},
            },
        )
        imported = self.core.import_scenario_definition(definition)
        self.assertEqual("L5", imported["risk_level"])
        command = self.core.build_scenario_command("map-after-gesture-l5", "run-l5", "booky-l5")
        detected = command["interactive_sequence"]["on_second_detect"]
        self.assertEqual("https://lib.kku.ac.th/map/", detected["navigation"]["display_url"])
        self.assertTrue(detected["steps"][0]["head_sequence"])
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="unsafe-l5", version="1.0.0", title="ไม่ปลอดภัย", description="ต้องไม่ผ่าน", risk_level="L5",
                command={"first_gate": {"action": "detect_person"}, "prompt": {"text": "ห้าม", "face": "HAPPY"}, "second_gate": {"action": "gesture_point"}, "on_first_timeout": {"steps": [{"text": "ห้าม", "face": "EXPECTING"}]}, "on_second_detect": {"steps": [{"text": "ห้าม", "face": "HAPPY"}], "navigation": {"display_url": "https://example.com/", "speech_text": "ห้าม"}}, "on_second_timeout": {"steps": [{"text": "ห้าม", "face": "EXPECTING"}]}},
            )

    def test_l6_field_ready_gate_blocks_dispatch_until_safety_heartbeat_is_ready(self):
        request = self.core.ScenarioRunRequest(
            scenario_id="library_map_field_ready_l6", robot_slug="booky-l6", idempotency_key="l6-ready-key"
        )
        run = self.core.create_scenario_run_record(request)
        with self.assertRaises(self.core.HTTPException) as blocked:
            asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        self.assertEqual(409, blocked.exception.status_code)
        self.assertEqual("SCENARIO_FIELD_READINESS_REQUIRED", blocked.exception.detail["code"])

        self.core._remember_robot("zenbo/booky-l6/status/heartbeat", '''{
            "version_name":"1.8.5-l6-field-ready", "topic_prefix":"zenbo/booky-l6",
            "robot_api_ready":true, "safety_monitor_active":true,
            "safety_guard":{"collision_guard_enabled":true,"fall_guard_enabled":true,"base_motion_enabled":false},
            "capabilities":["THAI_TTS","EXPRESSION","HEAD","WHEEL_LIGHTS","VISION_PERSON","GESTURE_POINT","DISPLAY_URL"]
        }''')
        published = []
        original_publish = self.core.mqtt_client.publish
        self.core.mqtt_client.publish = lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            result = asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        finally:
            self.core.mqtt_client.publish = original_publish
        self.assertEqual("DISPATCHED", result["run"]["state"])
        self.assertTrue(published)

    def test_l7_requires_fresh_operator_attestation_after_field_readiness(self):
        robot_slug = "booky-l7"
        self.core._remember_robot(f"zenbo/{robot_slug}/status/heartbeat", '''{
            "version_name":"1.8.6-l7-supervised", "topic_prefix":"zenbo/booky-l7",
            "robot_api_ready":true, "safety_monitor_active":true,
            "safety_guard":{"collision_guard_enabled":true,"fall_guard_enabled":true,"base_motion_enabled":false},
            "capabilities":["THAI_TTS","EXPRESSION","HEAD","WHEEL_LIGHTS","VISION_PERSON","GESTURE_POINT","DISPLAY_URL"]
        }''')
        run = self.core.create_scenario_run_record(self.core.ScenarioRunRequest(
            scenario_id="library_map_supervised_l7", robot_slug=robot_slug, idempotency_key="l7-attestation-key"
        ))
        with self.assertRaises(self.core.HTTPException) as blocked:
            asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        self.assertEqual("SCENARIO_FIELD_ATTESTATION_REQUIRED", blocked.exception.detail["code"])

        now = int(self.core.time.time() * 1000)
        with self.core.command_history_lock, self.core.db.connection(self.core.COMMAND_HISTORY_DB) as connection:
            connection.execute("INSERT INTO robot_field_attestations (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?)",
                               (robot_slug, now, "operator", '{"tts_checked":true,"vision_checked":true,"display_checked":true}'))
        published = []
        original_publish = self.core.mqtt_client.publish
        self.core.mqtt_client.publish = lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            result = asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        finally:
            self.core.mqtt_client.publish = original_publish
        self.assertEqual("DISPATCHED", result["run"]["state"])
        self.assertEqual("READY", self.core.get_field_attestation(robot_slug)["state"])

    def test_l8_allows_only_guarded_forward_micro_motion_and_is_feature_gated(self):
        definition = self.core.ScenarioDefinitionRequest(
            scenario_id="guarded-motion-l8", version="1.0.0", title="ขยับสั้น", description="ขยับตรงระยะสั้นพร้อมเซนเซอร์",
            risk_level="L8", required_capabilities=["SAFETY_SONAR", "SAFETY_DROP_LASER"],
            command={"autonomous_motion": {
                "text": "ผมจะขยับเล็กน้อยครับ", "voice_profile": "male_child", "face": "CONFIDENT",
                "safety": {"base_motion_enabled": True, "collision_guard_enabled": True, "fall_guard_enabled": True,
                           "max_distance_m": 0.15, "max_speed": 1, "auto_stop_ms": 1500},
                "motion": {"x": 0.15, "y": 0, "theta": 0, "speed": 1},
            }},
        )
        self.core.import_scenario_definition(definition)
        command = self.core.build_scenario_command("guarded-motion-l8", "run-l8", "booky-l8")
        self.assertEqual(0.15, command["motion"]["x"])
        self.assertTrue(command["safety"]["collision_guard_enabled"])
        self.assertTrue(command["head_sequence"])
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="unsafe-motion-l8", version="1.0.0", title="ห้าม", description="ต้องไม่ผ่าน", risk_level="L8",
                command={"autonomous_motion": {"text": "ห้าม", "face": "HAPPY",
                    "safety": {"base_motion_enabled": True, "collision_guard_enabled": True, "fall_guard_enabled": True,
                               "max_distance_m": 0.15, "max_speed": 1, "auto_stop_ms": 1500},
                    "motion": {"x": 0.20, "y": 0, "theta": 0, "speed": 1}}},
            )

        robot_slug = "booky-l8"
        self.core._remember_robot(f"zenbo/{robot_slug}/status/heartbeat", '''{
            "version_name":"1.8.7-l8", "topic_prefix":"zenbo/booky-l8",
            "robot_api_ready":true, "safety_monitor_active":true,
            "safety_guard":{"collision_guard_enabled":true,"fall_guard_enabled":true,"base_motion_enabled":true,"max_distance_m":0.15,"max_speed":1,"auto_stop_ms":1500},
            "capabilities":["THAI_TTS","EXPRESSION","HEAD","WHEEL_LIGHTS","SAFETY_SONAR","SAFETY_DROP_LASER"]
        }''')
        run = self.core.create_scenario_run_record(self.core.ScenarioRunRequest(
            scenario_id="guarded-motion-l8", robot_slug=robot_slug, idempotency_key="l8-feature-gate"
        ))
        now = int(self.core.time.time() * 1000)
        with self.core.command_history_lock, self.core.db.connection(self.core.COMMAND_HISTORY_DB) as connection:
            connection.execute("INSERT INTO robot_field_attestations (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?)",
                               (robot_slug, now, "operator", '{"tts_checked":true,"vision_checked":true,"display_checked":true}'))
        with self.assertRaises(self.core.HTTPException) as blocked:
            asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        self.assertEqual("AUTONOMOUS_MOTION_DISABLED", blocked.exception.detail["code"])
        published = []
        original_enabled = self.core.AUTONOMOUS_MOTION_ENABLED
        original_publish = self.core.mqtt_client.publish
        self.core.AUTONOMOUS_MOTION_ENABLED = True
        self.core.mqtt_client.publish = lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            result = asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        finally:
            self.core.AUTONOMOUS_MOTION_ENABLED = original_enabled
            self.core.mqtt_client.publish = original_publish
        self.assertEqual("DISPATCHED", result["run"]["state"])
        self.assertIn('"x": 0.15', published[0][1])
        self.core._record_scenario_client_event({"run_id": run["run_id"], "state": "CLIENT_RECEIVED"})
        self.core._record_scenario_client_event({"run_id": run["run_id"], "state": "SPEECH_COMPLETED"})
        self.assertEqual("RUNNING", self.core.get_scenario_run_record(run["run_id"])["state"])
        self.core._record_scenario_client_event({"run_id": run["run_id"], "state": "MOTION_COMPLETED"})
        self.assertEqual("SUCCEEDED", self.core.get_scenario_run_record(run["run_id"])["state"])
        timeline = self.core.scenario_run_events(run["run_id"])
        self.assertEqual("AWAITING_CONFIRMATION", timeline[0]["state"])
        self.assertIn("MOTION_COMPLETED", [event["state"] for event in timeline])
        from fastapi.testclient import TestClient
        response = TestClient(self.core.app).get(f"/api/v1/scenario-runs/{run['run_id']}/events")
        self.assertEqual(200, response.status_code)
        self.assertEqual(timeline, response.json()["events"])
        self.core._record_scenario_client_event({"run_id": "unknown-run", "state": "MOTION_COMPLETED"})
        self.assertEqual([], self.core.scenario_run_events("unknown-run"))

    def test_l10_calibrated_route_requires_one_confirmed_l8_segment_at_a_time(self):
        route = self.core.import_calibrated_route(self.core.CalibratedRouteDefinitionRequest(
            route_id="desk-ahead", version="1.0.0", title="ไปข้างหน้าจุดบริการ",
            segments=[{"label": "ช่วงที่ 1", "command": {
                "text": "รับคำสั่งครับ ผมจะขยับช่วงที่หนึ่ง", "voice_profile": "male_child", "face": "CONFIDENT",
                "safety": {"base_motion_enabled": True, "collision_guard_enabled": True, "fall_guard_enabled": True,
                           "max_distance_m": 0.15, "max_speed": 1, "auto_stop_ms": 1500},
                "motion": {"x": 0.15, "y": 0, "theta": 0, "speed": 1},
            }}],
        ))
        self.assertEqual(1, route["segment_count"])
        certification = self.core.certify_calibrated_route("desk-ahead", self.core.RouteCertificationRequest(
            operator_name="operator", path_clearance_checked=True, segment_measurements_checked=True,
            emergency_stop_checked=True, note="ตรวจเส้นทางแล้ว",
        ))
        self.assertEqual("READY", certification["state"])
        robot_slug = "booky-l10"
        self.core._remember_robot(f"zenbo/{robot_slug}/status/heartbeat", '''{
            "version_name":"1.8.8-l9", "topic_prefix":"zenbo/booky-l10",
            "robot_api_ready":true, "safety_monitor_active":true,
            "safety_guard":{"collision_guard_enabled":true,"fall_guard_enabled":true,"base_motion_enabled":true,"max_distance_m":0.15,"max_speed":1,"auto_stop_ms":1500},
            "capabilities":["THAI_TTS","EXPRESSION","HEAD","WHEEL_LIGHTS","SAFETY_SONAR","SAFETY_DROP_LASER","CALIBRATED_ROUTE"]
        }''')
        now = int(self.core.time.time() * 1000)
        with self.core.command_history_lock, self.core.db.connection(self.core.COMMAND_HISTORY_DB) as connection:
            connection.execute("INSERT INTO robot_field_attestations (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?)",
                               (robot_slug, now, "operator", '{"tts_checked":true,"vision_checked":true,"display_checked":true}'))
        original_governance = self.core.AUTONOMY_GOVERNANCE_REQUIRED
        self.core.AUTONOMY_GOVERNANCE_REQUIRED = False
        try:
            route_run = self.core.create_calibrated_route_run(self.core.CalibratedRouteRunRequest(
                route_id="desk-ahead", robot_slug=robot_slug, idempotency_key="l10-route-key"
            ))
        finally:
            self.core.AUTONOMY_GOVERNANCE_REQUIRED = original_governance
        self.assertEqual("AWAITING_SEGMENT_CONFIRMATION", route_run["state"])
        published, original_enabled, original_publish = [], self.core.AUTONOMOUS_MOTION_ENABLED, self.core.mqtt_client.publish
        original_governance = self.core.AUTONOMY_GOVERNANCE_REQUIRED
        self.core.AUTONOMOUS_MOTION_ENABLED = True
        self.core.AUTONOMY_GOVERNANCE_REQUIRED = False
        self.core.mqtt_client.publish = lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            result = asyncio.run(self.core.confirm_next_calibrated_route_segment(route_run["route_run_id"]))
        finally:
            self.core.AUTONOMOUS_MOTION_ENABLED, self.core.AUTONOMY_GOVERNANCE_REQUIRED, self.core.mqtt_client.publish = original_enabled, original_governance, original_publish
        self.assertEqual("SEGMENT_DISPATCHED", result["route_run"]["state"])
        segment_run_id = result["route_run"]["active_scenario_run_id"]
        self.assertTrue(segment_run_id)
        self.assertIn('"x": 0.15', published[0][1])
        self.core._record_scenario_client_event({"run_id": segment_run_id, "state": "CLIENT_RECEIVED"})
        self.core._record_scenario_client_event({"run_id": segment_run_id, "state": "MOTION_COMPLETED"})
        completed = self.core.refresh_calibrated_route_run(route_run["route_run_id"])
        self.assertEqual("COMPLETED", completed["state"])

    def test_l11_recovery_requires_new_attestation_after_safety_stop(self):
        self.core.import_calibrated_route(self.core.CalibratedRouteDefinitionRequest(
            route_id="recovery-ahead", version="1.0.0", title="ทดสอบกู้เส้นทาง",
            segments=[{"label": "ช่วงที่ 1", "command": {
                "text": "ขยับ", "face": "CONFIDENT",
                "safety": {"base_motion_enabled": True, "collision_guard_enabled": True, "fall_guard_enabled": True,
                           "max_distance_m": 0.15, "max_speed": 1, "auto_stop_ms": 1500},
                "motion": {"x": 0.15, "y": 0, "theta": 0, "speed": 1},
            }}],
        ))
        now = int(self.core.time.time() * 1000)
        route_run_id, robot_slug = "recovery-route-run", "booky-recovery"
        with self.core.command_history_lock, self.core.db.connection(self.core.COMMAND_HISTORY_DB) as connection:
            connection.execute("INSERT INTO calibrated_route_runs (route_run_id, route_id, robot_slug, idempotency_key, current_segment, state, active_scenario_run_id, created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (route_run_id, "recovery-ahead", robot_slug, "recovery-key", 0, "RECOVERY_REQUIRED", None, now, now))
            connection.execute("INSERT INTO calibrated_route_recoveries (route_run_id, recovery_required_at_ms, note) VALUES (?, ?, ?)", (route_run_id, now, "sensor stop"))
            connection.execute("INSERT INTO robot_field_attestations (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?)",
                               (robot_slug, now - 1, "operator", '{"tts_checked":true,"vision_checked":true,"display_checked":true}'))
        request = self.core.RouteRecoveryRequest(operator_name="operator", action="retry", note="ตรวจใหม่แล้ว")
        original_governance = self.core.AUTONOMY_GOVERNANCE_REQUIRED
        self.core.AUTONOMY_GOVERNANCE_REQUIRED = False
        try:
            with self.assertRaises(self.core.HTTPException) as blocked:
                self.core.recover_calibrated_route_run(route_run_id, request)
            self.assertEqual("ROUTE_RECOVERY_ATTESTATION_REQUIRED", blocked.exception.detail["code"])
            with self.core.command_history_lock, self.core.db.connection(self.core.COMMAND_HISTORY_DB) as connection:
                connection.execute("UPDATE robot_field_attestations SET attested_at_ms = ? WHERE robot_slug = ?", (now + 1, robot_slug))
            recovered = self.core.recover_calibrated_route_run(route_run_id, request)
        finally:
            self.core.AUTONOMY_GOVERNANCE_REQUIRED = original_governance
        self.assertEqual("AWAITING_SEGMENT_CONFIRMATION", recovered["state"])
        self.assertEqual("retry", recovered["recovery"]["action"])

    def test_l13_to_l20_governance_requires_a_short_lived_permit(self):
        route_id, robot_slug = "governed-ahead", "booky-governed"
        self.core.import_calibrated_route(self.core.CalibratedRouteDefinitionRequest(
            route_id=route_id, version="1.0.0", title="เส้นทางมีผู้ควบคุม",
            segments=[{"label": "ช่วงที่ 1", "command": {
                "text": "ขยับอย่างระมัดระวัง", "face": "CONFIDENT",
                "safety": {"base_motion_enabled": True, "collision_guard_enabled": True, "fall_guard_enabled": True,
                           "max_distance_m": 0.15, "max_speed": 1, "auto_stop_ms": 1500},
                "motion": {"x": 0.10, "y": 0, "theta": 0, "speed": 1},
            }}],
        ))
        self.core.certify_calibrated_route(route_id, self.core.RouteCertificationRequest(
            operator_name="safety officer", path_clearance_checked=True, segment_measurements_checked=True,
            emergency_stop_checked=True,
        ))
        authorization = self.core.issue_operator_authorization(self.core.OperatorAuthorizationRequest(
            operator_name="safety officer", role="safety_officer", scopes=["route_release", "operation_permit"],
        ))
        self.core.publish_route_release(route_id, self.core.RouteReleaseRequest(
            authorization_id=authorization["authorization_id"], state="ACTIVE", allowed_robot_slugs=[robot_slug],
        ))
        self.core.record_localization_attestation(robot_slug, self.core.LocalizationAttestationRequest(
            operator_name="operator", map_id="library-floor-1", map_version="1", starting_pose_checked=True,
            localization_drift_checked=True, fallback_stop_checked=True,
        ))
        self.core.record_safety_envelope(robot_slug, self.core.SafetyEnvelopeRequest(
            operator_name="operator", obstacle_stop_checked=True, exclusion_zone_checked=True, manual_takeover_checked=True,
        ))
        reservation = self.core.reserve_autonomy_zone(self.core.ZoneReservationRequest(
            zone_id="service-desk", robot_slug=robot_slug, route_id=route_id,
        ))
        self.core.record_fault_drill(robot_slug, self.core.FaultDrillRequest(
            operator_name="operator", emergency_stop_checked=True, lost_localization_stop_checked=True, obstacle_stop_checked=True,
        ))
        blocked = self.core.create_calibrated_route_run
        with self.assertRaises(self.core.HTTPException) as missing_permit:
            blocked(self.core.CalibratedRouteRunRequest(route_id=route_id, robot_slug=robot_slug, idempotency_key="governed-run"))
        self.assertEqual("AUTONOMY_PERMIT_REQUIRED", missing_permit.exception.detail["code"])
        permit = self.core.issue_operation_permit(self.core.OperationPermitRequest(
            route_id=route_id, robot_slug=robot_slug, zone_reservation_id=reservation["reservation_id"],
            authorization_id=authorization["authorization_id"],
        ))
        route_run = self.core.create_calibrated_route_run(self.core.CalibratedRouteRunRequest(
            route_id=route_id, robot_slug=robot_slug, idempotency_key="governed-run", operation_permit_id=permit["permit_id"],
        ))
        self.assertEqual("AWAITING_SEGMENT_CONFIRMATION", route_run["state"])
        self.assertEqual("READY", self.core.get_operation_permit(permit["permit_id"])["state"])
        preflight = self.core.autonomy_preflight(route_id, robot_slug, reservation["reservation_id"], authorization["authorization_id"], permit["permit_id"])
        self.assertTrue(preflight["permit_ready"])
        self.assertIn("ROBOT_FIELD_READINESS_REQUIRED", preflight["dispatch_blockers"])
        now = int(self.core.time.time() * 1000)
        self.core._remember_robot(f"zenbo/{robot_slug}/status/heartbeat", '''{
            "version_name":"1.8.9", "topic_prefix":"zenbo/booky-governed", "robot_api_ready":true,
            "safety_monitor_active":true, "safety_guard":{"collision_guard_enabled":true,"fall_guard_enabled":true,"base_motion_enabled":true,"max_distance_m":0.15,"max_speed":1,"auto_stop_ms":1500},
            "capabilities":["THAI_TTS","EXPRESSION","HEAD","WHEEL_LIGHTS","SAFETY_SONAR","SAFETY_DROP_LASER","CALIBRATED_ROUTE"]
        }''')
        with self.core.command_history_lock, self.core.db.connection(self.core.COMMAND_HISTORY_DB) as connection:
            connection.execute("INSERT INTO robot_field_attestations (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?)",
                               (robot_slug, now, "operator", '{"tts_checked":true,"vision_checked":true,"display_checked":true}'))
        published, original_motion, original_publish = [], self.core.AUTONOMOUS_MOTION_ENABLED, self.core.mqtt_client.publish
        self.core.AUTONOMOUS_MOTION_ENABLED, self.core.mqtt_client.publish = True, lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            dispatched = asyncio.run(self.core.confirm_next_calibrated_route_segment(route_run["route_run_id"]))
        finally:
            self.core.AUTONOMOUS_MOTION_ENABLED, self.core.mqtt_client.publish = original_motion, original_publish
        self.assertEqual("SEGMENT_DISPATCHED", dispatched["route_run"]["state"])
        self.core._record_scenario_client_event({"run_id": dispatched["route_run"]["active_scenario_run_id"], "state": "MOTION_COMPLETED"})
        completed = self.core.refresh_calibrated_route_run(route_run["route_run_id"])
        self.assertEqual("COMPLETED", completed["state"])
        self.assertEqual("RELEASED", self.core.get_zone_reservation(reservation["reservation_id"])["state"])
        revoked = self.core.revoke_operation_permit(permit["permit_id"], "test revoke")
        self.assertEqual("REVOKED", revoked["state"])
        released = self.core.release_zone_reservation(reservation["reservation_id"], "test complete")
        self.assertEqual("RELEASED", released["state"])

    def test_l13_governance_write_endpoint_requires_registry_token(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.core.app)
        payload = {"operator_name": "safety officer", "role": "safety_officer", "scopes": ["operation_permit"]}
        self.assertEqual(403, client.post("/api/v1/autonomy/authorizations", json=payload).status_code)
        response = client.post("/api/v1/autonomy/authorizations", json=payload,
                               headers={"X-Scenario-Registry-Token": "test-registry-token"})
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["authorization_id"])

    def test_registry_import_requires_a_supported_face_for_visual_contract(self):
        with self.assertRaises(Exception):
            self.core.ScenarioDefinitionRequest(
                scenario_id="missing-visual-contract", version="1.0.0", title="ไม่มีสีหน้า",
                description="ต้องไม่ผ่าน", command={"text": "สวัสดีครับ"},
            )

    def test_youtube_requires_a_single_playable_video_url(self):
        command = self.core.YouTubeCommand(url="https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual("https://youtu.be/dQw4w9WgXcQ", command.url)
        with self.assertRaises(Exception):
            self.core.YouTubeCommand(url="https://www.youtube.com/results?search_query=music")

    def test_n8n_playlist_registry_validates_https_video_and_returns_preview_without_dispatch(self):
        playlist = self.core.MusicPlaylistDefinitionRequest(
            playlist_id="happy-study",
            version="1.0.0",
            title="อ่านหนังสือเพลิน ๆ",
            mood="calm",
            tracks=[self.core.MusicTrack(title="เพลงตัวอย่าง", youtube={"url": "https://youtu.be/dQw4w9WgXcQ"})],
        )
        imported = self.core.import_music_playlist(playlist)
        self.assertEqual(1, imported["track_count"])
        preview = self.core.pick_music_preview("happy-study", "booky-1")
        self.assertEqual("NOT_SENT", preview["dispatch"])
        self.assertEqual("https://youtu.be/dQw4w9WgXcQ", preview["command"]["youtube"]["url"])
        from fastapi.testclient import TestClient
        client = TestClient(self.core.app)
        self.assertEqual(403, client.post("/api/v1/music-playlists", json=playlist.model_dump()).status_code)
        self.assertEqual(200, client.post("/api/v1/music-playlists", json=playlist.model_dump(), headers={"X-Scenario-Registry-Token": "test-registry-token"}).status_code)
        listed = client.get("/api/v1/music-playlists")
        self.assertEqual("happy-study", listed.json()["playlists"][0]["id"])

    def test_scheduled_music_dance_is_feature_gated_and_requires_an_approved_action(self):
        request = self.core.MusicPlaylistStartRequest(
            robot_slug="booky-1", dance_action_ids=[2], duration_seconds=45,
        )
        self.assertEqual([2], request.dance_action_ids)
        with self.assertRaises(Exception):
            self.core.MusicPlaylistStartRequest(robot_slug="booky-1", dance_action_ids=[999])

        from fastapi.testclient import TestClient
        original_enabled = self.core.MUSIC_DANCE_AUTOMATION_ENABLED
        self.core.MUSIC_DANCE_AUTOMATION_ENABLED = False
        try:
            response = TestClient(self.core.app).post(
                "/api/v1/music-playlists/happy-study/start", json=request.model_dump()
            )
        finally:
            self.core.MUSIC_DANCE_AUTOMATION_ENABLED = original_enabled
        self.assertEqual(409, response.status_code)
        self.assertEqual("MUSIC_DANCE_AUTOMATION_DISABLED", response.json()["detail"]["code"])

    def test_ota_manifest_is_opt_in_and_requires_https_sha256_pin(self):
        self.assertEqual("not_configured", self.core.apk_update_manifest()["status"])
        original = (self.core.APK_UPDATE_URL, self.core.APK_UPDATE_VERSION_CODE,
                    self.core.APK_UPDATE_VERSION_NAME, self.core.APK_UPDATE_SHA256)
        try:
            self.core.APK_UPDATE_URL = "https://libn.kku.ac.th/downloads/ZenboClient.apk"
            self.core.APK_UPDATE_VERSION_CODE = "18"
            self.core.APK_UPDATE_VERSION_NAME = "1.7.7-ota"
            self.core.APK_UPDATE_SHA256 = "a" * 64
            manifest = self.core.apk_update_manifest()
        finally:
            (self.core.APK_UPDATE_URL, self.core.APK_UPDATE_VERSION_CODE,
             self.core.APK_UPDATE_VERSION_NAME, self.core.APK_UPDATE_SHA256) = original
        self.assertEqual("ready", manifest["status"])
        self.assertEqual("USER_CONFIRMATION_REQUIRED", manifest["update"]["installation"])

    def test_command_history_paginates_and_keeps_robot_filter(self):
        for index in range(3):
            self.core.record_command_history(
                "pagination-bot", "test", "MQTT_PUBLISHED", {"text": f"history {index}"}
            )
        from fastapi.testclient import TestClient
        response = TestClient(self.core.app).get(
            "/api/v1/command-history?robot_slug=pagination-bot&page=2&page_size=2"
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(3, payload["total"])
        self.assertEqual(2, payload["page"])
        self.assertEqual(2, payload["total_pages"])
        self.assertFalse(payload["has_next"])
        self.assertTrue(payload["has_previous"])
        self.assertEqual(1, len(payload["items"]))
        self.assertEqual("pagination-bot", payload["items"][0]["robot_slug"])

    def test_device_mqtt_provisioning_returns_only_authorized_runtime_connection(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.core.app)
        original = (
            self.core.ZENBO_DEVICE_PROVISIONING_TOKEN, self.core.MQTT_USERNAME,
            self.core.MQTT_TOKEN, self.core.MQTT_CLIENT_HOST, self.core.MQTT_CLIENT_PORT,
            self.core.MQTT_CLIENT_TRANSPORT, self.core.ZENBO_DEVICE_ROBOT_SLUG,
            self.core.MQTT_AUTH_REQUIRED,
        )
        try:
            self.core.MQTT_AUTH_REQUIRED = True
            self.core.ZENBO_DEVICE_PROVISIONING_TOKEN = "device-secret"
            self.core.MQTT_USERNAME = "zenbo-client"
            self.core.MQTT_TOKEN = "broker-secret"
            self.core.MQTT_CLIENT_HOST = "mqtt.libn.kku.ac.th"
            self.core.MQTT_CLIENT_PORT = 8883
            self.core.MQTT_CLIENT_TRANSPORT = "ssl"
            self.core.ZENBO_DEVICE_ROBOT_SLUG = "booky-1"
            denied = client.post("/api/v1/device/mqtt-connection", json={"robot_slug": "booky-1"})
            self.assertEqual(403, denied.status_code)
            denied_slug = client.post(
                "/api/v1/device/mqtt-connection", json={"robot_slug": "other-robot"},
                headers={"X-Zenbo-Provisioning-Token": "device-secret"},
            )
            self.assertEqual(403, denied_slug.status_code)
            allowed = client.post(
                "/api/v1/device/mqtt-connection", json={"robot_slug": "booky-1"},
                headers={"X-Zenbo-Provisioning-Token": "device-secret"},
            )
        finally:
            (
                self.core.ZENBO_DEVICE_PROVISIONING_TOKEN, self.core.MQTT_USERNAME,
                self.core.MQTT_TOKEN, self.core.MQTT_CLIENT_HOST, self.core.MQTT_CLIENT_PORT,
                self.core.MQTT_CLIENT_TRANSPORT, self.core.ZENBO_DEVICE_ROBOT_SLUG,
                self.core.MQTT_AUTH_REQUIRED,
            ) = original
        self.assertEqual(200, allowed.status_code)
        self.assertEqual("no-store, max-age=0", allowed.headers["cache-control"])
        self.assertEqual("ssl", allowed.json()["transport"])
        self.assertEqual("zenbo/booky-1", allowed.json()["topic_prefix"])

    def test_safety_policy_defaults_to_unhindered_operator_drive(self):
        policy = self.core.SafetyModeCommand()
        self.assertTrue(policy.base_motion_enabled)
        self.assertFalse(policy.collision_guard_enabled)
        self.assertFalse(policy.fall_guard_enabled)
        self.assertEqual(7, policy.max_speed)

    def test_safety_policy_is_published_to_the_selected_robot(self):
        published = []
        original_publish = self.core.mqtt_client.publish
        self.core.mqtt_client.publish = lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            result = asyncio.run(self.core.set_robot_safety("booky-safe", self.core.SafetyModeCommand()))
        finally:
            self.core.mqtt_client.publish = original_publish
        self.assertEqual("safety_policy_sent", result["status"])
        self.assertEqual("zenbo/booky-safe/cmd/safety", published[0][0])
        self.assertEqual(2, published[0][2])

    def test_sensor_stop_is_retained_separately_from_latest_telemetry(self):
        self.core._remember_robot("zenbo/booky-sensors/status/safety", '{"state":"SENSOR_STOP","reason":"SONAR","meters":0.2}')
        self.core._remember_robot("zenbo/booky-sensors/status/safety", '{"state":"SENSOR_SAMPLE","sensor":"SONAR_MIN","meters":0.4}')
        with self.core.robot_registry_lock:
            robot = self.core.robot_registry["booky-sensors"]
        self.assertEqual("SENSOR_SAMPLE", robot["safety"]["data"]["state"])
        self.assertEqual("SENSOR_STOP", robot["last_safety_stop"]["data"]["state"])

    def test_rearming_safety_policy_clears_the_active_stop_banner(self):
        self.core._remember_robot("zenbo/booky-rearm/status/safety", '{"state":"SENSOR_STOP","reason":"SONAR","meters":0.2}')
        self.core._remember_robot("zenbo/booky-rearm/status/safety", '{"state":"POLICY_APPLIED"}')
        with self.core.robot_registry_lock:
            robot = self.core.robot_registry["booky-rearm"]
        self.assertNotIn("last_safety_stop", robot)
        self.assertEqual("POLICY_APPLIED", robot["safety"]["data"]["state"])

    def test_field_readiness_requires_client_reported_sdk_safety_and_capabilities(self):
        self.core._remember_robot("zenbo/booky-ready/status/heartbeat", '''{
            "version_name":"1.7.6-field-readiness", "topic_prefix":"zenbo/booky-ready",
            "robot_api_ready":true, "safety_monitor_active":true,
            "safety_guard":{"collision_guard_enabled":true,"fall_guard_enabled":true,"base_motion_enabled":false},
            "capabilities":["THAI_TTS","EXPRESSION","HEAD","WHEEL_LIGHTS"]
        }''')
        readiness = self.core.get_robot_field_readiness("booky-ready")
        self.assertEqual("READY", readiness["state"])
        self.assertFalse(readiness["blockers"])
        from fastapi.testclient import TestClient
        response = TestClient(self.core.app).get("/api/v1/robots/booky-ready/field-readiness")
        self.assertEqual(200, response.status_code)
        self.assertEqual("READY", response.json()["state"])

        self.core._remember_robot("zenbo/booky-legacy/status/heartbeat", '{"topic_prefix":"zenbo"}')
        legacy = self.core.get_robot_field_readiness("booky-legacy")
        self.assertEqual("NOT_READY", legacy["state"])
        self.assertIn("TOPIC_PREFIX_UNSAFE", [item["code"] for item in legacy["blockers"]])

    def test_confirmation_dispatches_run_id_and_client_telemetry_completes_run(self):
        request = self.core.ScenarioRunRequest(
            scenario_id="intro_booky",
            robot_slug="booky-2",
            idempotency_key="voice-session-8",
            source="n8n",
        )
        run = self.core.create_scenario_run_record(request)
        published = []
        original_publish = self.core.mqtt_client.publish
        self.core.mqtt_client.publish = lambda topic, payload, qos=0: published.append((topic, payload, qos))
        try:
            result = asyncio.run(self.core.confirm_scenario_run(run["run_id"]))
        finally:
            self.core.mqtt_client.publish = original_publish

        self.assertEqual("DISPATCHED", result["run"]["state"])
        self.assertIn(run["run_id"], published[0][1])
        self.core._record_scenario_client_event({"run_id": run["run_id"], "state": "CLIENT_RECEIVED"})
        self.core._record_scenario_client_event({"run_id": run["run_id"], "state": "SPEECH_COMPLETED"})
        self.assertEqual("SUCCEEDED", self.core.get_scenario_run_record(run["run_id"])["state"])

    def test_innotech_welcome_scenario_and_intelsphere_compiler(self):
        self.assertIn("innotech-judge-welcome-30", self.core.PRESENTATION_CATALOG)
        innotech = self.core.PRESENTATION_CATALOG["innotech-judge-welcome-30"]
        self.assertEqual(30, innotech["duration_seconds"])
        self.assertEqual("ready", innotech["availability"])
        self.assertIn("InnoTech Show & Share 2026", innotech["command"]["text"])
        self.assertEqual("PROUD", innotech["command"]["face"])
        self.assertEqual(2, innotech["command"]["action"]["action_id"])

        from fastapi.testclient import TestClient
        client = TestClient(self.core.app)

        # 1. Compile InnoTech Judge Welcome
        res = client.post("/api/v1/commands/compile", json={"command": "ต้อนรับกรรมการ InnoTech Show & Share 2026"})
        self.assertEqual(200, res.status_code)
        data = res.json()
        self.assertEqual("kku_intelsphere", data["compiler_source"])
        self.assertEqual("WELCOME_JUDGES", data["intent"])
        self.assertEqual("PROUD", data["compiled_payload"]["face"])
        self.assertEqual(2, data["compiled_payload"]["action"]["action_id"])

        # 2. Compile Dance & Twist
        res_dance = client.post("/api/v1/commands/compile", json={"command": "เต้นส่ายเอวให้ดูหน่อย"})
        self.assertEqual(200, res_dance.status_code)
        dance_data = res_dance.json()
        self.assertEqual("DANCE_MUSIC", dance_data["intent"])
        self.assertEqual(22, dance_data["compiled_payload"]["action"]["action_id"])
        self.assertEqual("SINGING", dance_data["compiled_payload"]["face"])

        # 3. Emergency Stop
        res_stop = client.post("/api/v1/commands/compile", json={"command": "หยุดเดี๋ยวนี้"})
        self.assertEqual(200, res_stop.status_code)
        self.assertTrue(res_stop.json()["compiled_payload"]["emergency"])


if __name__ == "__main__":
    unittest.main()
