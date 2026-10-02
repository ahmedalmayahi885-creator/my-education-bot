import os
from dotenv import load_dotenv

load_dotenv()

def _required(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value

BOT_TOKEN = _required('BOT_TOKEN')
ADMIN_ID = int(_required('ADMIN_ID'))
DATABASE_URL = _required('DATABASE_URL')
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME', '').strip()

# Railway/Postgres providers often expose postgres:// or postgresql:// URLs.
# SQLAlchemy async engine needs the asyncpg driver explicitly.
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql+asyncpg://' + DATABASE_URL[len('postgres://'):]
elif DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = 'postgresql+asyncpg://' + DATABASE_URL[len('postgresql://'):]

if CHANNEL_USERNAME and not CHANNEL_USERNAME.startswith('@'):
    CHANNEL_USERNAME = '@' + CHANNEL_USERNAME
