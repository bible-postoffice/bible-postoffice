import os
from dotenv import load_dotenv
from datetime import timedelta
import re

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

def _clean_env(value):
    if value is None:
        return None
    return value.strip()

# Flask 설정
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'e48ca7312db5b8f76c0c095e845c9eaf')
SESSION_COOKIE_SECURE = bool(os.environ.get('RENDER'))
PERMANENT_SESSION_LIFETIME = timedelta(days=31)

# Supabase 설정
SUPABASE_URL = _clean_env(os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_APP_URL"))
SUPABASE_ANON_KEY = _clean_env(os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_APP_KEY"))
SUPABASE_SERVICE_KEY = _clean_env(os.environ.get("SUPABASE_SERVICE_KEY"))
SUPABASE_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY

SUPABASE_VEC_URL = _clean_env(os.environ.get("SUPABASE_VEC_URL")) or SUPABASE_URL
SUPABASE_VEC_KEY = _clean_env(os.environ.get("SUPABASE_VEC_KEY")) or SUPABASE_KEY

# 카카오 설정
KAKAO_JS_KEY='dee7eaf4212183f48a85c693d00fc9f8'

# 성경 검색 테마 규칙
from popular_verses import (
    get_popularity_score,
    extract_chapter_verse,
    normalize_korean,
    BOOK_NAME_MAP,
)

DEFAULT_CONTEXT_DESCRIPTION = (
    '위로와 격려, 하나님의 신실하심, 회복과 소망, 두려움을 이기는 믿음, 사랑과 용기'
)

THEME_CONTEXT_RULES = [
    {
        "tokens": ['취업', '진로', '직장', '커리어', '회사'],
        "description": '취업과 진로, 장래의 길, 하나님의 공급과 인도, 두려움 대신 담대함',
        "curated_references": [
            "잠언 16:3",
            "잠언 3:5-6",
            "예레미야 29:11",
            "시편 37:23",
            "빌립보서 4:13",
        ],
    },
    {
        "tokens": ['시험', '공부', '학업', '입시'],
        "description": '지혜와 인내, 성실하게 준비하는 마음, 하나님께 맡기는 믿음',
        "curated_references": [
            "야고보서 1:5",
            "고린도전서 10:13",
            "빌립보서 4:6",
            "빌립보서 4:13",
            "잠언 2:6",
        ],
    },
    {
        "tokens": ['위로', '슬픔', '눈물', '상실', '아픔', '고통'],
        "description": '위로와 회복, 함께하시는 하나님, 눈물을 닦아주시는 사랑',
        "curated_references": [
            "시편 119:50",
            "이사야 41:10",
            "시편 34:18",
            "마태복음 11:28",
            "시편 147:3",
        ],
    },
    {
        "tokens": ['소망', '희망', '미래', '장래'],
        "description": '소망과 미래에 대한 약속, 하나님이 예비하신 계획을 신뢰함',
        "curated_references": [
            "예레미야 29:11",
            "고린도전서 13:13",
            "로마서 15:13",
            "히브리서 11:1",
            "시편 71:14",
        ],
    },
    {
        "tokens": ['두려움', '걱정', '근심', '불안'],
        "description": '두려움을 이기는 믿음, 평안, 담대함, 염려를 맡김',
        "curated_references": [
            "이사야 41:10",
            "빌립보서 4:6-7",
            "마태복음 6:34",
            "시편 56:3",
            "디모데후서 1:7",
        ],
    },
    {
        "tokens": ['감사', '기쁨', '찬양'],
        "description": '감사와 찬양, 기쁨과 즐거움, 하나님의 선하심',
        "curated_references": [
            "시편 100:4",
            "데살로니가전서 5:18",
            "시편 16:11",
            "빌립보서 4:4",
            "느헤미야 8:10",
        ],
    },
    {
        "tokens": ['용서', '죄책감', '회개'],
        "description": '용서와 회개, 새 마음, 은혜로 다시 시작함',
        "curated_references": [
            "요한일서 1:9",
            "누가복음 17:3-4",
            "에베소서 4:32",
            "시편 103:12",
            "미가 7:19",
        ],
    },
    {
        "tokens": ['사랑', '연애', '결혼', '부부', '가정', '부모', '자녀', '가족'],
        "description": '사랑과 연합, 가정과 관계 회복, 서로를 세워 줌',
        "curated_references": [
            "고린도전서 13:4-7",
            "요한일서 4:8",
            "에베소서 5:25",
            "잠언 17:17",
            "골로새서 3:13",
        ],
    },
    {
        "tokens": ['우정', '공동체', '교회', '형제'],
        "description": '공동체와 우정, 서로를 격려하고 세워 주는 관계',
        "curated_references": [
            "요한복음 15:13",
            "잠언 17:17",
            "잠언 27:17",
            "요한복음 17:21",
            "히브리서 10:24-25"
        ],
    },
    {
        "tokens": ['사명', '헌신', '섬김', '순종'],
        "description": '사명과 순종, 헌신과 사랑으로 섬기는 삶',
        "curated_references": [
            "요한복음 14:15",
            "로마서 12:1",
            "신명기 10:12",
            "마태복음 16:24",
            "갈라디아서 2:20"
        ],
    },
    {
        "tokens": ['건강', '질병', '치유', '회복'],
        "description": '치유와 회복, 강건함, 약한 자를 세우시는 하나님',
        "curated_references": [
            "야고보서 5:15",
            "출애굽기 15:26",
            "이사야 53:5",
            "마가복음 5:34",
            "시편 41:3"
        ],
    },
    {
        "tokens": ['재정', '돈', '필요', '궁핍', '가난'],
        "description": '필요를 채우시는 하나님, 공급과 만족, 나눔과 신뢰',
        "curated_references": [
            "빌립보서 4:19",
            "마태복음 6:33",
            "히브리서 13:5",
            "잠언 30:8",
            "마태복음 6:26",
        ],
    },
    {
        "tokens": ['갈등', '분노', '싸움'],
        "description": '화해와 용서, 평화, 사랑으로 문제를 해결함',
        "curated_references": [
            "야고보서 1:19-20",
            "잠언 15:1",
            "에베소서 4:26",
            "마태복음 18:15",
            "잠언 16:32"
        ],
    },
    {
        "tokens": ['평안', '쉼', '안식', '샬롬'],
        "description": '평안과 안식, 폭풍 가운데도 지키시는 하나님',
        "curated_references": [
            "요한복음 14:27",
            "마태복음 11:28",
            "시편 4:8",
            "빌립보서 4:7",
            "요한복음 16:33"
        ],
    },
]

BOOK_ABBREVIATIONS = {
    # 한글 약어
    "마": "마태복음", "막": "마가복음", "눅": "누가복음", "요": "요한복음",
    "롬": "로마서", "고전": "고린도전서", "고후": "고린도후서", "갈": "갈라디아서",
    "엡": "에베소서", "빌": "빌립보서", "골": "골로새서", "살전": "데살로니가전서",
    "살후": "데살로니가후서", "딤전": "디모데전서", "딤후": "디모데후서",
    "약": "야고보서", "벧전": "베드로전서", "벧후": "베드로후서",
    # 영문 약어(소문자)
    "mt": "마태복음", "matt": "마태복음", "mk": "마가복음", "lk": "누가복음",
    "jn": "요한복음", "rom": "로마서", "1th": "데살로니가전서", "2th": "데살로니가후서",
    "eph": "에베소서", "phil": "빌립보서", "jas": "야고보서",
}

KOREAN_TO_ENGLISH_BOOK = {v: k for k, v in BOOK_NAME_MAP.items()}
FULL_BOOK_TO_ABBREVIATIONS = {}
for abbr, full in BOOK_ABBREVIATIONS.items():
    if re.fullmatch(r"[가-힣0-9]+", abbr):
        FULL_BOOK_TO_ABBREVIATIONS.setdefault(full, []).append(abbr)

# 정규식 패턴
REFERENCE_SPLIT_PATTERN = re.compile(r'^(.*?)(\d+:\d.*)$')


REFERENCE_INPUT_PATTERN = re.compile(
    r'^\s*([0-9]{0,1}\s*[가-힣A-Za-z]{1,30})\s*([0-9]{1,3})\s*(?:[:장]\s*([0-9]{1,3}))\s*(?:[-–—~]\s*([0-9]{1,3}))?\s*(?:절)?\s*$'
)