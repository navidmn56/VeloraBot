# test_gemini_new.py
import asyncio
from google import genai
from google.genai import types

async def test_gemini():
    API_KEY = "YOUR_GEMINI_API_KEY"  # کلید خود را وارد کنید
    
    try:
        client = genai.Client(api_key=API_KEY)
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="سلام، چطوری؟ یه تست ساده است"
        )
        
        print("✅ موفقیت آمیز!")
        print(f"پاسخ: {response.text}")
        
    except Exception as e:
        print(f"❌ خطا: {e}")

asyncio.run(test_gemini())