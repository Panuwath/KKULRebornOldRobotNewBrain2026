import wave
import os
import numpy as np
from vachanatts import TTS

tts_func = TTS

levels = [
    {
        "name": "level_1_soft",
        "file": "sweet_level1_soft.wav",
        "pitch": 1.05,
        "speed": 1.00,
        "noise_scale": 0.75,
        "noise_w_scale": 0.80,
        "desc": "นุ่มนวล สุภาพ เป็นมิตร (นักศึกษา/วัยทำงานรุ่นใหม่)"
    },
    {
        "name": "level_2_bright",
        "file": "sweet_level2_bright.wav",
        "pitch": 1.08,
        "speed": 1.00,
        "noise_scale": 0.80,
        "noise_w_scale": 0.85,
        "desc": "หวาน สดใส มีชีวิตชีวา (Sweet & Bright)"
    },
    {
        "name": "level_3_gentle",
        "file": "sweet_level3_gentle.wav",
        "pitch": 1.12,
        "speed": 0.98,
        "noise_scale": 0.82,
        "noise_w_scale": 0.90,
        "desc": "หวานละมุน อ่อนโยน น่ารักเป็นพิเศษ (Very Sweet & Gentle)"
    }
]

text = "สวัสดีค่าา  ยินดีต้อนรับเข้าสู่โปรเจกต์หุ่นยนต์เซนโบนะค้าา  วันนี้ให้หนูช่วยแนะนำอะไรดีเอ่ยย  "

for item in levels:
    temp_raw = f"temp_{item['name']}.wav"
    vits_speed = item["speed"] / item["pitch"]
    
    tts_func(
        text=text,
        voice="th_f_1",
        output=temp_raw,
        speed=vits_speed,
        noise_scale=item["noise_scale"],
        noise_w_scale=item["noise_w_scale"]
    )
    
    with wave.open(temp_raw, 'rb') as wav_in:
        params = wav_in.getparams()
        n_frames = wav_in.getnframes()
        audio_data = wav_in.readframes(n_frames)
        sample_width = wav_in.getsampwidth()
        
        if sample_width == 1:
            data = np.frombuffer(audio_data, dtype=np.int8)
        elif sample_width == 2:
            data = np.frombuffer(audio_data, dtype=np.int16)
        else:
            data = np.frombuffer(audio_data, dtype=np.int32)
            
    new_n_samples = int(len(data) / item["pitch"])
    indices = np.linspace(0, len(data) - 1, new_n_samples)
    resampled_data = np.interp(indices, np.arange(len(data)), data)
    resampled_bytes = resampled_data.astype(data.dtype).tobytes()
    
    with wave.open(item["file"], 'wb') as wav_out:
        wav_out.setparams(params)
        wav_out.setnframes(len(resampled_data))
        wav_out.writeframes(resampled_bytes)
        
    if os.path.exists(temp_raw):
        os.remove(temp_raw)
        
    print(f"[✓] สร้าง {item['file']} สำเร็จ -> {item['desc']}")
