import os
from dotenv import load_dotenv


# --------------------------------------------------
# BASE DIR + ENV
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, "ai.env")

load_dotenv(ENV_PATH)


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")