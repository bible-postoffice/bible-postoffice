from flask import Blueprint, render_template, request, jsonify, session, url_for, redirect, current_app
from services.database import supabase
import config
import uuid
from datetime import datetime, timezone, timedelta
import os
from dateutil.relativedelta import relativedelta

# 우체통 생성 및 조회
postbox_bp = Blueprint('postbox', __name__)

@postbox_bp.route('/postbox/<url_path>')
def view_postbox(url_path):
    try:
        # 1. DB의 'postboxes' 테이블에서 url 컬럼이 url_path와 일치하는 데이터 조회
        result = supabase.table('postboxes').select("*").eq("url", url_path).execute()

        # 2. 데이터가 없는 경우 (잘못된 주소)
        if not result.data:
            print(f"No postbox found in DB for URL: {url_path}")
            return "우체통을 찾을 수 없습니다.", 404

        postbox = result.data[0] # 첫 번째 검색 결과 가져오기
        postbox_id = postbox['id']

        # 2. 해당 우체통에 담긴 편지 개수 세기 (count)
        # .count("exact")를 사용하면 데이터 본문 대신 개수만 효율적으로 가져옵니다.
        postcard_count_res = supabase.table('postcards') \
            .select("*", count="exact") \
            .eq("postbox_id", postbox_id) \
            .execute()
        
        postcard_count = postcard_count_res.count if postcard_count_res.count is not None else 0

       # 3. 보안 및 권한 관리 (세션 기반 소유권 확인)
        user_email = session.get('user_email')
        is_owner = False
        
        if user_email:
            user_res = supabase.table('bible_users').select("id").eq("email", user_email).execute()
            # DB의 owner_id와 현재 로그인 유저의 ID 비교
            if user_res.data and user_res.data[0]['id'] == postbox['owner_id']:
                is_owner = True

        # 4. 개봉일 및 시간 로직 (KST 설정 및 서비스 플로우 관리)
        KST = timezone(timedelta(hours=9))
        end_date = postbox.get('end_date') or '2026-01-01'
        
        try:
            dt_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            target_dt = datetime.combine(dt_date, datetime.min.time(), tzinfo=KST)
        except Exception:
            target_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=KST)
            end_date = '2026-01-01'

        now_kst = datetime.now(KST)
        is_opened = now_kst >= target_dt # 현재 시간이 개봉일 이후인지 여부

        # 5. 공유 및 바이럴을 위한 동적 데이터 구성 (OG 메타 태그 대응)
        # 상대 경로보다 절대 경로(request.host_url) 사용이 공유 시 이미지 인식에 유리합니다.
        og_image_url = f"{request.host_url.rstrip('/')}/static/images/postbox/{postbox['color']}.png"

        return render_template('view_postbox.html', 
                               postbox_name=postbox['name'],
                               prayer_topic=postbox.get('prayer_topic', ''),
                               url_path=url_path,
                               postbox_id=postbox_id,
                               color=postbox['color'],
                               postcard_count=postcard_count,
                              
                               # 보안 및 권한 변수
                               privacy='public' if postbox['privacy'] == 0 else 'private',
                               is_owner=is_owner,
                               is_opened=is_opened,
                               end_date=end_date,
                               is_logged_in=bool(session.get('user_email')),

                               # 공유 및 OG 태그용 변수 (base.html 연동)
                               og_title=f"📮 {postbox['name']}님의 우체통",
                               og_description=postbox.get('prayer_topic') or "따뜻한 마음을 편지에 담아 전달해주세요.",
                               og_image=og_image_url,

                               # API 키 설정 (클라이언트 사이드 통신용)
                               supabase_url=os.environ.get('SUPABASE_URL'),
                               supabase_key=os.environ.get('SUPABASE_KEY'),
                               kakao_js_key=os.environ.get('KAKAO_JS_KEY'))

    except Exception as e:
        print(f"Error in view_postbox: {e}")
        return "오류가 발생했습니다.", 500

@postbox_bp.route('/create-postbox-action', methods=['POST'])
def create_postbox_action():
    if 'user_email' not in session:
        return jsonify({"success": False, "message": "로그인이 필요합니다."}), 401

    data = request.get_json()
    owner_id = data.get('owner_id')
    user_email = session.get('user_email')
    
    try:
        # [핵심 추가] 2. bible_users 테이블에 해당 유저가 있는지 확인 (에러 방지)
        user_check = supabase.table('bible_users').select("id").eq("id", owner_id).execute()
        
        if not user_check.data:
            # 유저 정보가 없다면 자동으로 먼저 생성 (회원가입 정보 동기화)
            display_name = user_email.split('@')[0] if user_email else "사용자"
            supabase.table('bible_users').insert({
                "id": owner_id,
                "email": user_email,
                "nickname": display_name
            }).execute()
            print(f"새로운 유저 등록 완료: {user_email}")

        # 3. 고유 URL 생성
        unique_path = f"{str(uuid.uuid4())[:8]}" 
        
        # 4. 우체통 데이터 구성
        postbox_data = {
            "owner_id": owner_id,
            "name": data.get('name'),
            "prayer_topic": data.get('prayer_topic'),
            "color": data.get('color'),
            "privacy": data.get('privacy'),  # 0: public, 1: private (DB 설계에 맞춤)
            "url": unique_path,
            "is_opened": False,
            "created_at": datetime.now().isoformat()
        }

        # 5. DB에 저장
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

@postbox_bp.route('/check-and-save', methods=['POST'])
def check_and_save():
    try:
        data = request.get_json()
        email = data.get('email')
        token = data.get('token')
        nickname = data.get('nickname', '사용자')

        if not email:
            return jsonify({"success": False, "message": "이메일 정보가 필요합니다."}), 400

        # 1. Upsert 방식으로 사용자 정보 처리 (on_conflict='email' 설정 필요)
        user_data = {
            "email": email,
            "last_login_at": datetime.now().isoformat(),
            "nickname": nickname,
            "token": token
        }
        
        # select와 update를 한 번에 처리하는 upsert 활용 (또는 기존 로직 유지 시 select 결과 활용)
        res = supabase.table('bible_users').upsert(user_data, on_conflict='email').execute()
        
        if not res.data:
            raise Exception("Failed to sync user data")
            
        user_id = res.data[0]['id']

        # 2. 세션 저장
        session.update({
            'user_email': email,
            'user_id': user_id,
            'user_nickname': nickname,
            'token': token
        })

        # 3. 우체통 보유 여부 확인 (최적화: 필요한 컬럼만 조회)
        pb_res = supabase.table('postboxes').select('url').eq('owner_id', user_id).execute()

        has_postbox = False
        postbox_url = None

        if pb_res and hasattr(pb_res, 'data') and pb_res.data:
            has_postbox = True
            postbox_url = pb_res.data[0]['url']

        session['has_postbox'] = has_postbox
        session['postbox_url'] = postbox_url

        # 4. 리다이렉트 URL 결정
        if has_postbox and postbox_url:
            target_url = url_for('postbox.view_postbox', url_path=postbox_url)
        else:
            target_url = url_for('create_postbox_action')

        return jsonify({
            "success": True, 
            "redirect_url": target_url
        })

    except Exception as e:
        current_app.logger.error(f"Auth Sync Error: {str(e)}") # print 대신 logger 권장
        return jsonify({"success": False, "message": "서버 오류가 발생했습니다."}), 500
