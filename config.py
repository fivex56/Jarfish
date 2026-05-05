import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_config():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    return {
        "bot_token": os.environ["BOT_TOKEN"],
        "allowed_user_id": int(os.environ["ALLOWED_USER_ID"]),
        "db_path": str(BASE_DIR / os.environ.get("DB_PATH", "jarvis.db")),
        "log_path": str(BASE_DIR / "jarvis.log"),
        "timezone": os.environ.get("TZ", "Asia/Ho_Chi_Minh"),  # Da Nang = UTC+7
    }
