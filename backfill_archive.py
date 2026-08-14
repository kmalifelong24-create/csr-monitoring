"""
아카이브 일괄 복구 (1회용)

index.html의 모든 git 리비전을 훑어서, 그동안 수집됐던 FINDINGS 항목을
전부 모아 중복 없이 ARCHIVE로 병합한다.

메인 피드 정원(60건)에 밀려 사라졌던 과거 항목들을 되살리는 용도.
GitHub Actions에서 수동 실행(workflow_dispatch)으로 한 번만 돌리면 된다.
"""

import subprocess
import json
import re
import sys

import update_dashboard as U   # 기존 스크립트의 함수 재사용


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout


def extract_findings(html):
    """HTML 문자열에서 FINDINGS 배열 추출"""
    m = re.search(r'// FINDINGS_START[\s\S]*?// FINDINGS_END', html)
    if not m:
        return []
    arr = re.search(r'const FINDINGS = (\[[\s\S]*?\]);', m.group(0))
    if not arr:
        return []
    try:
        return json.loads(arr.group(1))
    except Exception:
        return []


def extract_archive(html):
    m = re.search(r'// ARCHIVE_START[\s\S]*?// ARCHIVE_END', html)
    if not m:
        return []
    arr = re.search(r'const ARCHIVE = (\[[\s\S]*?\]);', m.group(0))
    if not arr:
        return []
    try:
        return json.loads(arr.group(1))
    except Exception:
        return []


def main():
    # ── 1. 커밋 목록 수집 ──────────────────────────────────────────
    shas = sh("git log --format=%H --follow -- index.html").split()
    if not shas:
        print("커밋 이력을 찾지 못했습니다. checkout 시 fetch-depth: 0 인지 확인하세요.")
        sys.exit(1)
    print(f"index.html 커밋 리비전: {len(shas)}개")

    # ── 2. 각 리비전에서 항목 수집 ─────────────────────────────────
    collected = {}   # id -> item
    for i, sha in enumerate(shas, 1):
        html = sh(f"git show {sha}:index.html")
        if not html:
            continue
        items = extract_findings(html)
        arch = extract_archive(html)
        for w in arch:
            items.extend(w.get('items', []))
        new_here = 0
        for it in items:
            iid = it.get('id')
            if not iid or iid in collected:
                continue
            collected[iid] = it
            new_here += 1
        if new_here:
            print(f"  [{i}/{len(shas)}] {sha[:7]} → 신규 {new_here}건 (누적 {len(collected)})")

    print(f"\n히스토리 전체에서 수집: {len(collected)}건")

    # ── 3. 현재 파일 상태 확인 ─────────────────────────────────────
    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    cur_findings = extract_findings(html)
    cur_archive = extract_archive(html)
    cur_ids = set(f.get('id') for f in cur_findings)
    already = sum(len(w.get('items', [])) for w in cur_archive)
    print(f"현재 피드: {len(cur_findings)}건 / 현재 아카이브: {already}건")

    # ── 4. 아카이브로 넣을 항목 선별 ───────────────────────────────
    #     (지금 메인 피드에 살아있는 건 제외 — 중복 표시 방지)
    to_archive = [U.enrich(it) for iid, it in collected.items() if iid not in cur_ids]
    print(f"아카이브 병합 대상: {len(to_archive)}건")

    new_archive = U.merge_into_archive(cur_archive, to_archive)
    total = sum(len(w['items']) for w in new_archive)
    print(f"→ 아카이브 결과: {len(new_archive)}주 / {total}건 (기존 {already}건에서 +{total - already})")

    # 주요 이슈 통계
    keys = [i for i in to_archive if i.get('isKey')]
    print(f"   그중 주요 이슈로 분류: {len(keys)}건")

    # ── 5. 현재 피드 항목도 타이밍·점수 필드 채우기 ────────────────
    cur_findings = [U.enrich(f) for f in cur_findings]

    # ── 6. 파일에 반영 ─────────────────────────────────────────────
    findings_block = (
        "// FINDINGS_START\n"
        f"// AUTO-UPDATED: (아카이브 복구 시 필드 갱신)\n"
        f"const FINDINGS = {json.dumps(cur_findings, ensure_ascii=False, indent=2)};\n"
        "// FINDINGS_END"
    )
    archive_block = (
        "// ARCHIVE_START\n"
        f"const ARCHIVE = {json.dumps(new_archive, ensure_ascii=False, indent=2)};\n"
        "// ARCHIVE_END"
    )

    # 기존 AUTO-UPDATED 표기는 살려둔다
    m = re.search(r'// AUTO-UPDATED: ([^\n]*)', html)
    if m:
        findings_block = findings_block.replace(
            "// AUTO-UPDATED: (아카이브 복구 시 필드 갱신)",
            f"// AUTO-UPDATED: {m.group(1)}"
        )

    html = re.sub(r'// FINDINGS_START[\s\S]*?// FINDINGS_END', lambda _: findings_block, html)
    html = re.sub(r'// ARCHIVE_START[\s\S]*?// ARCHIVE_END', lambda _: archive_block, html)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("\nindex.html 갱신 완료 ✓")


if __name__ == '__main__':
    main()
