# คู่มือการตั้งค่าระบบสังเคราะห์เสียงภาษาไทยออฟไลน์: โทนเสียงนักศึกษาและวัยทำงาน (Thai Offline TTS: Young Adult & University Student Persona)

คู่มือนี้สรุปขั้นตอนการติดตั้งและตั้งค่าพารามิเตอร์ของระบบสังเคราะห์เสียง **วจนะ (Vachana TTS / PyThaiTTS)** แบบ Offline โดยปรับแต่งเฉพาะทางสำหรับ **"โทนเสียงนักศึกษา / First Jobber / วัยทำงานตอนต้น (อายุ 20–24 ปี)"** เพื่อให้น้ำเสียงมีความสุภาพ คล่องแคล่ว ฉะฉาน เป็นมิตร และมีความเป็นมืออาชีพ พร้อมสคริปต์เชื่อมต่อ API กับ n8n และหุ่นยนต์ Zenbo

---

## 1. วิธีติดตั้งระบบและไลบรารี (System Installation)

### ขั้นตอนที่ 1: ติดตั้ง Virtual Environment (Python 3.9 - 3.12)
```bash
# สร้าง virtual environment
python -m venv .venv

# เปิดใช้งาน (Activate)
# สำหรับ macOS / Linux:
source .venv/bin/activate

# สำหรับ Windows:
# .venv\Scripts\activate
```

### ขั้นตอนที่ 2: ติดตั้งไลบรารีประมวลผลคำและเสียงพูด
```bash
pip install --upgrade pip
pip install pythaitts onnxruntime pythainlp requests numpy fastapi uvicorn
```
> **หมายเหตุ**: `pythaitts` จะติดตั้งแพ็กเกจย่อย `vachanatts` ซึ่งเป็นตัวเชื่อมโยงตรงกับโมเดล VITS ภาษาไทยโดยอัตโนมัติ

---

## 2. พารามิเตอร์การจูนโทนเสียงนักศึกษาและวัยทำงาน (Young Professional Styling)

เพื่อสร้างบุคลิกเสียงที่มีความ **มั่นใจ ฉะฉาน สุภาพ เป็นกันเอง และน่าเชื่อถือ** เหมาะกับบทบาทผู้ช่วยอัจฉริยะ (AI Assistant / Service Robot):

### ตารางพารามิเตอร์เสียง (Audio Profile)
| พารามิเตอร์ | ค่าที่แนะนำ | คำอธิบายและผลลัพธ์ |
| :--- | :---: | :--- |
| **Pitch Factor** | **1.00** (หรือ 1.02–1.05 สำหรับเสียงสดใสขึ้นเล็กน้อย) | คลื่นเสียงธรรมชาติช่วงวัยหนุ่มสาว (Young Adult) คมชัดที่สุด ไม่แหลมเล็ก |
| **VITS Speed** | **1.05** | ความเร็วของโมเดล VITS ต้นทาง |
| **Net Speed** | **1.05x** | ความเร็วเสียงลัพธ์สุทธิ พูดคล่องแคล่ว กระชับ ทันสมัย ไม่เนือยช้า |
| **noise_scale** | **0.70 – 0.75** | ให้ความกังวานและมีชีวิตชีวา อบอุ่น สุภาพ ไม่เป็นทางการจนแข็งทื่อ |
| **noise_w_scale** | **0.80** | คุมความยาวสระให้กระชับ ชัดถ้อยชัดคำ เหมาะกับการสื่อสารในการทำงาน |

---

## 3. กฎการจัดรูปแบบข้อความสำหรับบทสนทนาวัยทำงาน (Text Preprocessing for Professional Dialogue)

ก่อนป้อนข้อความเข้าสู่โมเดล ควรแปลงข้อความตามรูปแบบภาษาพูดของคนรุ่นใหม่และคนทำงาน:

1. **การปรับหางเสียงให้สุภาพและเป็นมิตร (Polite & Friendly Endings)**:
   * ลากเสียงสระหางประโยคเล็กน้อยเพื่อลดความแข็งกระด้าง เช่น:
     * `ครับผม` $\rightarrow$ `ครับผมม  `
     * `ได้เลยค่ะ` $\rightarrow$ `ได้เลยค่าา  `
     * `ยินดีช่วยเหลือครับ` $\rightarrow$ `ยินดีช่วยเหลือนะคร้าบ  `
     * `เรียบร้อยแล้วค่ะ` $\rightarrow$ `เรียบร้อยแล้วนะค้าา  `
2. **การเว้นวรรค 2 เคาะ เพื่อจังหวะการนำเสนอที่เป็นมืออาชีพ**:
   * ใส่ `"  "` (สองเคาะ) คั่นระหว่างประโยคใจความสำคัญ เพื่อให้มีจังหวะหายใจและหยุดพักสายตา เช่น:
     * `"สวัสดีครับทุกคน  วันนี้ผมมีข้อมูลโปรเจกต์มาอัปเดตครับผมม  "`
   * ใส่ `"  "` ปิดท้ายประโยคเสมอ เพื่อให้เสียง Fade out อย่างนุ่มนวล
3. **การแปลงคำศัพท์เฉพาะทางและคำทับศัพท์ (Term Transliteration)**:
   * ทับศัพท์ภาษาอังกฤษเป็นคำอ่านภาษาไทย:
     * `Presentation` $\rightarrow$ `พรีเซนเตชัน`
     * `Dashboard` $\rightarrow$ `แดชบอร์ด`
     * `AI Assistant` $\rightarrow$ `เอไอ แอสซิสแทนต์`
     * `Meeting` $\rightarrow$ `มีตติ้ง`
     * `Project` $\rightarrow$ `โปรเจกต์`
   * แปลงตัวเลขและสถิติเป็นคำอ่านภาษาไทย เช่น `2567` $\rightarrow$ `สองพันห้าร้อยหกสิบเจ็ด`, `80%` $\rightarrow$ `แปดสิบเปอร์เซ็นต์`
   * ลบเครื่องหมายพิเศษและ Emojis ออกทั้งหมด

---

## 4. โค้ดตัวอย่างการสร้างเสียง (Python Implementation)

```python
import wave
import io
import os
import numpy as np
from vachanatts import TTS

tts_func = TTS

def generate_young_adult_voice(
    text: str,
    voice: str = "th_f_1",  # "th_f_1" (หญิง) หรือ "th_m_1" (ชาย)
    output_file: str = "young_adult_voice.wav",
    pitch_factor: float = 1.00,
    speed: float = 1.05
):
    """
    สร้างไฟล์เสียง WAV ภาษาไทยสำหรับคาแรคเตอร์นักศึกษา / วัยทำงาน (Young Professional)
    """
    # 1. จัดรูปแบบข้อความ (Text Formatting)
    clean_text = text.strip() + "  "
    
    # 2. คำนวณความเร็ว VITS
    vits_speed = speed / pitch_factor
    temp_wav = "temp_young_raw.wav"
    
    # 3. สังเคราะห์เสียงด้วยพารามิเตอร์สำหรับวัยทำงาน
    tts_func(
        text=clean_text,
        voice=voice,
        output=temp_wav,
        speed=vits_speed,
        noise_scale=0.75,     # น้ำเสียงสดใส สุภาพ มีชีวิตชีวา
        noise_w_scale=0.80     # ชัดถ้อยชัดคำ
    )
    
    # 4. หากมีการปรับ Pitch เล็กน้อย ให้ทำ Resampling
    if pitch_factor != 1.00:
        with wave.open(temp_wav, 'rb') as wav_in:
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
            
        if os.path.exists(temp_wav):
            os.remove(temp_wav)
    else:
        # หาก pitch = 1.00 สามารถเปลี่ยนชื่อไฟล์ตรงได้ทันที
        if os.path.exists(output_file):
            os.remove(output_file)
        os.rename(temp_wav, output_file)
        
    return output_file

if __name__ == "__main__":
    test_text = "สวัสดีครับอาจารย์และพี่ๆ ทุกท่าน  ระบบพร้อมเริ่มการนำเสนอโปรเจกต์แล้วครับผมม  "
    generate_young_adult_voice(test_text)
    print("สร้างไฟล์เสียงเสียงนักศึกษา/วัยทำงานเรียบร้อยแล้ว!")
```

---

## 5. การพัฒนา FastAPI Server และเชื่อมต่อกับ n8n

### ไฟล์ `server.py`
```python
import os
import io
import wave
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from vachanatts import TTS

app = FastAPI(title="Thai Young Adult TTS Service")
tts_func = TTS

class TTSRequest(BaseModel):
    text: str = Field(..., example="สวัสดีครับ  ผมพร้อมรายงานสรุปข้อมูลการประชุมวันนี้แล้วครับผมม  ")
    voice: str = Field(default="th_f_1", example="th_f_1")
    pitch: float = Field(default=1.00, example=1.00)
    speed: float = Field(default=1.05, example=1.05)

@app.post("/api/tts/binary")
async def generate_tts_binary(req: TTSRequest):
    try:
        # Preprocessing: เติม 2 เคาะ ท้ายข้อความ
        processed_text = req.text.strip() + "  "
        
        vits_speed = req.speed / req.pitch
        temp_wav = f"temp_{os.getpid()}.wav"
        
        tts_func(
            text=processed_text,
            voice=req.voice,
            output=temp_wav,
            speed=vits_speed,
            noise_scale=0.75,
            noise_w_scale=0.80
        )
        
        with wave.open(temp_wav, 'rb') as wav_in:
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
                
        if req.pitch != 1.00:
            new_n_samples = int(len(data) / req.pitch)
            indices = np.linspace(0, len(data) - 1, new_n_samples)
            resampled_data = np.interp(indices, np.arange(len(data)), data)
            resampled_bytes = resampled_data.astype(data.dtype).tobytes()
        else:
            resampled_data = data
            resampled_bytes = audio_data
            
        out_buf = io.BytesIO()
        with wave.open(out_buf, 'wb') as wav_out:
            wav_out.setparams(params)
            wav_out.setnframes(len(resampled_data))
            wav_out.writeframes(resampled_bytes)
            
        wav_bytes = out_buf.getvalue()
        
        if os.path.exists(temp_wav):
            os.remove(temp_wav)
            
        return Response(content=wav_bytes, media_type="audio/wav")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### การตั้งค่าใน n8n:
* **HTTP Method**: `POST`
* **URL**: `http://localhost:8000/api/tts/binary`
* **Headers**: `Content-Type: application/json`
* **JSON Body ตัวอย่าง**:
  ```json
  {
    "text": "สวัสดีครับทุกท่าน  ระบบตรวจสอบข้อมูลเรียบร้อยแล้ว  พร้อมเริ่มการทำงานในขั้นตอนถัดไปครับผมม  ",
    "voice": "th_f_1",
    "pitch": 1.00,
    "speed": 1.05
  }
  ```
* **n8n Response Format**: เลือกเป็น `File` (Binary) เพื่อส่งไฟล์ WAV ไปยังหุ่นยนต์ Zenbo หรือระบบเสียงของแอปพลิเคชัน
