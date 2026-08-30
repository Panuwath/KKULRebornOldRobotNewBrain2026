import os
import hashlib
import asyncio
from fastapi import FastAPI, HTTPException
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import edge_tts

logger = logging.getLogger("uvicorn")

app = FastAPI(title="Zenbo Neural TTS Service", version="1.0.0")

# Middleware to log incoming requests (method, path, body)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    body = await request.body()
    logger.info(f"Incoming request: {request.method} {request.url.path} body={body.decode('utf-8')}")
    response = await call_next(request)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = os.getenv("AUDIO_CACHE_DIR", "/app/audio_cache")
os.makedirs(AUDIO_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=AUDIO_DIR), name="static")

# ----------------------------------------------------------------------
# Voice handling utilities
import logging
logging.basicConfig(level=logging.INFO)
EXTERNAL_VOICE_MAP = {
    "th_m_2": "male_natural",
    "th_f_1": "female_sweet"
}

def normalize_voice(voice: str) -> str:
    """Map external voice identifiers to internal VOICE_MAP keys.
    Returns the internal voice key or the original if it already matches Edge‑TTS format."""
    v = voice.lower()
    # External mapping (e.g., from KKU webhook)
    if v in EXTERNAL_VOICE_MAP:
        return EXTERNAL_VOICE_MAP[v]
    # If already an Edge‑TTS voice id (starts with "th-")
    if v.startswith("th-"):
        return v
    # Fallback to original (may be internal key)
    return v

VOICE_MAP = {
    "female_sweet": "th-TH-PremwadeeNeural",
    "female": "th-TH-PremwadeeNeural",
    "male_natural": "th-TH-NiwatNeural",
    "male": "th-TH-NiwatNeural",
    "boy_cute": "th-TH-NiwatNeural",
    "boy": "th-TH-NiwatNeural",
}

class TTSRequest(BaseModel):
    text: str = Field(..., example="สวัสดีครับ  ยินดีต้อนรับเข้าสู่โปรเจกต์เซนโบนะครับ  ")
    voice: str = Field(default="female_sweet", example="female_sweet")
    rate: str = Field(default="-10%", example="-10%")
    pitch: str = Field(default="+2Hz", example="+2Hz")

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "zenbo-tts-service"}

@app.post("/api/v1/tts/synthesize")
async def synthesize_audio(req: TTSRequest):
    try:
        # Normalize external voice identifier, then map to Edge‑TTS voice ID
        voice_key = normalize_voice(req.voice)
        voice_id = VOICE_MAP.get(voice_key, voice_key)
        
        # สร้าง cache key จาก text + voice + rate + pitch
        hash_input = f"{req.text}_{voice_id}_{req.rate}_{req.pitch}".encode('utf-8')
        file_hash = hashlib.md5(hash_input).hexdigest()
        filename = f"{file_hash}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)

        if not os.path.exists(filepath):
            communicate = edge_tts.Communicate(req.text, voice_id, rate=req.rate, pitch=req.pitch)
            await communicate.save(filepath)

        return {
            "status": "success",
            "filename": filename,
            "url": f"/static/{filename}",
            "text": req.text,
            "voice": voice_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/tts/binary")
async def synthesize_binary(req: TTSRequest):
    try:
        voice_key = normalize_voice(req.voice)
        voice_id = VOICE_MAP.get(voice_key, voice_key)
        communicate = edge_tts.Communicate(req.text, voice_id, rate=req.rate, pitch=req.pitch)
        
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
                
        return Response(content=audio_data, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
