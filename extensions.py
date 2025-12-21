# extensions.py
import chromadb
from sentence_transformers import SentenceTransformer
from apscheduler.schedulers.background import BackgroundScheduler

chroma_client = chromadb.Client()
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
scheduler = BackgroundScheduler()
