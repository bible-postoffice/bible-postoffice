FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF 캐시 위치
ENV HF_HOME=/app/hf-cache
RUN mkdir -p /app/hf-cache

# Python 패키지 설치
COPY requirements.txt .
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 수정된 부분: Heredoc 대신 -c 옵션을 사용하여 모델 미리 다운로드
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small'); print('✅ downloaded embedding model to cache')"

# 애플리케이션 코드 복사
COPY . .

# ChromaDB 데이터 디렉토리
RUN mkdir -p /app/chroma_data

# Cloud Run 포트 설정
ENV PORT=8080

# 서비스 실행 (timeout 설정은 앱 특성에 맞춰 유지)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 2 --timeout 300 app:app
