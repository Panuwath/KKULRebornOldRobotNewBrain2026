import wave
import os
import numpy as np
from vachanatts import TTS

tts_func = TTS

levels_male = [
    {
        "name": "male_level1_friendly",
        "file": "male_friendly_young.wav",
        "voice": "th_m_1",
        "pitch": 1.00,
        "speed": 1.05,
        "noise_scale": 0.75,
        "noise_w_scale": 0.80,
        "desc": "เสียงหนุ่มนักศึกษา/วัยทำงาน อบอุ่น สุภาพ เป็นกันเอง"
    },
    {
        "name": "male_level2_cool",
        "file": "male_cool_energetic.wav",
        "voice": "th_m_1",
        "pitch": 0.95,
        "speed": 1.05,
        "noise_scale": 0.70,
        "noise_w_scale": 0.80,
        "desc": "เสียงทุ้ม นุ่ม มั่นใจ สมาร์ท"
    }
]

text = "สวัสดีครับผมม  ยินดีต้อนรับเข้าสู่โปรเจกต์หุ่นยนต์เซนโบนะคร้าบ  วันนี้มีข้อมูลอะไรให้ผมช่วยดูแลไหมครับบ  "

for item in levels_male:
    temp_raw = f"temp_{item['name']}.wav"
    vits_speed = item["speed"] / item["pitch"]
    
    tts_func(
        text=text,
        voice=item["voice"],
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
            
    if item["pitch"] != 1.0:
        new_n_samples = int(len(data) / item["pitch"])
        indices = np.linspace(0, len(data) - 1, new_n_samples)
        resampled_data = np.interp(indices, np.arange(len(data)), data)
        resampled_bytes = resampled_data.astype(data.dtype).tobytes()
    else:
        resampled_data = data
        resampled_bytes = audio_data
        
    with wave.open(item["file"], 'wb') as wav_out:
        wav_out.setparams(params)
        wav_out.setnframes(len(resampled_data))
        wav_out.writeframes(resampled_bytes)
        
    if os.path.exists(temp_raw):
        os.remove(temp_raw)
        
    print(f"[✓] สร้าง {item['file']} สำเร็จ -> {item['desc']}")
