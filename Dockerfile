FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF 캐시 위치 (런타임 다운로드 캐시)
ENV HF_HOME=/tmp/hf-cache
RUN mkdir -p /tmp/hf-cache

# Python 패키지 설치
COPY requirements.txt .
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 애플리케이션 코드 복사
COPY . .

# ChromaDB 데이터 디렉토리
RUN mkdir -p /app/chroma_data

# Cloud Run
ENV PORT=8080

# ✅ timeout 0 제거, ✅ workers 증가
CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 --timeout 300 app:app
