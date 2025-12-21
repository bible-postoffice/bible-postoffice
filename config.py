import os
from dotenv import load_dotenv

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")