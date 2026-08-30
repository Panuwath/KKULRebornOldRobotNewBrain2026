import os
import json
import re
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

app = FastAPI(title="Zenbo Natural Language & Voice Compiler", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KKU_INTELSPHERE_API_URL = os.getenv(
    "KKU_INTELSPHERE_API_URL", "https://gen.ai.kku.ac.th/api/v1/chat/completions"
)
KKU_API_KEY = os.getenv("KKU_API_KEY", "")
KKU_INTELSPHERE_MODEL = os.getenv("KKU_INTELSPHERE_MODEL", "gpt-5.6-luna")
CORE_API_URL = os.getenv("CORE_API_URL", "http://zenbo-core-api:5005")

SYSTEM_PROMPT = """You are the Zenbo Robot Compiler Engine. Your job is to compile natural language commands (in Thai or English) into structured JSON instructions for an ASUS Zenbo robot.

Strict Rules:
1. Always output ONLY valid JSON matching the schema below — no markdown, no explanation.
2. Calculate physical safety limits:
   - x, y (motion): max 2.0 meters per step
   - theta (motion): -180 to 180 degrees
   - yaw (head): -45 to 45 degrees
   - pitch (head): -15 to 55 degrees
   - speed: 1 to 5
3. Select appropriate RobotFace from: [HAPPY, DEFAULT, INTEREST, DOUBT, EXPECT, SHY, WORRIED, SHOCK, TIRED, SINGING, PROUD]
4. Select wheel_lights mode from: [breathing, blinking, charging, marquee, off]
5. Compose polite, friendly Thai spoken response in the "text" field.
6. Set "emergency": true only when the user asks to stop, halt, or cancel.
7. For a head shake, emit "head_sequence" with 3–4 safe yaw steps. For a YouTube URL, emit "youtube" only when the URL is a youtube.com or youtu.be HTTPS URL.
8. YouTube dance action IDs must be chosen only from [2, 3, 5, 11, 18, 22, 23, 44]. Never claim that a numeric action ID has a particular official dance name.

JSON Output Schema:
{
  "text": "ข้อความที่หุ่นยนต์จะพูดตอบกลับ",
  "voice": "female_sweet",
  "rate": "-10%",
  "pitch": "+2Hz",
  "face": "HAPPY",
  "motion": { "x": 0.0, "y": 0.0, "theta": 0.0, "speed": 2 },
  "head": { "yaw": 0.0, "pitch": 0.0, "speed": 2 },
  "head_sequence": [{ "yaw": -25.0, "pitch": 10.0, "speed": 2, "delay_ms": 450 }],
  "action": null,
  "wheel_lights": { "mode": "breathing", "color": "0x00D031", "brightness": 10 },
  "youtube": { "url": "https://www.youtube.com/watch?v=...", "dance_action_ids": [2, 3, 5, 11], "loop_dance": true, "duration_seconds": null },
  "emergency": false
}"""


class TextCompileRequest(BaseModel):
    command: str = Field(..., example="เซนโบ เดินหน้ามาหาหน่อย แล้วยิ้มหวานๆ แนะนำตัวด้วยนะ")
    auto_dispatch: bool = Field(default=True, description="ส่งต่อคำสั่งไปยังหุ่นยนต์ทันทีหรือไม่")
    robot_slug: Optional[str] = Field(default=None, description="Zenbo target; required for a device-specific dispatch")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "zenbo-compiler-service"}


async def call_intelsphere_api(text: str) -> Dict[str, Any]:
    """เรียก KKU IntelSphere API เพื่อแปลงภาษาธรรมชาติเป็นคำสั่ง Zenbo"""
    headers = {
        "Authorization": f"Bearer {KKU_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": KKU_INTELSPHERE_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            KKU_INTELSPHERE_API_URL, json=payload, headers=headers, timeout=30.0
        )
        if res.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"IntelSphere API returned {res.status_code}: {res.text[:200]}",
            )
        data = res.json()
        raw_content = data["choices"][0]["message"]["content"]
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[-1]
            if raw_content.endswith("```"):
                raw_content = raw_content[:-3]
        return json.loads(raw_content)


def normalize_compiled_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Discard malformed optional LLM fields before the preview crosses the API boundary."""
    if not isinstance(payload, dict):
        raise ValueError("Compiler response must be a JSON object")
    allowed = {
        "text", "voice_profile", "voice", "rate", "pitch", "face", "motion", "head",
        "head_sequence", "action", "wheel_lights", "emotional_action", "remote_control",
        "behavior", "vision", "youtube", "emergency",
    }
    normalized = {key: value for key, value in payload.items() if key in allowed}
    normalized["emergency"] = bool(normalized.get("emergency", False))
    youtube = normalized.get("youtube")
    if not isinstance(youtube, dict) or not isinstance(youtube.get("url"), str) or not youtube["url"].strip():
        normalized.pop("youtube", None)
    else:
        normalized["youtube"] = {
            "url": youtube["url"].strip(),
            "dance_action_ids": youtube.get("dance_action_ids") or [],
            "loop_dance": bool(youtube.get("loop_dance", False)),
            "duration_seconds": youtube.get("duration_seconds"),
        }
    if not isinstance(normalized.get("head_sequence"), list) or not normalized.get("head_sequence"):
        normalized.pop("head_sequence", None)
    return normalized


@app.post("/api/v1/compiler/text")
async def compile_text(req: TextCompileRequest):
    """คอมไพล์ภาษาธรรมชาติเป็นคำสั่งควบคุม Zenbo ผ่าน KKU IntelSphere"""
    try:
        compiler_source = "local_fallback"
        if KKU_API_KEY:
            try:
                compiled_json = await call_intelsphere_api(req.command)
                compiler_source = "kku_intelsphere"
            except Exception as e:
                print(f"[!] IntelSphere API failed, falling back to local parser: {e}")
                compiled_json = parse_natural_command(req.command)
        else:
            compiled_json = parse_natural_command(req.command)

        compiled_json = normalize_compiled_payload(compiled_json)

        dispatch_result = None
        if req.auto_dispatch:
            async with httpx.AsyncClient() as client:
                if compiled_json.get("emergency"):
                    stop_url = (f"{CORE_API_URL}/api/v1/robots/{req.robot_slug}/stop"
                                if req.robot_slug else f"{CORE_API_URL}/api/v1/robot/stop")
                    dispatch_res = await client.post(
                        stop_url, timeout=10.0
                    )
                else:
                    if req.robot_slug:
                        compiled_json["robot_slug"] = req.robot_slug
                    dispatch_res = await client.post(
                        f"{CORE_API_URL}/api/v1/robot/interact",
                        json=compiled_json,
                        timeout=10.0,
                    )
                dispatch_result = dispatch_res.json()

        return {
            "status": "compiled_successfully",
            "original_command": req.command,
            "compiled_payload": compiled_json,
            "compiler_source": compiler_source,
            "dispatch_result": dispatch_result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compiler Error: {str(e)}")


@app.post("/api/v1/compiler/voice")
async def compile_voice(
    audio: UploadFile = File(...),
    auto_dispatch: bool = Form(default=True),
):
    """รับไฟล์เสียง → แปลงเป็นข้อความด้วย ASR → คอมไพล์เป็นคำสั่ง Zenbo"""
    try:
        audio_bytes = await audio.read()

        transcript = await speech_to_text(audio_bytes, audio.filename)

        req = TextCompileRequest(command=transcript, auto_dispatch=False)
        result = await compile_text(req)

        if auto_dispatch and not result.get("compiled_payload", {}).get("emergency"):
            async with httpx.AsyncClient() as client:
                dispatch_res = await client.post(
                    f"{CORE_API_URL}/api/v1/robot/interact",
                    json=result["compiled_payload"],
                    timeout=10.0,
                )
                result["dispatch_result"] = dispatch_res.json()

        result["transcript"] = transcript
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice Compiler Error: {str(e)}")


async def speech_to_text(audio_bytes: bytes, filename: str) -> str:
    """แปลงเสียงพูดภาษาไทยเป็นข้อความ (ASR)"""
    if KKU_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {KKU_API_KEY}",
            }
            files = {"file": (filename, audio_bytes, "audio/wav")}
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://gen.ai.kku.ac.th/api/v1/speech-to-text",
                    files=files,
                    headers=headers,
                    timeout=30.0,
                )
                if res.status_code == 200:
                    return res.json().get("text", "")
        except Exception as e:
            print(f"[!] IntelSphere STT failed: {e}")

    return "สวัสดี"


def parse_natural_command(text: str) -> Dict[str, Any]:
    """กฎการสกัดและคอมไพล์คำสั่งภาษาไทย (Local Fallback Parser)"""
    t = text.strip()

    if any(k in t for k in ["หยุด", "อย่าขยับ", "ยกเลิก", "stop"]):
        return {
            "text": "รับทราบค่ะ  หยุดการทำงานทันทีแล้วค่าา  ",
            "voice": "female_sweet",
            "rate": "-10%",
            "pitch": "+2Hz",
            "face": "SHOCK",
            "emergency": True,
            "wheel_lights": {"mode": "blinking", "color": "0xFF0000", "brightness": 20},
        }

    motion = None
    if "เดินหน้า" in t or "มาหา" in t or "ตรงไป" in t:
        motion = {"x": 0.5, "y": 0.0, "theta": 0.0, "speed": 2}
    elif "ถอยหลัง" in t or "ถอย" in t:
        motion = {"x": -0.5, "y": 0.0, "theta": 0.0, "speed": 2}
    elif "เลี้ยวซ้าย" in t or "หันซ้าย" in t:
        motion = {"x": 0.0, "y": 0.0, "theta": -45.0, "speed": 2}
    elif "เลี้ยวขวา" in t or "หันขวา" in t:
        motion = {"x": 0.0, "y": 0.0, "theta": 45.0, "speed": 2}
    elif "หมุนตัว" in t or "หมุนรอบ" in t:
        motion = {"x": 0.0, "y": 0.0, "theta": 180.0, "speed": 2}

    head = None
    head_sequence = None
    if "ก้มหน้า" in t or "มองลง" in t:
        head = {"yaw": 0.0, "pitch": -10.0, "speed": 2}
    elif "เงยหน้า" in t or "มองบน" in t or "มองฟ้า" in t:
        head = {"yaw": 0.0, "pitch": 30.0, "speed": 2}
    if any(k in t for k in ["ส่ายหัว", "ส่ายหน้า"]):
        head_sequence = [
            {"yaw": -25.0, "pitch": 10.0, "speed": 2, "delay_ms": 450},
            {"yaw": 25.0, "pitch": 10.0, "speed": 2, "delay_ms": 450},
            {"yaw": -25.0, "pitch": 10.0, "speed": 2, "delay_ms": 450},
            {"yaw": 0.0, "pitch": 10.0, "speed": 2, "delay_ms": 0},
        ]

    face = "HAPPY"
    if any(k in t for k in ["สงสัย", "งง", "ถาม"]):
        face = "DOUBT"
    elif any(k in t for k in ["เขิน", "อาย"]):
        face = "SHY"
    elif any(k in t for k in ["ภูมิใจ", "เท่", "มั่นใจ"]):
        face = "PROUD"
    elif any(k in t for k in ["เหนื่อย", "พัก"]):
        face = "TIRED"
    elif any(k in t for k in ["เต้น", "เพลง"]):
        face = "SINGING"

    action = None
    if any(k in t for k in ["เต้น", "ร้องเพลง", "แดนซ์"]):
        action = {"action_id": 22, "stop": False}

    youtube = None
    youtube_match = re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s]+", t, re.IGNORECASE)
    if youtube_match:
        youtube = {
            "url": youtube_match.group(0).rstrip(".,!?)］】"),
            "dance_action_ids": [2, 3, 5, 11, 18, 22, 23, 44],
            "loop_dance": any(k in t for k in ["เต้น", "แดนซ์", "dance"]),
            "duration_seconds": None,
        }

    wheel_lights = {"mode": "breathing", "color": "0x00D031", "brightness": 10}
    if "ไฟสีฟ้า" in t or "สีฟ้า" in t:
        wheel_lights = {"mode": "breathing", "color": "0x007F7F", "brightness": 15}
    elif "ไฟสีแดง" in t or "สีแดง" in t:
        wheel_lights = {"mode": "blinking", "color": "0xFF0000", "brightness": 20}
    elif "ไฟสีส้ม" in t or "สีส้ม" in t:
        wheel_lights = {"mode": "charging", "color": "0xFF9000", "brightness": 15}

    response_text = f"รับทราบคำสั่งค่ะ  กำลังดำเนินการให้ทันทีนะค้าา  "
    if "แนะนำตัว" in t:
        response_text = "สวัสดีค่าา  หนูชื่อเซนโบ  ยินดีที่ได้รู้จักทุกคนนะค้าา  "
    elif "ต้อนรับ" in t:
        response_text = "สวัสดีค่ะ ยินดีต้อนรับทุกท่านนะคะ หนูเซนโบพร้อมดูแลทุกคนค่ะ"
    elif "เต้น" in t or "เพลง" in t:
        response_text = "มาสนุกกันเลยค่าา  หนูจะเต้นให้ดูนะค้าา  "

    result = {
        "text": response_text,
        "voice": "female_sweet",
        "rate": "-10%",
        "pitch": "+2Hz",
        "face": face,
        "motion": motion,
        "head": head,
        "head_sequence": head_sequence,
        "action": action,
        "wheel_lights": wheel_lights,
        "youtube": youtube,
        "emergency": False,
    }
    return result
