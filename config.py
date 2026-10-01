import os
from dotenv import load_dotenv

# تحميل المتغيرات من ملف .env إن وجد
load_dotenv()

# توكن البوت
BOT_TOKEN = os.getenv("BOT_TOKEN", "8933862542:AAH9bGh_rVCZXM_1Ln-6FpKkevDoIGgrIFM")

# معرف الأدمن الأساسي (السوبر أدمن)
ADMIN_ID = int(os.getenv("ADMIN_ID", "190332205"))

# رابط أو اسم قاعدة البيانات (educational_bot)
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:123456@localhost:5432/educational_bot"
)

# معرف القناة الخاصة بالبوت
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@alnukba2027")

if not BOT_TOKEN:
    raise ValueError("لم يتم العثور على BOT_TOKEN في الإعدادات")