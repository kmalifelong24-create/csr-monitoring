"""
CSR 공고 모니터링 — 자동 업데이트 스크립트
매일 GitHub Actions로 실행되어 뉴스를 수집하고 index.html을 갱신합니다.

[아카이브 정책]
- 메인 피드(FINDINGS)는 최대 MAX_FEED건 유지
- 아카이브로 넘어가는 경우 두 가지:
  (1) 게시일이 ARCHIVE_AFTER_DAYS일 지난 항목
  (2) 메인 피드 정원(MAX_FEED)에서 밀려난 항목  ← 이전 버전에서 누락되어 유실되던 부분
- 아카이브는 주간 단위로 그룹화, 최대 ARCHIVE_WEEKS주 보관
"""

import feedparser
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
import hashlib
import time

# ── 설정 ────────────────────────────────────────────────────────────────
MAX_FEED = 60            # 메인 피드 최대 건수
ARCHIVE_AFTER_DAYS = 7   # 며칠 지나면 아카이브로 보낼지
ARCHIVE_WEEKS = 26       # 아카이브 보관 주 수 (약 6개월)
KST = timezone(timedelta(hours=9))

# ── 모니터링 대상 기업 ──────────────────────────────────────────────────
COMPANIES = [
    {"name": "국민은행", "priority": "high"},
    {"name": "우리은행", "priority": "high"},
    {"name": "현대자동차그룹", "priority": "high"},
    {"name": "KT그룹희망나눔재단", "priority": "high"},
    {"name": "CJ나눔재단", "priority": "high"},
    {"name": "신한희망재단", "priority": "high"},
    {"name": "교보교육재단", "priority": "high"},
    {"name": "하나금융그룹", "priority": "high"},
    {"name": "IBK행복나눔재단", "priority": "high"},
    {"name": "iM사회공헌재단", "priority": "high"},
    {"name": "NH농협은행", "priority": "high"},
    {"name": "신용카드사회공헌재단", "priority": "high"},
    {"name": "KRX국민행복재단", "priority": "high"},
    {"name": "롯데장학재단", "priority": "high"},
    {"name": "미래에셋박현주재단", "priority": "high"},
    {"name": "CJ올리브네트웍스", "priority": "high"},
    {"name": "롯데이노베이트", "priority": "high"},
    {"name": "HD현대1%나눔재단", "priority": "high"},
    {"name": "GS칼텍스", "priority": "high"},
    {"name": "LS그룹", "priority": "high"},
    {"name": "KT&G장학재단", "priority": "high"},
    {"name": "BNK금융그룹", "priority": "high"},
    {"name": "신협사회공헌재단", "priority": "high"},
    {"name": "새마을금고중앙회", "priority": "high"},
    {"name": "현대백화점사회복지재단", "priority": "high"},
    {"name": "이랜드재단", "priority": "high"},
    {"name": "삼성전자", "priority": "cond"},
    {"name": "LG전자", "priority": "cond"},
    {"name": "네이버 커넥트재단", "priority": "cond"},
    {"name": "카카오임팩트재단", "priority": "cond"},
    {"name": "넥슨재단", "priority": "cond"},
    {"name": "NC문화재단", "priority": "cond"},
    {"name": "스마일게이트 희망스튜디오", "priority": "cond"},
    {"name": "넷마블문화재단", "priority": "cond"},
    {"name": "한화그룹", "priority": "cond"},
    {"name": "SK행복나눔재단", "priority": "cond"},
    {"name": "포스코청암재단", "priority": "cond"},
    {"name": "아산나눔재단", "priority": "cond"},
    {"name": "현대차 정몽구 재단", "priority": "cond"},
    {"name": "BMW 코리아 미래재단", "priority": "cond"},
    {"name": "메르세데스-벤츠 사회공헌위원회", "priority": "cond"},
]

# ── 검색 키워드 ──────────────────────────────────────────────────────────
COMPANY_KEYWORDS = [
    "교육사업 운영기관 모집",
    "인재육성 사업 공모",
    "학습지원 수행기관 모집",
    "교육 위탁운영 공모",
    "역량강화 교육 협력기관",
    "멘토링 사업 운영기관 공모",
]

GENERAL_KEYWORDS = [
    "취약계층 교육사업 운영기관 모집 2026",
    "디지털교육 격차해소 수행기관 공모",
    "청소년 인재육성 교육 협력기관 모집",
    "AI 교육 취약계층 지원 사업 공모",
    "평생학습 위탁운영 기업재단 공모 2026",
    "교육격차 해소 사업 운영기관 모집",
]

# ── 관련성 필터 ───────────────────────────────────────────────────────────
INCLUDE_KEYWORDS = [
    '교육', '인재육성', '멘토링', '격차해소', '학습지원', '역량강화', '평생학습',
    '학습', '훈련', '코딩', 'AI교육', 'AI 교육', '디지털교육', '디지털 교육',
    '취약계층', '교육격차', '청소년 교육', '성인교육', '직업교육',
    '수행기관', '운영기관', '협력기관', '위탁운영', '교육사업', '장학',
    '인재 양성', '능력개발', '직무교육', '리터러시',
]

EXCLUDE_KEYWORDS = [
    '가전', '구독', '여행', '봉사단', '인턴', '채용', '취업', '입사지원',
    '구매', '할인', '이벤트', '경품', '추첨', '공연', '전시', '박람회',
    '주주', '투자', '주가', '실적', '매출', '영업이익', '배당',
    '결혼', '출산', '맛집', '레저', '관광', '스포츠 후원', '헬스케어',
    '봉사활동 모집', '자원봉사',
]

def is_relevant(title, summary):
    """교육/인재육성 관련 여부 판단"""
    text = title + ' ' + summary
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return False
    for kw in INCLUDE_KEYWORDS:
        if kw in text:
            return True
    return False

# ── 헬퍼: 주간 범위 ────────────────────────────────────────────────────
def get_week_range(date_str):
    """날짜의 주간 범위 반환 (월~일요일)"""
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        return f"{monday.strftime('%Y-%m-%d')} ~ {sunday.strftime('%Y-%m-%d')}"
    except Exception:
        return "날짜 미상"

# ── 헬퍼: HTML에서 JS 배열 추출 ───────────────────────────────────────
def extract_js_array(html, var_name, start_marker, end_marker):
    """HTML 마커 사이에서 const VAR = [...] 추출"""
    block = re.search(
        rf'{re.escape(start_marker)}[\s\S]*?{re.escape(end_marker)}', html
    )
    if not block:
        return []
    arr = re.search(rf'const {var_name} = (\[[\s\S]*?\]);', block.group(0))
    if arr:
        try:
            return json.loads(arr.group(1))
        except Exception:
            return []
    return []

# ── 뉴스 수집 ────────────────────────────────────────────────────────────
def fetch_google_news(query, days=30, max_results=5):
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
        cutoff = datetime.now() - timedelta(days=days)
        results = []
        for entry in feed.entries[:max_results]:
            try:
                pub = datetime(*entry.published_parsed[:6])
                if pub < cutoff:
                    continue
                title = re.sub(r'\s*-\s*[^-]+$', '', entry.title).strip()
                summary = re.sub('<[^>]+>', '', entry.get('summary', ''))[:250]
                results.append({
                    'title': title,
                    'url': entry.link,
                    'date': pub.strftime('%Y-%m-%d'),
                    'summary': summary,
                })
            except Exception:
                continue
        return results
    except Exception as e:
        print(f"  검색 오류 ({query[:30]}...): {e}")
        return []

# ── 분류 ────────────────────────────────────────────────────────────────
def classify_type(title, summary):
    text = title + ' ' + summary
    if any(w in text for w in ['입찰', '낙찰', '나라장터', '용역 공고']):
        return 'tender'
    if any(w in text for w in ['모집', '공모', '수행기관', '운영기관', '협력기관', '신청 접수', '참여기관']):
        return 'recruit'
    return 'news'

def classify_status(title, summary, date_str):
    text = title + ' ' + summary
    if any(w in text for w in ['종료', '마감됨', '선정 완료', '완료']):
        return 'closed'
    pub_date = datetime.strptime(date_str, '%Y-%m-%d')
    age_days = (datetime.now() - pub_date).days
    if age_days <= 14:
        return 'open'
    return 'closed'

# ── 추적 가이드 생성 ─────────────────────────────────────────────────────
def generate_track_note(company, type_, title, summary):
    text = title + ' ' + summary
    if type_ == 'tender':
        return "입찰 공고 확인. 나라장터 또는 재단 홈페이지에서 자격요건·마감일 즉시 확인 필요. KMA 입찰 참가 가능 여부 검토 후 신속 대응 요망."
    if type_ == 'recruit':
        if '연간' in text or '년도' in text or '2026' in text:
            return f"연간 사업 운영기관 모집 공고. 이 회차 마감 후 다음 모집은 약 10~12개월 후 예상. 현 수행기관 계약 종료 3~4개월 전 KMA 제안서 선제 발송 권장. {company} 담당자 컨텍 유지 필요."
        return f"{company} 모집 공고 확인. 마감일 체크 후 즉시 지원 검토. 이번 회차 마감 시 다음 공모 시점(통상 6~12개월 후) 캘린더 등록 권장."
    if '협약' in text or '파트너십' in text or '위탁' in text:
        return f"{company}가 외부 기관과 협약·위탁 계약 체결. 통상 1년 계약이므로 약 9~10개월 후 재계약 시점. 현 파트너 종료 전 KMA를 대안 파트너로 제안하는 타이밍 공략 필요."
    return f"{company} 사회공헌 관련 소식 수집. 사업 방향성 파악 및 협업 가능 접점 검토. 관련 담당자 컨텍 시 이 소식 활용 가능."

def generate_track_when(type_, status):
    if status == 'open':
        return "지금 즉시 — 현재 모집/공고 진행 중"
    if type_ == 'tender':
        return "즉시 확인 — 입찰 마감일 체크"
    if type_ == 'recruit':
        return "약 10~12개월 후 — 다음 사업연도 모집 시점"
    return "3~6개월 후 — 사업 기획 시점"

def make_id(company, title):
    return hashlib.md5(f"{company}{title}".encode()).hexdigest()[:8]

# ── 아카이브 병합 ────────────────────────────────────────────────────────
def merge_into_archive(existing_archive, items):
    """items를 주간 그룹으로 묶어 기존 아카이브에 병합(중복 제외)"""
    existing_ids = set()
    for week_entry in existing_archive:
        for it in week_entry.get('items', []):
            existing_ids.add(it.get('id', ''))

    week_groups = {}
    for item in items:
        iid = item.get('id')
        if not iid or iid in existing_ids:
            continue
        existing_ids.add(iid)  # 같은 배치 내 중복도 차단
        week = get_week_range(item.get('date', ''))
        week_groups.setdefault(week, []).append(item)

    new_archive = [dict(w, items=list(w.get('items', []))) for w in existing_archive]
    for week, group in week_groups.items():
        found = next((w for w in new_archive if w['week'] == week), None)
        if found:
            found['items'].extend(group)
        else:
            new_archive.append({'week': week, 'items': group})

    # 각 주 내부는 최신순 정렬
    for w in new_archive:
        w['items'].sort(key=lambda x: x.get('date', ''), reverse=True)

    new_archive.sort(key=lambda x: x['week'], reverse=True)
    return new_archive[:ARCHIVE_WEEKS]

# ── 메인 ────────────────────────────────────────────────────────────────
def run():
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')} KST] CSR 모니터링 시작")

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    old_findings = extract_js_array(html, 'FINDINGS', '// FINDINGS_START', '// FINDINGS_END')
    existing_archive = extract_js_array(html, 'ARCHIVE', '// ARCHIVE_START', '// ARCHIVE_END')
    print(f"기존 FINDINGS: {len(old_findings)}건, 아카이브: {len(existing_archive)}주")

    # ① 오래된 항목 분리
    cutoff = now.replace(tzinfo=None) - timedelta(days=ARCHIVE_AFTER_DAYS)
    aged_out = []
    current_findings = []
    for item in old_findings:
        try:
            fd = datetime.strptime(item['date'], '%Y-%m-%d')
            if fd < cutoff:
                aged_out.append(item)
            else:
                current_findings.append(item)
        except Exception:
            current_findings.append(item)
    print(f"기간 경과({ARCHIVE_AFTER_DAYS}일) 아카이브 대상: {len(aged_out)}건, 유지: {len(current_findings)}건")

    # ② 새 뉴스 수집
    seen_ids = set(f.get('id') for f in current_findings)
    new_findings = []

    def add_item(company, r):
        fid = make_id(company, r['title'])
        if fid in seen_ids:
            return
        seen_ids.add(fid)
        t = classify_type(r['title'], r['summary'])
        s = classify_status(r['title'], r['summary'], r['date'])
        new_findings.append({
            'id': fid, 'company': company,
            'type': t, 'status': s,
            'title': r['title'], 'summary': r['summary'],
            'date': r['date'], 'deadline': None, 'url': r['url'],
            'isNew': True,
            'trackNote': generate_track_note(company, t, r['title'], r['summary']),
            'trackWhen': generate_track_when(t, s),
        })

    # 우선순위 기업 개별 검색
    for company in [c for c in COMPANIES if c['priority'] == 'high']:
        for kw in COMPANY_KEYWORDS:
            query = f"{company['name']} {kw}"
            print(f"  검색: {query[:45]}")
            for r in fetch_google_news(query, days=45, max_results=3):
                if not is_relevant(r['title'], r['summary']):
                    continue
                add_item(company['name'], r)
            time.sleep(0.5)

    # 조건부 기업 통합 검색
    for company in [c for c in COMPANIES if c['priority'] == 'cond']:
        query = f"{company['name']} 교육사업 인재육성 모집 2026"
        for r in fetch_google_news(query, days=30, max_results=2):
            if not is_relevant(r['title'], r['summary']):
                continue
            add_item(company['name'], r)
        time.sleep(0.5)

    # 통합 키워드 검색
    company_names = [c['name'] for c in COMPANIES]
    for query in GENERAL_KEYWORDS:
        print(f"  통합 검색: {query[:45]}")
        for r in fetch_google_news(query, days=14, max_results=5):
            if not is_relevant(r['title'], r['summary']):
                continue
            matched = next((n for n in company_names if n.split('/')[0].strip() in r['title'] + r['summary']), None)
            if not matched:
                continue
            add_item(matched, r)
        time.sleep(0.5)

    # ③ 정렬 후 정원 적용 — 밀려난 항목도 아카이브로 보낸다 (핵심 수정)
    all_findings = current_findings + new_findings
    open_items = sorted([f for f in all_findings if f.get('status') == 'open'],
                        key=lambda x: x.get('date', ''), reverse=True)
    other_items = sorted([f for f in all_findings if f.get('status') != 'open'],
                         key=lambda x: x.get('date', ''), reverse=True)
    merged = open_items + other_items

    kept_findings = merged[:MAX_FEED]
    overflow = merged[MAX_FEED:]          # ← 이전에는 그냥 버려지던 항목들
    print(f"정원({MAX_FEED}) 초과로 아카이브 이동: {len(overflow)}건")

    # ④ 아카이브 병합 (기간 경과분 + 정원 초과분)
    new_archive = merge_into_archive(existing_archive, aged_out + overflow)
    archived_total = sum(len(w['items']) for w in new_archive)
    print(f"\n수집 완료: FINDINGS {len(kept_findings)}건, 아카이브 {archived_total}건 / {len(new_archive)}주")

    # ⑤ index.html 갱신
    findings_json = json.dumps(kept_findings, ensure_ascii=False, indent=2)
    new_findings_block = (
        f"// FINDINGS_START\n"
        f"// AUTO-UPDATED: {now.strftime('%Y-%m-%d %H:%M')} KST\n"
        f"const FINDINGS = {findings_json};\n"
        f"// FINDINGS_END"
    )

    archive_json = json.dumps(new_archive, ensure_ascii=False, indent=2)
    new_archive_block = (
        f"// ARCHIVE_START\n"
        f"const ARCHIVE = {archive_json};\n"
        f"// ARCHIVE_END"
    )

    html = re.sub(r'// FINDINGS_START[\s\S]*?// FINDINGS_END', lambda m: new_findings_block, html)
    html = re.sub(r'// ARCHIVE_START[\s\S]*?// ARCHIVE_END', lambda m: new_archive_block, html)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("index.html 업데이트 완료 ✓")

if __name__ == '__main__':
    run()
