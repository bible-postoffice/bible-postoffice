# 인덱스, 로그아웃 등 기본 페이지
@app.route('/')
def index():
    display_name = session.get('user_nickname', '사용자')
    has_postbox = session.get('has_postbox', False)
    postbox_url = session.get('postbox_url')

    if 'user_email' in session:
        # 세션에 정보가 없거나 확실하지 않을 때만 DB 재확인
        if not has_postbox:
            try:
                email = session['user_email']
                # DB에서 유저 ID 조회
                user_res = supabase.table('bible_users').select("id").eq("email", email).execute()
                
                if user_res.data:
                    user_id = user_res.data[0]['id']
                    # flag 여부와 상관없이 실제 우체통 존재 여부 확인
                    pb_res = supabase.table('postboxes').select("url").eq("owner_id", user_id).limit(1).execute()
                    if pb_res.data:
                        has_postbox = True
                        postbox_url = pb_res.data[0]['url']
                        # 세션 업데이트
                        session['has_postbox'] = True
                        session['postbox_url'] = postbox_url
            except Exception as e:
                print(f"Index DB Error: {e}")

    return render_template('index.html',
                            has_postbox=has_postbox,
                            postbox_url=postbox_url,
                            is_logged_in=bool(session.get('user_email')))
