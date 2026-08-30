import os
import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP

CORE_API_URL = os.getenv("CORE_API_URL", "http://zenbo-core-api:5005")
mcp = FastMCP("Zenbo-Controller-MCP", host="0.0.0.0", port=8088)

@mcp.tool()
async def zenbo_speak(text: str, voice: str = "female_sweet", face: str = "HAPPY") -> str:
    """Make ASUS Zenbo speak in Thai using neural voice and display facial expression.
    Args:
        text: Thai speech text
        voice: 'female_sweet' or 'male_natural'
        face: 'HAPPY', 'DOUBT', 'SHY', 'PROUD', 'SHOCK', 'TIRED', 'SINGING', 'DEFAULT'
    """
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{CORE_API_URL}/api/v1/robot/interact", json={
                "text": text,
                "voice": voice,
                "face": face
            }, timeout=10.0)
            return f"Spoke: '{text}' (Face: {face}) -> {res.status_code}"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def zenbo_move(x: float = 0.0, y: float = 0.0, theta: float = 0.0, speed: int = 2) -> str:
    """Move Zenbo base robot.
    Args:
        x: meters forward (+) or backward (-)
        y: meters left (+) or right (-)
        theta: rotation degrees (-180 to 180)
        speed: speed level 1-3
    """
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{CORE_API_URL}/api/v1/robot/interact", json={
                "motion": {"x": x, "y": y, "theta": theta, "speed": speed}
            }, timeout=10.0)
            return f"Moved: x={x}, y={y}, theta={theta}° -> {res.status_code}"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def zenbo_move_head(yaw: float = 0.0, pitch: float = 0.0, speed: int = 2) -> str:
    """Turn Zenbo head.
    Args:
        yaw: left/right degrees (-45 to 45)
        pitch: tilt up/down degrees (-15 to 55)
        speed: speed level 1-3
    """
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{CORE_API_URL}/api/v1/robot/interact", json={
                "head": {"yaw": yaw, "pitch": pitch, "speed": speed}
            }, timeout=10.0)
            return f"Head turned: yaw={yaw}°, pitch={pitch}° -> {res.status_code}"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def zenbo_play_action(action_id: int = 22) -> str:
    """Play canned animation on Zenbo (e.g. 22 for dance)."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{CORE_API_URL}/api/v1/robot/interact", json={
                "action": {"action_id": action_id, "stop": False},
                "face": "SINGING"
            }, timeout=10.0)
            return f"Playing action {action_id} -> {res.status_code}"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def zenbo_set_lights(mode: str = "breathing", color: str = "0x00D031") -> str:
    """Set Zenbo wheel LED lights (modes: breathing, blinking, charging, marquee)."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{CORE_API_URL}/api/v1/robot/interact", json={
                "wheel_lights": {"mode": mode, "color": color, "brightness": 15}
            }, timeout=10.0)
            return f"Lights set to mode={mode}, color={color} -> {res.status_code}"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def zenbo_emergency_stop() -> str:
    """Emergency stop all robot motions and audio playback."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{CORE_API_URL}/api/v1/robot/stop", timeout=10.0)
            return "Zenbo EMERGENCY STOPPED."
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    print("[*] Starting Zenbo MCP Server on port 8088...")
    mcp.run(transport="sse")
