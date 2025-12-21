import os
from datetime import datetime
import requests
from flask import Flask, render_template, request, jsonify, session, redirect # redirect 추가
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'e48ca7312db5b8f76c0c095e845c9eaf')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/auth/check-and-save', methods=['POST'])
def check_and_save():

    data = request.get_json()
    token = data.get('token')
    email = data.get('email')

    try:
        # 1. 토큰 검증 (Supabase Auth 연동)
        user_info = supabase.auth.get_user(token)
        if not user_info:
            return jsonify({"success": False, "message": "유효하지 않은 토큰"}), 401

        # Supabase 유저 메타데이터에서 display_name 추출
        user_metadata = user_info.user.user_metadata
        nickname = user_metadata.get('display_name') or user_metadata.get('full_name') or email.split('@')[0]
        
        # 2. bible_users 테이블에 Upsert (없으면 생성, 있으면 업데이트)
        # email 컬럼이 Primary Key로 설정되어 있어야 합니다.
        user_data = {
            "email": email,
            "nickname" : nickname,
            "last_login_at": datetime.now().isoformat() # 파이썬에서 시간 생성
        }
        
        # upsert는 기본적으로 on_conflict를 Primary Key로 잡습니다.
        response = supabase.table('bible_users').upsert(user_data).execute()

        if not response.data:
            return jsonify({"success": False, "message": "유저 정보를 찾을 수 없습니다."}), 404
        
        user = response.data[0]
        user_id = user.get('id')
        user_flag = user.get('flag', False) # flag 값 확인 (True/False)
        
        # 세션에 이메일 저장 (로그인 유지용)
        session['user_email'] = email
        session['user_nickname'] = nickname


        # 2. 로직 분기
        if user_flag:
            # [Case: flag=true] 우체통 정보 조회
            postbox_res = supabase.table('postboxes').select('url').eq('owner_id', user_id).execute()
            
            if postbox_res.data:
                # 우체통 URL이 존재하면 해당 주소로 안내
                postbox_url = postbox_res.data[0].get('url')
                print(f"Redirecting to: /postbox/{postbox_url}")
                return jsonify({
                    "success": True,
                    "redirect_url": f"/postbox/{postbox_url}", # 실제 우체통 주소
                    "status": "existing_user",
                    "nickname": nickname
                })
            else:
                # 데이터 정합성 방어: flag는 true인데 postbox가 없는 경우
                return jsonify({"success": True, "redirect_url": "/create-postbox", "status": "new_user"})
        
        else:
            # [Case: flag=false] 계정은 있으나 우체통은 없음 -> 생성 페이지로
            return jsonify({
                "success": True, 
                "redirect_url": "/create-postbox", 
                "status": "new_user",
                "nickname": nickname
            })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


import uuid

@app.route('/create-postbox-action', methods=['POST'])
def create_postbox_action():
    if 'user_email' not in session:
        return jsonify({"success": False, "message": "로그인이 필요합니다."}), 401

    data = request.get_json()
    
    try:
        # 고유 URL 생성 (예: nickname-4자리숫자)
        unique_path = f"{str(uuid.uuid4())[:8]}" 
        
        postbox_data = {
            "owner_id": data.get('owner_id'),
            "name": data.get('name'),
            "prayer_topic": data.get('prayer_topic'),
            "color": data.get('color'),
            "privacy": data.get('privacy'), # True/False
            "url": unique_path,
            "is_opened": False,
            "created_at" : datetime.now().isoformat()
        }

        # DB에 저장 (이때 SQL에서 만든 트리거가 bible_users의 flag를 true로 바꿈)
        result = supabase.table('postboxes').insert(postbox_data).execute()

        if result.data:
            return jsonify({
                "success": True, 
                "url": unique_path
            })
        else:
            return jsonify({"success": False, "message": "DB 저장 실패"}), 500

    except Exception as e:
        print(f"Create Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/create-postbox')
def create_postbox_page():
    if 'user_email' not in session:
        return redirect('/')
    
    user_nickname = session.get('user_nickname', '사용자')

    return render_template('create_postbox.html',
                           user_name=user_nickname,
                           supabase_url=os.environ.get('SUPABASE_URL'), 
                           supabase_key=os.environ.get('SUPABASE_KEY')
                           )

# 우체통 확인
@app.route('/postbox/<url_path>')
def view_postbox(url_path):
    try:
        # 1. DB의 'postboxes' 테이블에서 url 컬럼이 url_path와 일치하는 데이터 조회
        result = supabase.table('postboxes').select("*").eq("url", url_path).execute()

        # 2. 데이터가 없는 경우 (잘못된 주소)
        if not result.data:
            print(f"No postbox found in DB for URL: {url_path}")
            return "우체통을 찾을 수 없습니다.", 404

        postbox = result.data[0] # 첫 번째 검색 결과 가져오기

       # 2. 현재 접속자가 주인인지 확인 (세션 기반)
        # 세션의 이메일과 DB의 owner_id(또는 연동된 이메일)를 비교
        # 여기서는 단순화를 위해 세션 이메일이 있고, 해당 유저의 id와 pb['owner_id']가 같은지 확인이 필요합니다.
        # 일단은 로그인 기능을 고려해 아래와 같이 구성합니다.
        user_email = session.get('user_email')
        end_date = session.get('end_date') or '2026-01-01'
        is_owner = False
        
        # 주인을 확인하기 위해 현재 로그인된 유저의 UUID를 가져와야 함
        if user_email:
            user_res = supabase.table('bible_users').select("id").eq("email", user_email).execute()
            if user_res.data and user_res.data[0]['id'] == postbox['owner_id']:
                is_owner = True

        # 3. 개봉일 설정 (예: 2026년 1월 1일)
        from datetime import datetime
        try:
            target_dt = datetime.strptime(end_date, '%Y-%m-%d')
        except:
            # 날짜 형식이 잘못되었을 경우를 대비한 방어 코드
            target_dt = datetime(2026, 1, 1)

        is_expired = datetime.now() >= target_dt

        # 4. 템플릿 렌더링 (HTML에서 사용하는 변수명과 일치시킴)
        return render_template('view_postbox.html', 
                               postbox_name=postbox['name'],
                               color=postbox['color'],
                               # DB가 0이면 'public', 1이면 'private'으로 변환해서 전달
                               privacy='public' if postbox['privacy'] == 0 else 'private',
                               end_date=end_date,
                               is_owner=is_owner,
                               is_expired=is_expired)

    except Exception as e:
        print(f"Error: {e}")
        return "오류가 발생했습니다.", 500

# 편지 작성
@app.route('/send_postcard/<url_path>')
def send_postcard(url_path):
    # 1. 로그인 체크
    if 'user_email' not in session:
        return redirect('/login')

    # 2. 우체통 정보 가져오기 (작성 화면 꾸미기용)
    result = supabase.table('postboxes').select("name, color").eq("url", url_path).execute()
    if not result.data:
        return "존재하지 않는 우체통입니다.", 404

    pb = result.data[0]
    return render_template('send_postcard.html', 
                           url_path=url_path, 
                           postbox_name=pb['name'], 
                           color=pb['color'])


@app.route('/')
def index():
    if 'user_email' in session:
            # 로그인 세션이 있다면 DB에서 flag를 다시 확인
            email = session['user_email']
            user_res = supabase.table('bible_users').select("id, flag").eq("email", email).execute()
            
            if user_res.data and user_res.data[0]['flag'] is True:
                # 우체통이 이미 있다면 내 우체통으로 리다이렉트
                pb_res = supabase.table('postboxes').select("url").eq("owner_id", user_res.data[0]['id']).execute()
                if pb_res.data:
                    return redirect(f"/postbox/{pb_res.data[0]['url']}")
            
            # flag가 false면 생성 페이지로
            return redirect('/create-postbox')
    return render_template('index.html',
                            url=os.environ.get('SUPABASE_URL'), 
                            key=os.environ.get('SUPABASE_KEY'))

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 Flask 서버 시작 (Port: 5001)")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)