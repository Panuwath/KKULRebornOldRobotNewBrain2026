import os
import json
import httpx
import time
import sqlite3
from threading import Lock
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
import paho.mqtt.client as mqtt

app = FastAPI(title="Zenbo Core API Gateway & MQTT Bridge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def liff_api_alias(request, call_next):
    """Allow the public LIFF proxy to reserve its API namespace safely."""
    if request.url.path.startswith("/liff-api/"):
        request.scope["path"] = request.url.path[len("/liff-api"):]
    return await call_next(request)

LIFF_DIR = os.getenv("LIFF_DIR", "/app/liff-app")


class NoStoreStaticFiles(StaticFiles):
    """Keep LIFF WebView from serving an older controller after a deploy."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


if os.path.exists(LIFF_DIR):
    app.mount("/liff", NoStoreStaticFiles(directory=LIFF_DIR, html=True), name="liff")

@app.get("/")
async def root():
    index_file = os.path.join(LIFF_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "Zenbo Core API Gateway Online. Access LIFF at /liff"}

MQTT_HOST = os.getenv("MQTT_HOST", "mqtt-broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "zenbo_core_gateway")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://zenbo-tts-service:8000")
TTS_BINARY_PATH = os.getenv("TTS_BINARY_PATH", "/api/v1/tts/binary")
COMPILER_SERVICE_URL = os.getenv("COMPILER_SERVICE_URL", "http://zenbo-compiler-service:5006")
COMPILER_API_MODE = os.getenv("COMPILER_API_MODE", "legacy").strip().lower()
SERVER_PUBLIC_HOST = os.getenv("SERVER_PUBLIC_HOST", "http://localhost:8000")
COMMAND_HISTORY_DB = os.getenv("COMMAND_HISTORY_DB", "/app/data/command_history.sqlite3")
NAVIGATION_SERVICE_URL = os.getenv("NAVIGATION_SERVICE_URL", "http://10.101.118.149:8032")

# These identifiers are the stable voice-persona contract.  The Android client
# resolves each profile through Core's reachable Neural TTS proxy; rate/pitch
# create distinct child, young, and adult delivery while keeping one provider.
VOICE_PROFILES = {
    "female_child": {"label": "เด็กผู้หญิง สดใส", "provider": "neural", "voice": "female_sweet", "rate": "-8%", "pitch": "+10Hz"},
    "female_young": {"label": "ผู้หญิงวัยรุ่น เป็นมิตร", "provider": "neural", "voice": "female_sweet", "rate": "-6%", "pitch": "+4Hz"},
    "female_adult": {"label": "ผู้หญิงผู้ใหญ่ สุภาพ", "provider": "neural", "voice": "female_sweet", "rate": "-3%", "pitch": "+0Hz"},
    "male_child": {"label": "เด็กผู้ชาย ร่าเริง", "provider": "neural", "voice": "boy_cute", "rate": "-8%", "pitch": "+7Hz"},
    "male_young": {"label": "ผู้ชายวัยรุ่น เป็นมิตร", "provider": "neural", "voice": "male_natural", "rate": "-4%", "pitch": "+2Hz"},
    "male_adult": {"label": "ผู้ชายผู้ใหญ่ อบอุ่น", "provider": "neural", "voice": "male_natural", "rate": "-2%", "pitch": "+0Hz"},
}

# Present Mode is deliberately catalog-driven.  The browser may select a
# presentation and provide bounded text fields, but it cannot inject arbitrary
# motion/action payloads into a preset.  Presets marked gated are visible for
# planning, yet Core refuses to dispatch them until their device capability
# and safety gate are implemented and verified.
PRESENTATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "library-welcome-30": {"title": "ยินดีต้อนรับห้องสมุด 30 วินาที", "icon": "📚", "category": "ต้อนรับ", "duration_seconds": 30, "availability": "ready", "description": "Booky กล่าวต้อนรับสำนักหอสมุด มข.", "fields": [], "command": {"text": "สวัสดีครับ ผมบุ๊คกี้ ยินดีต้อนรับทุกท่านสู่สำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ ที่นี่มีพื้นที่อ่านหนังสือ ค้นคว้า และเรียนรู้อย่างสร้างสรรค์ หากต้องการความช่วยเหลือ เรียกผมได้เสมอนะครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "judge-greeting": {"title": "ทักทายกรรมการ", "icon": "🎓", "category": "พิธีการ", "duration_seconds": 18, "availability": "ready", "description": "กล่าวต้อนรับกรรมการอย่างสุภาพ", "fields": [{"name": "event_name", "label": "ชื่องาน", "default": "กิจกรรมวันนี้", "max_length": 80}], "command": {"text": "สวัสดีครับ คณะกรรมการผู้ทรงเกียรติทุกท่าน ยินดีต้อนรับสู่ {event_name} ครับ ผมบุ๊คกี้ พร้อมนำเสนอและอำนวยความสะดวกแก่ทุกท่านครับ", "voice_profile": "male_young", "face": "PROUD", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 12}, "head": {"yaw": 0, "pitch": 8, "speed": 1}}},
    "photo-invitation": {"title": "เชิญถ่ายภาพ", "icon": "📸", "category": "กิจกรรม", "duration_seconds": 12, "availability": "ready", "description": "เชิญทุกคนรวมตัว นับถอยหลัง และเปิดพรีวิวกล้องบน Zenbo", "fields": [], "camera_preview": {"vision_action": "detect_face", "display": "zenbo_screen"}, "command": {"text": "ขอเชิญทุกท่านมาถ่ายภาพร่วมกันนะครับ ยิ้มให้กล้องครับ สาม สอง หนึ่ง", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "marquee", "color": "#FF4FA3", "brightness": 16}, "vision": {"action": "detect_face", "interval_ms": 1000, "debug_preview": True}}},
    "photo-pose": {"title": "โพสท่าถ่ายภาพ", "icon": "😊", "category": "กิจกรรม", "duration_seconds": 6, "availability": "ready", "description": "ยิ้มและอยู่กับที่สำหรับถ่ายภาพ", "fields": [], "command": {"text": "พร้อมถ่ายภาพครับ", "voice_profile": "male_child", "face": "HAPPY", "head": {"yaw": 0, "pitch": 5, "speed": 1}, "wheel_lights": {"mode": "static", "color": "#FF4FA3", "brightness": 12}}},
    "self-introduction": {"title": "แนะนำตัว Booky", "icon": "🤖", "category": "ต้อนรับ", "duration_seconds": 20, "availability": "ready", "description": "แนะนำบทบาทและความสามารถของหุ่นยนต์", "fields": [{"name": "robot_name", "label": "ชื่อหุ่นยนต์", "default": "บุ๊คกี้", "max_length": 40}], "command": {"text": "สวัสดีครับ ผม{robot_name} หุ่นยนต์ผู้ช่วยของสำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ ผมช่วยทักทาย แนะนำเส้นทาง สื่อสาร และสร้างรอยยิ้มให้ทุกคนได้ครับ", "voice_profile": "male_child", "face": "CONFIDENT", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "library-orientation": {"title": "แนะนำบริการห้องสมุด", "icon": "🧭", "category": "นำชม", "duration_seconds": 25, "availability": "ready", "description": "แนะนำพื้นที่และบริการหลัก", "fields": [], "command": {"text": "สำนักหอสมุดมีบริการค้นหนังสือ ยืมคืน พื้นที่อ่านหนังสือ และพื้นที่เรียนรู้ร่วมกันครับ หากต้องการไปยังจุดใด เลือกเมนูนำทางบนหน้าควบคุม แล้วผมจะแสดงแผนที่และพูดคำแนะนำให้ครับ", "voice_profile": "male_young", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 12}}},
    "route-guide": {"title": "นำชมด้วยแผนที่", "icon": "🗺️", "category": "นำชม", "duration_seconds": 30, "availability": "ready", "description": "แสดงแผนที่และพูดเส้นทาง โดยไม่สั่งเดินอัตโนมัติ", "fields": [{"name": "from_location", "label": "จาก", "default": "1102", "max_length": 80}, {"name": "to", "label": "ไป", "default": "1401", "max_length": 80}], "command": {"face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 12}}, "route_required": True},
    "route-announcement": {"title": "ประกาศจุดบริการ", "icon": "📍", "category": "นำชม", "duration_seconds": 12, "availability": "ready", "description": "บอกจุดหมายโดยไม่เคลื่อนที่", "fields": [{"name": "destination", "label": "จุดหมาย", "default": "เคาน์เตอร์บริการ", "max_length": 80}], "command": {"text": "หากต้องการไปยัง {destination} ผมยินดีแสดงเส้นทางบนแผนที่ให้ครับ", "voice_profile": "male_young", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 10}}},
    "new-member-welcome": {"title": "ต้อนรับสมาชิกใหม่", "icon": "🌱", "category": "ต้อนรับ", "duration_seconds": 14, "availability": "ready", "description": "ต้อนรับผู้ใช้บริการใหม่", "fields": [], "command": {"text": "ยินดีต้อนรับสมาชิกใหม่ครับ ขอให้ทุกท่านสนุกกับการเรียนรู้ และใช้บริการสำนักหอสมุดได้อย่างเต็มที่นะครับ", "voice_profile": "male_child", "face": "PLEASED", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "ask-me": {"title": "โหมดสื่อสาร", "icon": "💬", "category": "สื่อสาร", "duration_seconds": 0, "availability": "gated", "description": "ต้องมี speech-to-text และ dialog state บนหุ่นก่อน", "fields": [], "gate_reason": "ยังไม่มี dialog runner ที่ยืนยันการฟัง/ตอบเสียงบน Zenbo"},
    "feedback-invitation": {"title": "เชิญให้ข้อเสนอแนะ", "icon": "📝", "category": "สื่อสาร", "duration_seconds": 14, "availability": "ready", "description": "เชิญผู้ใช้ส่งความคิดเห็น", "fields": [], "command": {"text": "ความคิดเห็นของทุกท่านมีความหมายมากครับ หากมีข้อเสนอแนะ โปรดแจ้งเจ้าหน้าที่หรือส่งผ่านแบบประเมิน ขอบคุณครับ", "voice_profile": "male_young", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#FFC107", "brightness": 10}}},
    "story-time": {"title": "เล่านิทาน", "icon": "📖", "category": "เด็กและการเรียนรู้", "duration_seconds": 90, "availability": "gated", "description": "ต้องมี runner แบ่งตอนและหยุดได้ทันที", "fields": [], "gate_reason": "TTS ยาวและสีหน้าหลายช่วงต้องรันแบบเรียงคิว"},
    "quiz-host": {"title": "พิธีกรเกมตอบคำถาม", "icon": "❓", "category": "กิจกรรม", "duration_seconds": 0, "availability": "gated", "description": "ต้องมีรอ operator เฉลยและสถานะรอบเกม", "fields": [], "gate_reason": "ต้องมี stateful quiz runner"},
    "event-opening": {"title": "กล่าวเปิดงาน", "icon": "🎉", "category": "พิธีการ", "duration_seconds": 18, "availability": "ready", "description": "กล่าวเปิดงานแบบปรับชื่องาน", "fields": [{"name": "event_name", "label": "ชื่องาน", "default": "กิจกรรมวันนี้", "max_length": 80}], "command": {"text": "ขณะนี้ได้เวลาเริ่ม {event_name} แล้วครับ ขอให้ทุกท่านได้รับความรู้ ความสุข และแรงบันดาลใจตลอดกิจกรรมครับ", "voice_profile": "male_young", "face": "PROUD", "wheel_lights": {"mode": "marquee", "color": "#FFC107", "brightness": 16}}},
    "celebration": {"title": "แสดงความยินดี", "icon": "✨", "category": "บันเทิง", "duration_seconds": 10, "availability": "gated", "description": "ไฟและ canned action ต้องสอบเทียบกับ Zenbo เครื่องจริง", "fields": [], "gate_reason": "ยังไม่ยืนยันความหมายของ action ID และ callback บนเครื่องจริง"},
    "dance-show": {"title": "เต้นโชว์", "icon": "💃", "category": "บันเทิง", "duration_seconds": 8, "availability": "ready", "description": "แสดงท่าเต้นที่ยืนยันว่าใช้งานได้ โดยไม่พึ่ง YouTube", "fields": [], "command": {"text": "เต้นให้ชมกันนะครับ", "voice_profile": "male_child", "face": "SINGING", "action": {"action_id": 2}, "wheel_lights": {"mode": "marquee", "color": "#FF4FA3", "brightness": 16}}},
    "youtube-play": {"title": "เปิดเพลงจาก YouTube", "icon": "▶️", "category": "บันเทิง", "duration_seconds": 0, "availability": "ready", "description": "เปิดเพลงจากลิงก์ YouTube โดยไม่สั่งเต้น", "fields": [{"name": "youtube_url", "label": "ลิงก์ YouTube", "placeholder": "https://www.youtube.com/watch?v=...", "input_type": "url", "default": "", "max_length": 2048}], "command": {"youtube": {"url": "{youtube_url}", "dance_action_ids": [], "loop_dance": False}}},
    "music-dance": {"title": "เพลงจาก YouTube และเต้น", "icon": "🎵", "category": "บันเทิง", "duration_seconds": 0, "availability": "gated", "description": "รอทดสอบ player telemetry เพื่อหยุดเต้นเมื่อเพลงจบ", "fields": [], "gate_reason": "ท่าเต้นใช้ได้แล้ว; ยังต้องยืนยัน YouTube playback และสถานะเพลงจบก่อนเปิดโหมดรวม"},
    "children-greeting": {"title": "ทักทายเด็ก", "icon": "🧒", "category": "เด็กและการเรียนรู้", "duration_seconds": 12, "availability": "ready", "description": "คำทักทายสั้น สนุก และเป็นมิตร", "fields": [], "command": {"text": "สวัสดีครับน้อง ๆ ทุกคน ผมบุ๊คกี้ยินดีที่ได้เจอครับ วันนี้เรามาเรียนรู้และสนุกไปด้วยกันนะครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "rainbow", "color": "#00D031", "brightness": 14}}},
    "accessibility-help": {"title": "ช่วยเหลือผู้ใช้", "icon": "🤝", "category": "สื่อสาร", "duration_seconds": 16, "availability": "ready", "description": "พูดช้าและชัด พร้อมเชิญเรียกเจ้าหน้าที่", "fields": [], "command": {"text": "สวัสดีครับ หากต้องการความช่วยเหลือ กรุณาบอกผมได้เลยนะครับ ผมจะแนะนำบริการเบื้องต้น และสามารถช่วยเรียกเจ้าหน้าที่ให้ได้ครับ", "voice_profile": "male_adult", "face": "PLEASED", "wheel_lights": {"mode": "breath", "color": "#00AEEF", "brightness": 10}}},
    "staff-call": {"title": "เรียกเจ้าหน้าที่", "icon": "🔔", "category": "สื่อสาร", "duration_seconds": 10, "availability": "ready", "description": "แจ้งคำขอในเสียง; ยังไม่ส่ง LINE/โทรศัพท์", "fields": [{"name": "area", "label": "พื้นที่", "default": "จุดบริการ", "max_length": 80}], "command": {"text": "ขอความช่วยเหลือจากเจ้าหน้าที่บริเวณ {area} ครับ ขอบคุณครับ", "voice_profile": "male_adult", "face": "SERIOUS", "wheel_lights": {"mode": "blinking", "color": "#FFC107", "brightness": 16}}},
    "checkpoint-mark": {"title": "Mark ฐานกิจกรรม", "icon": "🏷️", "category": "ฐานกิจกรรม", "duration_seconds": 0, "availability": "gated", "description": "ต้องมีฐานข้อมูล virtual checkpoint ก่อน", "fields": [], "gate_reason": "ยังไม่มี persistence สำหรับ checkpoint/operator"},
    "checkpoint-arrival": {"title": "ถึงฐานกิจกรรม", "icon": "🚩", "category": "ฐานกิจกรรม", "duration_seconds": 0, "availability": "gated", "description": "ต้องอ่าน virtual checkpoint ที่บันทึกได้ก่อน", "fields": [], "gate_reason": "ยังไม่มี checkpoint service"},
    "standby": {"title": "โหมดพักรอ", "icon": "🌙", "category": "ระบบ", "duration_seconds": 6, "availability": "ready", "description": "เข้าสู่โหมดพร้อมรอรับคำสั่ง", "fields": [], "command": {"text": "บุ๊คกี้พร้อมรอรับคำสั่งครับ", "voice_profile": "male_child", "face": "DEFAULT_STILL", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 6}}},
}

# MQTT Setup
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
robot_registry: Dict[str, Dict[str, Any]] = {}
robot_registry_lock = Lock()
command_history_lock = Lock()


def init_command_history() -> None:
    os.makedirs(os.path.dirname(COMMAND_HISTORY_DB), exist_ok=True)
    with sqlite3.connect(COMMAND_HISTORY_DB) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS command_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER NOT NULL,
                robot_slug TEXT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                accepted_latency_ms INTEGER,
                payload_json TEXT NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS command_history_created_idx ON command_history(created_at_ms DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS command_history_robot_idx ON command_history(robot_slug, created_at_ms DESC)")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(command_history)")}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE command_history ADD COLUMN user_id TEXT")
        if "display_name" not in columns:
            connection.execute("ALTER TABLE command_history ADD COLUMN display_name TEXT")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS user_robot_binding (
                user_id TEXT NOT NULL,
                robot_slug TEXT NOT NULL,
                display_name TEXT,
                permission TEXT NOT NULL DEFAULT 'operator',
                created_at_ms INTEGER NOT NULL,
                PRIMARY KEY (user_id, robot_slug)
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS user_robot_binding_user_idx ON user_robot_binding(user_id)")


def record_command_history(robot_slug: Optional[str], source: Optional[str], status: str,
                           payload: Dict[str, Any], accepted_latency_ms: Optional[int] = None,
                           user_id: Optional[str] = None, display_name: Optional[str] = None) -> int:
    """Persist accepted LIFF dispatches; this is an audit of gateway acceptance, not robot completion."""
    with command_history_lock, sqlite3.connect(COMMAND_HISTORY_DB) as connection:
        cursor = connection.execute(
            """INSERT INTO command_history
               (created_at_ms, robot_slug, source, status, accepted_latency_ms, payload_json, user_id, display_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(time.time() * 1000), robot_slug, (source or "liff").strip()[:40], status,
             accepted_latency_ms, json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
             (user_id or "").strip()[:64] or None, (display_name or "").strip()[:128] or None),
        )
        return int(cursor.lastrowid)


def _remember_robot(topic: str, payload: str) -> None:
    """Keep the latest retained/heartbeat status for each robot prefix."""
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "zenbo" or parts[-2] != "status":
        return
    slug = "/".join(parts[1:-2])
    if not slug:
        return
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {"raw": payload}
    with robot_registry_lock:
        existing = robot_registry.get(slug, {})
        robot = {
            **existing,
            "robot_slug": slug,
            "topic": topic,
            "last_seen": time.time(),
        }
        event_kind = parts[-1]
        if event_kind == "heartbeat":
            robot.update(data)
        else:
            robot["last_event"] = {
                "kind": event_kind,
                "received_at_ms": int(time.time() * 1000),
                "data": data,
            }
        robot_registry[slug] = robot


def on_mqtt_message(client, userdata, message):
    _remember_robot(message.topic, message.payload.decode("utf-8", errors="replace"))

@app.on_event("startup")
def startup_event():
    init_command_history()
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.subscribe("zenbo/+/status/#", qos=1)
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.loop_start()
        print(f"[*] Connected to MQTT Broker at {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        print(f"[!] MQTT connection error: {e}")

@app.on_event("shutdown")
def shutdown_event():
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

class MotionCommand(BaseModel):
    x: float = Field(default=0.0, description="Forward/backward in meters")
    y: float = Field(default=0.0, description="Left/right in meters")
    theta: float = Field(default=0.0, description="Rotation angle in degrees")
    speed: int = Field(default=2, description="Speed level 1-5")

class HeadCommand(BaseModel):
    yaw: float = Field(default=0.0, description="Yaw angle in degrees (-45 to 45)")
    pitch: float = Field(default=0.0, description="Pitch angle in degrees (-15 to 55)")
    speed: int = Field(default=2, description="Speed level 1-5")

class HeadSequenceStep(HeadCommand):
    delay_ms: int = Field(default=0, ge=0, le=10000)

class YouTubeCommand(BaseModel):
    url: str = Field(..., min_length=12, max_length=2048)
    dance_action_ids: List[int] = Field(default_factory=list)
    loop_dance: bool = False
    duration_seconds: Optional[int] = Field(default=None, ge=1, le=3600)

    @field_validator("url")
    @classmethod
    def validate_youtube_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("https://"):
            raise ValueError("YouTube URL must use HTTPS")
        host = normalized.split("/", 3)[2].lower()
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
            raise ValueError("Only youtube.com or youtu.be URLs are supported")
        return normalized

    @field_validator("dance_action_ids")
    @classmethod
    def validate_dance_actions(cls, values: List[int]) -> List[int]:
        allowed = {2, 3, 5, 11, 18, 22, 23, 44}
        if any(value not in allowed for value in values):
            raise ValueError("Unsupported dance action ID")
        return values

class NavigationCommand(BaseModel):
    display_url: str = Field(..., min_length=12, max_length=2048)
    speech_text: str = Field(..., min_length=1, max_length=2000)
    step_speeches: List[str] = Field(default_factory=list, max_length=30)

    @field_validator("display_url")
    @classmethod
    def validate_display_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("http://10.101.118.149:8032/"):
            raise ValueError("Navigation display URL is not trusted")
        return normalized

class CannedActionCommand(BaseModel):
    action_id: int = Field(..., example=22)
    stop: bool = Field(default=False)

class WheelLightsCommand(BaseModel):
    mode: str = Field(default="breathing", example="breathing")
    color: str = Field(default="0x00D031", example="0x00D031")
    brightness: int = Field(default=10, example=10)
    side: str = Field(default="both", example="both")
    direction: str = Field(default="forward", example="forward")
    speed: str = Field(default="DEFAULT", example="DEFAULT")

class FaceStep(BaseModel):
    face: str
    duration: float = Field(default=10, ge=0)

class EmotionalActionCommand(BaseModel):
    action_id: int
    faces: List[FaceStep]
    speed: Optional[float] = None

class RemoteControlCommand(BaseModel):
    body: Optional[str] = None
    head: Optional[str] = None

class BehaviorCommand(BaseModel):
    action: str
    enabled: bool = True
    track: bool = True
    distance: Optional[float] = Field(default=None, gt=0)

class VisionCommand(BaseModel):
    action: str
    interval_ms: int = Field(default=1000, ge=100, le=10000)
    track_id: Optional[int] = None
    debug_preview: bool = False

class InteractCommand(BaseModel):
    text: Optional[str] = Field(default=None, example="สวัสดีครับ  ผมพร้อมให้บริการแล้วครับผมม  ")
    voice_profile: Optional[str] = Field(default=None, example="female_young")
    voice: Optional[str] = Field(default="female_sweet", example="female_sweet")
    rate: Optional[str] = Field(default="-10%", example="-10%")
    pitch: Optional[str] = Field(default="+2Hz", example="+2Hz")
    face: Optional[str] = Field(default="HAPPY", example="HAPPY")
    motion: Optional[MotionCommand] = None
    head: Optional[HeadCommand] = None
    head_sequence: Optional[List[HeadSequenceStep]] = None
    action: Optional[CannedActionCommand] = None
    wheel_lights: Optional[WheelLightsCommand] = None
    emotional_action: Optional[EmotionalActionCommand] = None
    remote_control: Optional[RemoteControlCommand] = None
    behavior: Optional[BehaviorCommand] = None
    vision: Optional[VisionCommand] = None
    youtube: Optional[YouTubeCommand] = None
    navigation: Optional[NavigationCommand] = None
    robot_slug: Optional[str] = Field(default=None, description="Target robot slug, e.g. zenbo1")
    source: Optional[str] = Field(default="liff", max_length=40, description="LIFF surface that dispatched this command")
    user_id: Optional[str] = Field(default=None, max_length=64, description="LINE userId of the dispatcher")
    display_name: Optional[str] = Field(default=None, max_length=128, description="LINE display name of the dispatcher")


class PresentationRequest(BaseModel):
    preset_id: str = Field(min_length=2, max_length=80)
    robot_slug: str = Field(min_length=1, max_length=120)
    variables: Dict[str, str] = Field(default_factory=dict)

    @field_validator("preset_id")
    @classmethod
    def known_preset_id(cls, value: str) -> str:
        preset_id = value.strip()
        if preset_id not in PRESENTATION_CATALOG:
            raise ValueError("Unknown presentation preset")
        return preset_id

class NeuralTtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice: str = Field(default="female_sweet")
    rate: str = Field(default="-8%")
    pitch: str = Field(default="+0Hz")

class CommandCompileRequest(BaseModel):
    command: str = Field(min_length=1, max_length=1000)
    robot_slug: Optional[str] = Field(default=None)


class UserRobotBindingRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    robot_slug: str = Field(min_length=1, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=128)
    permission: str = Field(default="operator", pattern="^(operator|admin|viewer)$")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "zenbo-core-api"}


@app.post("/api/v1/commands/compile")
async def compile_command(req: CommandCompileRequest):
    """Compile natural language for preview only; dispatch stays an explicit client action."""
    try:
        async with httpx.AsyncClient() as client:
            if COMPILER_API_MODE == "shared_v1":
                response = await client.post(
                    f"{COMPILER_SERVICE_URL}/v1/compile",
                    json={"text": req.command, "send": False, "source": "liff_preview"},
                    timeout=55.0,
                )
            else:
                response = await client.post(
                    f"{COMPILER_SERVICE_URL}/api/v1/compiler/text",
                    json={"command": req.command, "robot_slug": req.robot_slug, "auto_dispatch": False},
                    timeout=35.0,
                )
        data = response.json()
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=data.get("detail", "Compiler request failed"))
        if COMPILER_API_MODE == "shared_v1":
            action = str(data.get("command", {}).get("action", "")).strip().lower()
            text = str(data.get("command", {}).get("text") or req.command).strip()
            mapped = {
                "audio": {"text": text},
                "speak": {"text": text},
                "say": {"text": text},
                "nod": {"head_sequence": [{"yaw": 0, "pitch": 18, "speed": 2, "delay_ms": 0}, {"yaw": 0, "pitch": 0, "speed": 2, "delay_ms": 650}]},
                "shake_head": {"head_sequence": [{"yaw": -28, "pitch": 8, "speed": 2, "delay_ms": 0}, {"yaw": 28, "pitch": 8, "speed": 2, "delay_ms": 500}, {"yaw": 0, "pitch": 8, "speed": 2, "delay_ms": 500}]},
                "dance": {"action": {"action_id": 2}},
                "stop": {"emergency": True},
            }
            if action not in mapped:
                raise HTTPException(status_code=422, detail=f"Compiler action '{action or 'unknown'}' needs an explicit control before it can be sent")
            return {
                "compiled_payload": mapped[action],
                "compiler_source": "shared_v1",
                "compiler_action": action,
            }
        return data
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Compiler service is unavailable") from exc


@app.post("/api/v1/tts/neural/binary")
async def proxy_neural_tts(req: NeuralTtsRequest):
    """Serve Neural TTS bytes to Zenbo clients through their reachable Core API."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{TTS_SERVICE_URL}{TTS_BINARY_PATH}",
                # Thai TTS v1.3 accepts voice/age/speed.  The previous
                # neural-provider rate/pitch fields cause a 422 there, so
                # never forward provider-specific fields across this bridge.
                json={"text": req.text, "voice": req.voice},
                timeout=30.0,
            )
        if res.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Neural TTS service rejected the request ({res.status_code}): {res.text[:200]}",
            )
        return Response(
            content=res.content,
            media_type=res.headers.get("content-type", "audio/mpeg"),
            headers={"Cache-Control": "no-store"},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Neural TTS service is unavailable") from exc


@app.get("/api/v1/voice-profiles")
async def list_voice_profiles():
    """List stable voice-persona IDs understood by current Zenbo clients."""
    return {"profiles": [
        {"id": profile_id, **profile}
        for profile_id, profile in VOICE_PROFILES.items()
    ]}


def presentation_public_metadata(preset_id: str, preset: Dict[str, Any]) -> Dict[str, Any]:
    """Keep executable command templates server-side; LIFF receives catalog metadata only."""
    return {
        "id": preset_id,
        "title": preset["title"],
        "icon": preset["icon"],
        "category": preset["category"],
        "duration_seconds": preset["duration_seconds"],
        "availability": preset["availability"],
        "description": preset["description"],
        "fields": preset.get("fields", []),
        "gate_reason": preset.get("gate_reason"),
        "route_required": bool(preset.get("route_required")),
        "camera_preview": preset.get("camera_preview"),
    }


def _presentation_variables(preset: Dict[str, Any], supplied: Dict[str, str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for field in preset.get("fields", []):
        name = field["name"]
        raw = supplied.get(name, field.get("default", ""))
        if not isinstance(raw, str):
            raise HTTPException(status_code=422, detail={"code": "INVALID_PRESENTATION_VARIABLE", "field": name})
        value = " ".join(raw.split())
        if not value or len(value) > int(field.get("max_length", 80)):
            raise HTTPException(status_code=422, detail={"code": "INVALID_PRESENTATION_VARIABLE", "field": name})
        values[name] = value
    return values


def _interpolate_presentation_template(value: Any, variables: Dict[str, str]) -> Any:
    """Interpolate only the server-owned presentation template, recursively."""
    if isinstance(value, str):
        try:
            return value.format(**variables)
        except KeyError as error:
            raise HTTPException(status_code=422, detail={"code": "MISSING_PRESENTATION_VARIABLE", "field": str(error)})
    if isinstance(value, list):
        return [_interpolate_presentation_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _interpolate_presentation_template(item, variables) for key, item in value.items()}
    return value


async def build_presentation_command(req: PresentationRequest) -> Dict[str, Any]:
    preset = PRESENTATION_CATALOG[req.preset_id]
    if preset["availability"] != "ready":
        raise HTTPException(status_code=409, detail={
            "code": "PRESENTATION_GATED",
            "message": preset.get("gate_reason", "This presentation is not yet available"),
        })
    variables = _presentation_variables(preset, req.variables)
    command = _interpolate_presentation_template(
        json.loads(json.dumps(preset.get("command", {}), ensure_ascii=False)), variables
    )
    if isinstance(command.get("youtube"), dict):
        try:
            command["youtube"] = YouTubeCommand(**command["youtube"]).model_dump()
        except ValidationError as error:
            raise HTTPException(status_code=422, detail={"code": "INVALID_YOUTUBE_URL", "message": str(error)})
    if preset.get("route_required"):
        route_response = await get_navigation_route(variables["from_location"], variables["to"])
        route = route_response["route"]
        command.update({
            "text": route["speech_text"],
            "voice_profile": "male_young",
            "navigation": {
                "display_url": route["display_url"],
                "speech_text": route["speech_text"],
                "step_speeches": route["step_speeches"],
            },
        })
    command.update({"robot_slug": req.robot_slug, "source": "liff_present"})
    return command


@app.get("/api/v1/presentations")
async def list_presentations():
    return {"presets": [
        presentation_public_metadata(preset_id, preset)
        for preset_id, preset in PRESENTATION_CATALOG.items()
    ]}


@app.post("/api/v1/presentations/preview")
async def preview_presentation(req: PresentationRequest):
    """Build a safe, server-owned preview without publishing it to MQTT."""
    command = await build_presentation_command(req)
    return {"preset": presentation_public_metadata(req.preset_id, PRESENTATION_CATALOG[req.preset_id]), "command": command}


@app.post("/api/v1/presentations/start")
async def start_presentation(req: PresentationRequest):
    """Dispatch a ready preset through the existing audited interaction path."""
    command = await build_presentation_command(req)
    result = await robot_interact(InteractCommand(**command))
    return {"preset_id": req.preset_id, **result}


@app.get("/api/v1/command-history")
async def command_history(robot_slug: Optional[str] = None, limit: int = 50):
    """Return bounded gateway dispatch history. It does not claim physical completion."""
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    query = "SELECT id, created_at_ms, robot_slug, source, status, accepted_latency_ms, payload_json, user_id, display_name FROM command_history"
    params: List[Any] = []
    if robot_slug:
        query += " WHERE robot_slug = ?"
        params.append(robot_slug)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with command_history_lock, sqlite3.connect(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute(query, params).fetchall()
    return {"items": [{
        "id": row[0], "created_at_ms": row[1], "robot_slug": row[2], "source": row[3],
        "status": row[4], "accepted_latency_ms": row[5], "payload": json.loads(row[6]),
        "user_id": row[7], "display_name": row[8],
    } for row in rows]}


@app.get("/api/v1/robots")
async def list_robots():
    """Return online Zenbo clients discovered from MQTT heartbeats."""
    now = time.time()
    with robot_registry_lock:
        robots = [dict(robot) for robot in robot_registry.values()
                  if now - robot.get("last_seen", 0) <= 90]
    for robot in robots:
        robot["age_seconds"] = round(now - robot.get("last_seen", now))
        robot.pop("last_seen", None)
    robots.sort(key=lambda robot: robot["robot_slug"])
    return {"robots": robots, "count": len(robots)}

@app.get("/api/v1/navigation/route")
async def get_navigation_route(from_location: str, to: str):
    """Proxy the trusted campus route service; this endpoint never drives the robot."""
    from_location, to = from_location.strip(), to.strip()
    if not from_location or not to or len(from_location) > 120 or len(to) > 120:
        raise HTTPException(status_code=422, detail={"code": "INVALID_LOCATION", "message": "from_location and to are required"})
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{NAVIGATION_SERVICE_URL}/api/zenbo/navigate",
                params={"from": from_location, "to": to}, timeout=10.0,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_UNAVAILABLE", "message": str(error)})
    if response.status_code != 200 or not data.get("success") or not isinstance(data.get("data"), dict):
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_FAILED", "message": "Navigation service did not return a route"})
    route = data["data"]
    display_url = route.get("zenbo_display_url")
    speech_text = route.get("speech_text")
    steps = route.get("step_speeches", [])
    if not isinstance(display_url, str) or not display_url.startswith(f"{NAVIGATION_SERVICE_URL}/") or not isinstance(speech_text, str) or not speech_text.strip() or not isinstance(steps, list):
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_INVALID_RESPONSE", "message": "Navigation response is incomplete"})
    return {"route": {"display_url": display_url, "speech_text": speech_text, "step_speeches": [str(step)[:500] for step in steps[:30]], "distance_meters": route.get("total_distance_meters"), "estimated_minutes": route.get("estimated_minutes"), "step_count": route.get("step_count"), "start": route.get("start"), "destination": route.get("destination")}}

@app.get("/api/v1/navigation/rooms")
async def list_navigation_rooms():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{NAVIGATION_SERVICE_URL}/api/rooms", timeout=10.0)
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_UNAVAILABLE", "message": str(error)})
    rooms = data.get("data") if response.status_code == 200 and data.get("success") else None
    if not isinstance(rooms, list):
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_INVALID_RESPONSE", "message": "Room list unavailable"})
    return {"rooms": [{"code": item.get("code"), "name_th": item.get("name_th"), "floor": item.get("floor")} for item in rooms if isinstance(item, dict) and item.get("code") and item.get("name_th")][:200]}


@app.post("/api/v1/robots/{robot_slug}/connect")
async def connect_robot(robot_slug: str):
    """Send a handshake to one selected client and report discovery state."""
    with robot_registry_lock:
        robot = robot_registry.get(robot_slug)
    if not robot or time.time() - robot.get("last_seen", 0) > 90:
        raise HTTPException(status_code=404, detail=f"Zenbo client '{robot_slug}' is offline or not discovered")
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/interact", json.dumps({
        "text": "บุ๊คกี้พร้อมแล้วครับ",
        "voice": "th_m_1",
        "age": 10,
        "speed": 0.78,
        "face": "HAPPY",
        "robot_slug": robot_slug,
    }), qos=1)
    robot = dict(robot)
    robot["age_seconds"] = round(time.time() - robot.get("last_seen", time.time()))
    robot.pop("last_seen", None)
    return {"status": "connected", "robot_slug": robot_slug, "known": True, "robot": robot}

@app.post("/api/v1/robot/interact")
async def robot_interact(cmd: InteractCommand):
    started_at = time.perf_counter()
    if cmd.voice_profile and cmd.voice_profile not in VOICE_PROFILES:
        raise HTTPException(status_code=422, detail={
            "code": "UNKNOWN_VOICE_PROFILE",
            "message": "Unsupported voice_profile",
            "supported": list(VOICE_PROFILES.keys()),
        })

    audio_url = None

    # Profile-aware APKs obtain WAV directly from the robot-network TTS service
    # at :8025.  Do not generate an unusable public cache URL for those clients.
    # Legacy requests remain compatible with the existing neural-cache flow.
    if cmd.text and not cmd.voice_profile:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{TTS_SERVICE_URL}/api/v1/tts/synthesize",
                    json={
                        "text": cmd.text,
                        "voice": cmd.voice,
                        "rate": cmd.rate,
                        "pitch": cmd.pitch
                    },
                    timeout=10.0
                )
                if res.status_code == 200:
                    tts_data = res.json()
                    audio_url = f"{SERVER_PUBLIC_HOST}{tts_data['url']}"
        except Exception as e:
            print(f"[!] TTS Request failed: {e}")

    payload = {
        "text": cmd.text,
        "voice_profile": cmd.voice_profile,
        "voice": cmd.voice,
        "age": None,
        "speed": None,
        "audio_url": audio_url,
        "face": cmd.face,
        "motion": cmd.motion.model_dump() if cmd.motion else None,
        "head": cmd.head.model_dump() if cmd.head else None,
        "head_sequence": [step.model_dump() for step in cmd.head_sequence] if cmd.head_sequence else None,
        "action": cmd.action.model_dump() if cmd.action else None,
        "wheel_lights": cmd.wheel_lights.model_dump() if cmd.wheel_lights else None,
        "emotional_action": cmd.emotional_action.model_dump() if cmd.emotional_action else None,
        "remote_control": cmd.remote_control.model_dump() if cmd.remote_control else None,
        "behavior": cmd.behavior.model_dump() if cmd.behavior else None,
        "vision": cmd.vision.model_dump() if cmd.vision else None,
        "youtube": cmd.youtube.model_dump() if cmd.youtube else None,
        "navigation": cmd.navigation.model_dump() if cmd.navigation else None,
    }
    
    topic_prefix = f"zenbo/{cmd.robot_slug}" if cmd.robot_slug else "zenbo"
    mqtt_client.publish(f"{topic_prefix}/cmd/interact", json.dumps(payload), qos=1)
    
    if audio_url:
        mqtt_client.publish(f"{topic_prefix}/cmd/speak", json.dumps({"audio_url": audio_url, "text": cmd.text, "face": cmd.face}), qos=1)
    if cmd.face:
        mqtt_client.publish(f"{topic_prefix}/cmd/expression", json.dumps({"face": cmd.face}), qos=1)
    if cmd.motion:
        mqtt_client.publish(f"{topic_prefix}/cmd/motion", json.dumps(cmd.motion.model_dump()), qos=1)
    if cmd.head:
        mqtt_client.publish(f"{topic_prefix}/cmd/head", json.dumps(cmd.head.model_dump()), qos=1)
    if cmd.head_sequence:
        mqtt_client.publish(f"{topic_prefix}/cmd/head_sequence", json.dumps([step.model_dump() for step in cmd.head_sequence]), qos=1)
    if cmd.action:
        mqtt_client.publish(f"{topic_prefix}/cmd/action", json.dumps(cmd.action.model_dump()), qos=1)
    if cmd.wheel_lights:
        mqtt_client.publish(f"{topic_prefix}/cmd/lights", json.dumps(cmd.wheel_lights.model_dump()), qos=1)
    if cmd.emotional_action:
        mqtt_client.publish(f"{topic_prefix}/cmd/emotional", json.dumps(cmd.emotional_action.model_dump()), qos=1)
    if cmd.remote_control:
        mqtt_client.publish(f"{topic_prefix}/cmd/remote", json.dumps(cmd.remote_control.model_dump()), qos=1)
    if cmd.behavior:
        mqtt_client.publish(f"{topic_prefix}/cmd/behavior", json.dumps(cmd.behavior.model_dump()), qos=1)
    if cmd.vision:
        mqtt_client.publish(f"{topic_prefix}/cmd/vision", json.dumps(cmd.vision.model_dump()), qos=1)
    if cmd.youtube:
        mqtt_client.publish(f"{topic_prefix}/cmd/youtube", json.dumps(cmd.youtube.model_dump()), qos=1)

    accepted_latency_ms = round((time.perf_counter() - started_at) * 1000)
    history_id = record_command_history(cmd.robot_slug, cmd.source, "MQTT_PUBLISHED", payload, accepted_latency_ms,
                                        user_id=cmd.user_id, display_name=cmd.display_name)
    return {"status": "dispatched", "payload": payload, "history_id": history_id,
            "accepted_latency_ms": accepted_latency_ms}

@app.post("/api/v1/robot/stop")
async def robot_emergency_stop():
    payload = {"emergency": True}
    mqtt_client.publish("zenbo/cmd/stop", json.dumps(payload), qos=2)
    history_id = record_command_history(None, "liff", "EMERGENCY_STOP_SENT", payload)
    return {"status": "stopped", "history_id": history_id}


@app.post("/api/v1/robots/{robot_slug}/stop")
async def robot_stop(robot_slug: str):
    payload = {"emergency": True, "robot_slug": robot_slug}
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/stop", json.dumps(payload), qos=2)
    history_id = record_command_history(robot_slug, "liff", "EMERGENCY_STOP_SENT", payload)
    return {"status": "stopped", "robot_slug": robot_slug, "history_id": history_id}


@app.post("/api/v1/user-robot-binding")
async def upsert_user_robot_binding(req: UserRobotBindingRequest):
    """Bind a LINE userId to a robot slug (QR pairing / permission grant)."""
    with command_history_lock, sqlite3.connect(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            """INSERT INTO user_robot_binding (user_id, robot_slug, display_name, permission, created_at_ms)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, robot_slug) DO UPDATE SET
                 display_name = excluded.display_name,
                 permission = excluded.permission""",
            (req.user_id, req.robot_slug, req.display_name, req.permission, int(time.time() * 1000)),
        )
    return {"status": "bound", "user_id": req.user_id, "robot_slug": req.robot_slug, "permission": req.permission}


@app.get("/api/v1/user-robot-binding/{user_id}")
async def get_user_robot_bindings(user_id: str):
    with command_history_lock, sqlite3.connect(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT user_id, robot_slug, display_name, permission, created_at_ms FROM user_robot_binding WHERE user_id = ? ORDER BY robot_slug",
            (user_id,),
        ).fetchall()
    return {"bindings": [{
        "user_id": row[0], "robot_slug": row[1], "display_name": row[2],
        "permission": row[3], "created_at_ms": row[4],
    } for row in rows]}


@app.delete("/api/v1/user-robot-binding/{user_id}/{robot_slug}")
async def delete_user_robot_binding(user_id: str, robot_slug: str):
    with command_history_lock, sqlite3.connect(COMMAND_HISTORY_DB) as connection:
        cursor = connection.execute(
            "DELETE FROM user_robot_binding WHERE user_id = ? AND robot_slug = ?",
            (user_id, robot_slug),
        )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Binding not found")
    return {"status": "unbound", "user_id": user_id, "robot_slug": robot_slug}
