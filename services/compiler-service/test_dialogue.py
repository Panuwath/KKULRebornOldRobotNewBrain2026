"""Contract tests for deterministic wake-word and safety gates."""
import asyncio
import importlib.util
import os
import sys
import types
import unittest

# The local macOS interpreter does not have the service's multipart optional
# dependency.  Stub only the unused upload parser so this contract test can
# load FastAPI routes; Docker still installs python-multipart from requirements.
multipart = types.ModuleType("multipart")
multipart.__version__ = "0.0.18"
multipart_submodule = types.ModuleType("multipart.multipart")
multipart_submodule.parse_options_header = lambda value: value
sys.modules.setdefault("multipart", multipart)
sys.modules.setdefault("multipart.multipart", multipart_submodule)

SPEC = importlib.util.spec_from_file_location("zenbo_compiler", os.path.join(os.path.dirname(__file__), "compiler.py"))
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


class DialogueContractTest(unittest.TestCase):
    def interpret(self, text):
        return asyncio.run(compiler.interpret_dialogue(compiler.DialogueRequest(session_id="session-1234", text=text)))

    def test_wake_then_safe_command(self):
        wake = self.interpret("สวัสดี Booky")
        self.assertEqual("AWAITING_COMMAND", wake["state"])
        command = self.interpret("กล่าวต้อนรับผู้มาใช้บริการ")
        self.assertEqual("COMMAND_READY", command["state"])
        self.assertTrue(command["compiled_payload"]["text"])

    def test_bunny_is_a_wake_word_with_or_without_a_greeting(self):
        for phrase in ("บันนี่", "สวัสดีบันนี่", "สวัสดี บันนี่"):
            with self.subTest(phrase=phrase):
                result = self.interpret(phrase)
                self.assertEqual("AWAITING_COMMAND", result["state"])
                self.assertEqual("WAKE", result["intent"])

    def test_stop_has_priority_without_wake_word(self):
        result = self.interpret("zenbo หยุด")
        self.assertEqual("STOP_REQUESTED", result["state"])
        self.assertTrue(result["compiled_payload"]["emergency"])

    def test_follow_is_gated_after_wake_word(self):
        self.interpret("booky")
        result = self.interpret("ตามฉันมา")
        self.assertEqual("GATED", result["state"])
        self.assertEqual("FOLLOW_PERSON", result["intent"])

    def test_switching_robot_requires_a_fresh_wake_word(self):
        session_id = "robot-switch-1234"
        wake = asyncio.run(compiler.interpret_dialogue(compiler.DialogueRequest(
            session_id=session_id, text="สวัสดี booky", robot_slug="booky-1"
        )))
        self.assertEqual("AWAITING_COMMAND", wake["state"])
        switched = asyncio.run(compiler.interpret_dialogue(compiler.DialogueRequest(
            session_id=session_id, text="กล่าวต้อนรับ", robot_slug="bunny-1"
        )))
        self.assertEqual("WAKE_WORD_REQUIRED", switched["state"])
        self.assertEqual("SESSION_TARGET_CHANGED", switched["reason"])


if __name__ == "__main__":
    unittest.main()
