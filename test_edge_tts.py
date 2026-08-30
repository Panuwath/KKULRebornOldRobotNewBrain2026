import asyncio
import edge_tts

async def generate_natural_voices():
    text_male = "สวัสดีครับอาจารย์และเพื่อนๆ ทุกคน ยินดีต้อนรับเข้าสู่โปรเจกต์หุ่นยนต์เซนโบนะครับ วันนี้มีข้อมูลอะไรให้ผมช่วยดูแลไหมครับ"
    text_female = "สวัสดีค่ะอาจารย์และเพื่อนๆ ทุกคน ยินดีต้อนรับเข้าสู่โปรเจกต์หุ่นยนต์เซนโบนะคะ วันนี้มีข้อมูลอะไรให้หนูช่วยดูแลไหมคะ"
    
    # 1. เสียงผู้ชายไทยแบบมนุษย์ธรรมชาติสูง (th-TH-NiwatNeural)
    male_voice = "th-TH-NiwatNeural"
    communicate_male = edge_tts.Communicate(text_male, male_voice, rate="+5%", pitch="+0Hz")
    await communicate_male.save("natural_male_human.mp3")
    print("[✓] สร้าง natural_male_human.mp3 สำเร็จ (เสียงผู้ชายธรรมชาติระดับสตูดิโอ)")

    # 2. เสียงผู้หญิงไทยหวานธรรมชาติสูง (th-TH-PremwadeeNeural)
    female_voice = "th-TH-PremwadeeNeural"
    communicate_female = edge_tts.Communicate(text_female, female_voice, rate="+3%", pitch="+2Hz")
    await communicate_female.save("natural_female_human.mp3")
    print("[✓] สร้าง natural_female_human.mp3 สำเร็จ (เสียงผู้หญิงหวานธรรมชาติระดับสตูดิโอ)")

if __name__ == "__main__":
    asyncio.run(generate_natural_voices())
