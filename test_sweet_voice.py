import wave
import os
import numpy as np
from vachanatts import TTS

tts_func = TTS

def generate_sweet_voice(
    text: str,
    voice: str = "th_f_1",
    output_file: str = "sweet_voice_test.wav",
    pitch_factor: float = 1.08, # โทนเสียงหวาน นุ่ม สดใส
    net_speed: float = 1.00     # จังหวะพูดนุ่มนวล เป็นมิตร
):
    print(f"[*] เริ่มประมวลผลสังเคราะห์เสียงหวานๆ...")
    print(f"    - ข้อความ: {text}")
    print(f"    - Pitch Factor: {pitch_factor} | Net Speed: {net_speed}")

    # 1. จัดการข้อความ (Preprocessing)
    clean_text = text.strip() + "  "

    # 2. คำนวณความเร็ว VITS
    vits_speed = net_speed / pitch_factor
    temp_raw = "temp_sweet_raw.wav"

    # 3. รันโมเดล TTS
    tts_func(
        text=clean_text,
        voice=voice,
        output=temp_raw,
        speed=vits_speed,
        noise_scale=0.80,    # เพิ่มมิติความกังวานและอารมณ์หวานๆ
        noise_w_scale=0.85    # สระนุ่มนวล ไม่ห้วน
    )

    # 4. ทำ Resampling เพื่อปรับ Pitch
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

    new_n_samples = int(len(data) / pitch_factor)
    indices = np.linspace(0, len(data) - 1, new_n_samples)
    resampled_data = np.interp(indices, np.arange(len(data)), data)
    resampled_bytes = resampled_data.astype(data.dtype).tobytes()

    with wave.open(output_file, 'wb') as wav_out:
        wav_out.setparams(params)
        wav_out.setnframes(len(resampled_data))
        wav_out.writeframes(resampled_bytes)

    if os.path.exists(temp_raw):
        os.remove(temp_raw)

    print(f"[+] บันทึกไฟล์เสียงสำเร็จ: {output_file}")
    file_size_kb = os.path.getsize(output_file) / 1024
    print(f"    - ขนาดไฟล์: {file_size_kb:.2f} KB")
    return output_file

if __name__ == "__main__":
    sample_text = "สวัสดีค่าา  ยินดีที่ได้ดูแลทุกคนนะค้าา  วันนี้มีข้อมูลอะไรให้ช่วยค้นหาไหมเอ่ยย  "
    out = generate_sweet_voice(sample_text, pitch_factor=1.08, net_speed=1.00)
