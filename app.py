# app.py
from flask import Flask, render_template, request, jsonify
import chromadb
import uuid
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv
from popular_verses import get_popularity_score  # ⭐ 추가

load_dotenv()

app = Flask(__name__)

# 1024차원 임베딩 모델 로드
print("🔄 임베딩 모델 로딩 중...")
embedding_model = SentenceTransformer('intfloat/multilingual-e5-large')
print(f"✅ 임베딩 모델 로드 완료: {embedding_model.get_sentence_embedding_dimension()}차원")

# ChromaDB 초기화
try:
    chroma_client = chromadb.PersistentClient(path="./vectordb2")
    bible_collection = chroma_client.get_collection(name="bible")
    print(f"✅ 컬렉션 로드 성공: {bible_collection.name}")
    print(f"   총 구절 수: {bible_collection.count()}")
except Exception as e:
    print(f"❌ ChromaDB 에러: {e}")
    bible_collection = None

mailboxes = {}
postcards = {}


@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>성경 구절 우체통</title>
        <style>
            body {
                font-family: 'Noto Sans KR', sans-serif;
                text-align: center;
                padding: 50px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
                max-width: 500px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }
            input {
                padding: 15px;
                width: 80%;
                font-size: 16px;
                border: 2px solid #ddd;
                border-radius: 10px;
                margin: 20px 0;
            }
            button {
                padding: 15px 40px;
                font-size: 16px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 10px;
                cursor: pointer;
            }
            button:hover {
                background: #764ba2;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎄 성경 구절 우체통 🎄</h1>
            <p>당신만의 우체통을 만들고<br>소중한 사람들에게 성경 구절을 선물하세요</p>
            <input type="text" id="nickname" placeholder="닉네임을 입력하세요">
            <br>
            <button onclick="createMailbox()">우체통 만들기</button>
        </div>

        <script>
            async function createMailbox() {
                const nickname = document.getElementById('nickname').value;
                if (!nickname) {
                    alert('닉네임을 입력해주세요');
                    return;
                }
                
                const response = await fetch('/api/create-mailbox', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({nickname})
                });
                
                const data = await response.json();
                window.location.href = data.url;
            }
        </script>
    </body>
    </html>
    '''


@app.route('/api/create-mailbox', methods=['POST'])
def create_mailbox():
    data = request.json
    nickname = data.get('nickname')
    
    mailbox_id = str(uuid.uuid4())[:8]
    mailboxes[mailbox_id] = {
        'id': mailbox_id,
        'nickname': nickname,
        'url': f'/mailbox/{mailbox_id}',
        'created_at': datetime.now().isoformat(),
        'is_opened': False
    }
    postcards[mailbox_id] = []
    
    return jsonify({
        'mailbox_id': mailbox_id,
        'url': f'/mailbox/{mailbox_id}'
    })


@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    """semantic 우선 + popularity로 부스팅하는 구절 추천"""
    if not bible_collection:
        return jsonify({'error': 'ChromaDB 컬렉션이 로드되지 않았습니다'}), 500
    
    try:
        data = request.json
        keyword = data.get('keyword', '사랑')
        print(f"\n🔍 검색 키워드: '{keyword}'")
        
        # 1) 쿼리 임베딩
        query_text = f"query: {keyword}"
        query_embedding = embedding_model.encode(query_text).tolist()
        print(f"   임베딩 생성 완료: {len(query_embedding)}차원")
        
        # 2) pre-filter 없이 충분히 넓게 semantic 검색 (예: 상위 50개)
        raw_results = bible_collection.query(
            query_embeddings=[query_embedding],
            n_results=50,           # 넉넉히 가져오고
            include=["documents", "metadatas", "distances"]
        )
        print(f"✅ 1차 벡터 검색 완료: {len(raw_results['documents'][0])}개 결과")
        
        docs = raw_results["documents"][0]
        metas = raw_results["metadatas"][0]
        dists = raw_results["distances"][0]
        
        # 3) semantic score + popularity score를 결합해서 rerank
        reranked = []
        for doc, meta, dist in zip(docs, metas, dists):
            # Chroma distance가 cosine/L2 등에 따라 다른데,
            # 여기서는 일단 (1 - dist)를 유사도처럼 사용
            semantic_score = 1 - dist
            
            popularity = meta.get("popularity", 30)
            # 0~1로 정규화 (0~100 가정)
            pop_norm = popularity / 100.0
            
            # 가중치 조절: semantic 0.8, popularity 0.2 (원하는 비율로 조정 가능)
            final_score = semantic_score * 0.8 + pop_norm * 0.2
            
            reference = meta.get("reference", meta.get("source", ""))
            if not reference:
                reference = "알 수 없는 구절"
            
            reranked.append({
                "text": doc,
                "reference": reference,
                "semantic_score": round(semantic_score, 4),
                "popularity": popularity,
                "final_score": round(final_score, 4),
            })
        
        # 4) final_score 기준으로 정렬
        reranked.sort(key=lambda x: x["final_score"], reverse=True)
        
        # 5) 상위 5개만 반환
        top_k = reranked[:5]
        
        print("📌 최종 선택된 구절 (final_score 기준 상위 5개):")
        for i, r in enumerate(top_k, 1):
            print(f"  {i}. [{r['reference']}] final={r['final_score']}, "
                  f"semantic={r['semantic_score']}, pop={r['popularity']}")
            print(f"     {r['text'][:80]}...")
        
        return jsonify({"verses": top_k})
    
    except Exception as e:
        print(f"❌ 검색 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"검색 실패: {str(e)}"}), 500



def format_results(results):
    """ChromaDB 결과를 포맷팅하는 헬퍼 함수"""
    formatted = []
    if results['documents'] and results['documents'][0]:
        for i, doc in enumerate(results['documents'][0]):
            metadata = results['metadatas'][0][i] if results.get('metadatas') else {}
            distance = results['distances'][0][i] if results.get('distances') else 0
            
            reference = metadata.get('reference', metadata.get('source', f"구절 {i+1}"))
            similarity_score = round((1 - distance) * 100, 1)
            popularity = metadata.get('popularity', 30)
            
            formatted.append({
                'text': doc,
                'reference': reference,
                'similarity': similarity_score,
                'popularity': popularity
            })
            
            print(f"  [{reference}] 유사도: {similarity_score}% | 인기도: {popularity}")
    
    return formatted


@app.route('/api/send-postcard', methods=['POST'])
def send_postcard():
    data = request.json
    mailbox_id = data.get('mailbox_id')
    
    if mailbox_id not in mailboxes:
        return jsonify({'error': 'Mailbox not found'}), 404
    
    postcard = {
        'id': str(uuid.uuid4()),
        'verse_reference': data.get('verse_reference'),
        'verse_text': data.get('verse_text'),
        'message': data.get('message', ''),
        'created_at': datetime.now().isoformat()
    }
    
    postcards[mailbox_id].append(postcard)
    
    return jsonify({'success': True, 'postcard_id': postcard['id']})


@app.route('/mailbox/<mailbox_id>')
def mailbox(mailbox_id):
    if mailbox_id not in mailboxes:
        return "우체통을 찾을 수 없습니다", 404
    
    mailbox_data = mailboxes[mailbox_id]
    
    if datetime.now() >= datetime(2026, 1, 1) or mailbox_data['is_opened']:
        mailbox_data['is_opened'] = True
        return render_template('mailbox.html', 
                             mailbox=mailbox_data, 
                             postcards=postcards.get(mailbox_id, []))
    else:
        return render_template('mailbox_locked.html', mailbox=mailbox_data)


@app.route('/send/<mailbox_id>')
def send_page(mailbox_id):
    if mailbox_id not in mailboxes:
        return "우체통을 찾을 수 없습니다", 404
    
    return render_template('send_postcard.html', mailbox_id=mailbox_id)


def open_all_mailboxes():
    for mailbox_id in mailboxes:
        mailboxes[mailbox_id]['is_opened'] = True


scheduler = BackgroundScheduler()
scheduler.add_job(
    func=open_all_mailboxes,
    trigger='cron',
    year=2026,
    month=1,
    day=1,
    hour=0,
    minute=0
)
scheduler.start()


if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 Flask 서버 시작")
    print("✅ 시맨틱 검색 활성화 (1024차원 벡터)")
    print("✅ 인기도 필터링 활성화 (3-tier 검색)")
    print("📍 브라우저에서 접속: http://127.0.0.1:5001")
    print("="*50 + "\n")
    app.run(host='127.0.0.1', port=5001, debug=True, threaded=True)
