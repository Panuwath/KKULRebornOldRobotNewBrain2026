import asyncio
import edge_tts

async def generate_slower_voices():
    text_male = "สวัสดีครับอาจารย์และเพื่อนๆ ทุกคน... ยินดีต้อนรับเข้าสู่โปรเจกต์หุ่นยนต์เซนโบนะครับ... วันนี้มีข้อมูลอะไร ให้ผมช่วยดูแลไหมครับ"
    text_female = "สวัสดีค่ะอาจารย์และเพื่อนๆ ทุกคน... ยินดีต้อนรับเข้าสู่โปรเจกต์หุ่นยนต์เซนโบนะคะ... วันนี้มีข้อมูลอะไร ให้หนูช่วยดูแลไหมคะ"

    # 1. ผู้ชาย ปรับช้าลง -10% จังหวะผ่อนคลาย สบายหู
    await edge_tts.Communicate(text_male, "th-TH-NiwatNeural", rate="-10%", pitch="+0Hz").save("male_slower_10.mp3")
    
    # 2. ผู้ชาย ปรับช้าลง -15% นุ่มนวล ชัดถ้อยชัดคำเป็นพิเศษ
    await edge_tts.Communicate(text_male, "th-TH-NiwatNeural", rate="-15%", pitch="+0Hz").save("male_slower_15.mp3")

    # 3. ผู้หญิง ปรับช้าลง -10% หวานละมุน ผ่อนคลาย
    await edge_tts.Communicate(text_female, "th-TH-PremwadeeNeural", rate="-10%", pitch="+2Hz").save("female_slower_10.mp3")

    # 4. ผู้หญิง ปรับช้าลง -15% หวาน นุ่มนวล ฟังสบาย
    await edge_tts.Communicate(text_female, "th-TH-PremwadeeNeural", rate="-15%", pitch="+2Hz").save("female_slower_15.mp3")
    
    print("[✓] สร้างไฟล์เสียงเวอร์ชันพูดช้าลงสำเร็จทุกไฟล์")

if __name__ == "__main__":
    asyncio.run(generate_slower_voices())
