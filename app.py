# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import chromadb
import uuid
from datetime import datetime
from sentence_transformers import SentenceTransformer
import os
import re
import requests
from dotenv import load_dotenv

# 기존에 작성하신 라이브러리 임포트
from popular_verses import (
    get_popularity_score,
    extract_chapter_verse,
    normalize_korean,
    BOOK_NAME_MAP,
)

load_dotenv()

app = Flask(__name__)
# 세션 및 보안을 위한 시크릿 키 (로그인 구현 시 필수)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "bible-mailbox-secret-key")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# --- [중략: 제공해주신 임베딩 모델 및 ChromaDB 초기화 로직] ---
# (이 부분에는 제공해주신 embedding_model 로드와 bible_collection 초기화 코드가 그대로 들어갑니다.)

# --- [중략: 테마 및 레퍼런스 처리 함수들] ---
# (THEME_CONTEXT_RULES, parse_reference_input, build_reference_label 등 
# 제공해주신 모든 헬퍼 함수들이 이 영역에 위치합니다.)

# ----------------------------------------------------------------
# 1. 메인 및 인증 관련 라우트 (추가/수정된 부분)
# ----------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # 회원가입 폼 데이터 수집
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # [TODO: Supabase 등에 사용자 정보 저장 로직 추가]
        print(f"회원가입 시도: {name}, {email}")
        
        # 가입 성공 시 로그인 페이지로 이동
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 로그인 처리 로직
        email = request.form.get('email')
        password = request.form.get('password')
        
        # [TODO: 인증 확인 로직]
        session['user_email'] = email # 임시 세션 생성
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ----------------------------------------------------------------
# 2. 우체통 및 구절 API 라우트 (기존 로직 유지)
# ----------------------------------------------------------------

@app.route('/api/create-mailbox', methods=['POST'])
def create_mailbox():
    # ... (기존 제공해주신 코드 유지) ...
    pass # 실제 파일에는 제공해주신 로직을 그대로 넣으시면 됩니다.

@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    # ... (기존 제공해주신 시맨틱 검색 로직 유지) ...
    pass

@app.route('/api/send-postcard', methods=['POST'])
def send_postcard():
    # ... (기존 제공해주신 Supabase 저장 로직 유지) ...
    pass

@app.route('/mailbox/<mailbox_id>')
def mailbox(mailbox_id):
    # ... (기존 제공해주신 우체통 조회 로직 유지) ...
    pass

# 회원 로그인 구현 전까지 테스트
@app.route('/setup-postbox')
def setup_mailbox():
    # 임시로 유저 이름을 '나'로 설정 (로그인 연동 전)
    return render_template('setup_postbox.html', user_name="말씀지기")

from flask import Flask, render_template, request
from datetime import datetime

@app.route('/postbox/<name>')
def view_postbox(name):
    # 테스트용 파라미터들
    color = request.args.get('color', 'red')
    privacy = request.args.get('privacy', 'public')
    role = request.args.get('role', 'guest')  # 'owner' 또는 'guest'
    
    # 시간 체크 (2026년 1월 1일로 설정하여 테스트해보세요)
    target_date = datetime(2026, 1, 1, 0, 0, 0)
    is_expired = datetime.now() >= target_date # 현재 시간이 타겟 시간을 지났는가?
    
    is_owner = (role == 'owner')
    
    return render_template('view_postbox.html', 
                           postbox_name=name, 
                           color=color, 
                           privacy=privacy,
                           is_owner=is_owner,
                           is_expired=is_expired)

if __name__ == '__main__':
    # 디버그 모드로 실행
    app.run(debug=True, port=5000)