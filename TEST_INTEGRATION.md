# Zenbo Client Integration Test

## APK Built Successfully
- Location: `zenbo-client-android/app/build/outputs/apk/debug/app-debug.apk` (8.6 MB)

## MQTT Topics Supported

### Commands (Subscribe)
| Topic | Description |
|-------|-------------|
| `zenbo/cmd/interact` | Original command schema (face, motion, head, action, wheel_lights, vision, text, audio_url) |
| `zenbo/cmd/stop` / `zenbo/stop` | Emergency stop all |
| `zenbo/cmd/expression` | Set face expression |
| `zenbo/cmd/cancel` | Cancel current action |
| `zenbo/cmd/vision` / `zenbo/vision` | Vision commands |
| `zenbo/audio` | Gateway audio command (text→TTS, audio_url) |
| `zenbo/movement` | Gateway movement (dance, move, head, face, lights) |
| `zenbo/ping` | Status check |

### Status (Publish)
| Topic | Payload Example |
|-------|-----------------|
| `zenbo/status/connection` | `{"state":"connected","message":"Connected"}` |
| `zenbo/status/robot_state` | `{"state":"INIT_COMPLETE"}` |
| `zenbo/status/action_done` | `{"status":"SUCCESS","type":"speak"}` |
| `zenbo/status/vision` | `{"action":"detect_face","faces":[...]}` |
| `zenbo/status/error` | `{"code":"MOTION_FAIL_OBSTACLE","message":"cmd=5 serial=1"}` |

## Gateway API (libn-docker:8030)
- `POST /v1/command` - Natural language → command + send
- `POST /v1/compile` - Natural language → compile only
- `POST /v1/dispatch` - Pre-compiled command → send
- `GET /v1/commands` - List all supported commands
- `POST /v1/stop` - Stop robot
- `GET /health` - Health check

## Test Commands

### Test 1: Basic speak via gateway
```bash
curl -X POST http://libn-docker:8030/v1/command \
  -H "Content-Type: application/json" \
  -d '{"text":"สวัสดีครับ ผมบุ๊กกี้","send":true,"robot_slugs":["zenbo1"]}'
```

### Test 2: Movement via gateway
```bash
curl -X POST http://libn-docker:8030/v1/command \
  -H "Content-Type: application/json" \
  -d '{"text":"เดินหน้า 2 ก้าว","send":true,"robot_slugs":["zenbo1"]}'
```

### Test 3: Direct MQTT test (if mosquitto available)
```bash
# Speak
mosquitto_pub -h 10.101.118.149 -p 1883 -t zenbo/audio \
  -m '{"text":"สวัสดีครับ","voice":"th_m_1","age":20,"speed":0.96,"face":"happy"}'

# Move
mosquitto_pub -h 10.101.118.149 -p 1883 -t zenbo/movement \
  -m '{"motion":{"x":0.5,"y":0,"theta":0,"speed":3}}'

# Vision
mosquitto_pub -h 10.101.118.149 -p 1883 -t zenbo/vision \
  -m '{"vision":{"action":"detect_face","interval_ms":1000,"debug_preview":false}}'

# Stop
mosquitto_pub -h 10.101.118.149 -p 1883 -t zenbo/stop -m '{}'

# Ping
mosquitto_pub -h 10.101.118.149 -p 1883 -t zenbo/ping -m '{}'
```

### Test 4: Subscribe to status
```bash
mosquitto_sub -h 10.101.118.149 -p 1883 -t "zenbo/status/#" -v
```

## Architecture Summary

```
LINE/LIFF → n8n → /v1/command → MQTT (zenbo/audio, zenbo/movement, etc.) → Android App → Zenbo SDK
                                                              ↓
                                                    MQTT (zenbo/status/#) → n8n → LINE/LIFF
```

## Key Features Implemented
1. ✅ Zenbo Junior SDK (real 709KB jar) - build successful
2. ✅ MQTT connection to 10.101.118.149:1883
3. ✅ Dual topic support: legacy (`zenbo/cmd/*`) + gateway (`zenbo/audio`, `zenbo/movement`, etc.)
4. ✅ Vision callbacks: detect_face, detect_person, gesture_point, recognize_person
5. ✅ Error reporting via MQTT
6. ✅ TTS via external server with native fallback
7. ✅ Wheel lights: static, breath, strobe, rainbow, wave, comet, starry
8. ✅ Motion: moveBody, moveHead, playAction
9. ✅ Expression: 29 RobotFace types
10. ✅ OTA update support via zenbo/update topic