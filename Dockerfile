FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF 캐시 위치 (이미지 빌드 시 모델을 미리 받아놓음)
ENV HF_HOME=/app/hf-cache
RUN mkdir -p /app/hf-cache

# Python 패키지 설치
COPY requirements.txt .
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 미리 임베딩 모델 다운로드해 런타임 첫 요청 지연을 줄인다
RUN python - <<'PY'
from sentence_transformers import SentenceTransformer

SentenceTransformer('intfloat/multilingual-e5-small')
print('✅ downloaded embedding model to cache')
PY

# 애플리케이션 코드 복사
COPY . .

# ChromaDB 데이터 디렉토리
RUN mkdir -p /app/chroma_data

# Cloud Run
ENV PORT=8080

# ✅ timeout 0 제거, ✅ workers 증가
CMD exec gunicorn --bind :$PORT --workers 1 --threads 2 --timeout 300 app:app


