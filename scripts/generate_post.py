#!/usr/bin/env python3
"""Generate one new weekly blog post using the Gemini API and wire it into
blog/posts.json + sitemap.xml. Designed to run inside GitHub Actions.

Env vars:
  GEMINI_API_KEY  - required, Google AI Studio key
  GEMINI_MODEL    - optional, defaults to gemini-2.5-flash
  POST_DATE       - optional override (YYYY-MM-DD), defaults to today (UTC)
"""

import html
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOG_DIR = os.path.join(ROOT, "blog")
POSTS_JSON = os.path.join(BLOG_DIR, "posts.json")
SITEMAP = os.path.join(ROOT, "sitemap.xml")

SITE_URL = "https://annual-leave-calculator.pages.dev"
CATEGORIES = ["제도 이해", "특수 고용형태", "휴직/복직", "퇴사/정산", "갈등 대응", "실사용 후기"]

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def load_posts():
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def build_prompt(posts):
    existing = "\n".join(
        f"- [{p['category']}] {p['title']} (slug: {p['slug']})" for p in posts
    )
    return f"""당신은 15년 차 인사팀장으로, 회사 블로그에 매주 연차휴가 관련 글을 올립니다.
연차를 딱딱한 노무 이슈가 아니라, 직장인이 마땅히 누려야 할 유쾌한 권리로 다루는
따뜻하고 현실감 있는 글쓰기 스타일을 유지하세요. 실제 사례처럼 생생한 에피소드로
시작해서, 정확한 법적 근거(근로기준법 제60조 등)를 자연스럽게 풀어주고, 실용적인
조언으로 마무리하는 구조를 씁니다.

이미 발행된 글 목록 (절대 같은 주제나 슬러그를 반복하지 마세요):
{existing}

사용 가능한 카테고리: {', '.join(CATEGORIES)}

위 목록에 없는, 완전히 새로운 각도의 주제로 글 1편을 작성하세요. 최근 한국 노동
시장에서 실제로 화제가 될 법한 상황(예: 특정 업종, 특정 생애주기, 특정 제도 변화)을
다뤄도 좋습니다.

다음 JSON 스키마로만 응답하세요 (마크다운 코드블록 없이 순수 JSON):
{{
  "title": "기존 글들과 비슷한 톤의 제목. 대사 인용구+설명 조합 형태 권장",
  "slug": "영문 소문자 kebab-case, 3~6단어, 기존 슬러그와 중복 금지",
  "category": "위 카테고리 중 하나를 정확히 그대로",
  "summary": "40~70자 한글 한 문장 요약",
  "alt_text": "히어로 이미지에 어울리는 15자 내외 한글 대체 텍스트",
  "sections": [
    {{"heading": "소제목1", "paragraphs": ["문단1", "문단2"]}},
    {{"heading": "소제목2", "paragraphs": ["문단1", "문단2"]}},
    {{"heading": "소제목3(선택)", "paragraphs": ["문단1"]}}
  ]
}}

전체 본문은 700~1100자 분량의 한글로 작성하고, 각 문단은 3~6문장으로 구성하세요.
paragraphs 안의 텍스트는 순수 문장으로만 작성하고 마크다운 문법(**, #, - 등)은 절대 쓰지 마세요."""


def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.9,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini API error {e.code}: {e.read().decode('utf-8')}")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response shape: {data}") from e

    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def slugify_fallback(title, used_slugs):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "post"
    slug = base
    n = 2
    while slug in used_slugs:
        slug = f"{base}-{n}"
        n += 1
    return slug


def pick_image(posts):
    # posts is newest-first. For each image, record the smallest index it
    # appears at (its most recent use). Pick the image whose most recent
    # use is furthest back, so it never collides with the post right above it.
    last_used_index = {}
    for idx, p in enumerate(posts):
        img = p["image"]
        if img not in last_used_index:
            last_used_index[img] = idx
    if not last_used_index:
        return "https://images.pexels.com/photos/5408818/pexels-photo-5408818.jpeg?auto=compress&cs=tinysrgb&w=1200"
    return max(last_used_index, key=last_used_index.get)


def format_inline(text):
    parts = re.split(r"\*\*(.+?)\*\*", text)
    out = []
    for i, part in enumerate(parts):
        escaped = html.escape(part, quote=True)
        out.append(f"<strong>{escaped}</strong>" if i % 2 == 1 else escaped)
    return "".join(out)


def render_html(post, date_str):
    e = lambda s: html.escape(s, quote=True)
    title = post["title"]
    summary = post["summary"]
    slug = post["slug"]
    category = post["category"]
    image = post["image"]
    canonical = f"{SITE_URL}/blog/{slug}.html"

    sections_html = ""
    for sec in post["sections"]:
        paras = "\n".join(f"      <p>\n        {format_inline(p)}\n      </p>" for p in sec["paragraphs"])
        sections_html += f"      <h2>{e(sec['heading'])}</h2>\n{paras}\n"

    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": title,
            "description": summary,
            "image": image,
            "datePublished": date_str,
            "dateModified": date_str,
            "author": {"@type": "Person", "name": "직장인 연차 계산기 운영자 (15년차 인사팀장)"},
            "publisher": {"@type": "Organization", "name": "직장인 연차 계산기"},
            "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        },
        ensure_ascii=False,
        indent=2,
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-5Q4HXM8Q4M"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-5Q4HXM8Q4M');
</script>
<script>try{{var t=localStorage.getItem("theme");if(t)document.documentElement.setAttribute("data-theme",t);}}catch(e){{}}</script>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 100 100%27%3E%3Ctext y=%27.9em%27 font-size=%2790%27%3E%F0%9F%97%93%EF%B8%8F%3C/text%3E%3C/svg%3E" />
<title>{e(title)} | 연차 이야기</title>
<meta name="description" content="{e(summary)}" />
<link rel="canonical" href="{canonical}" />
<meta property="og:title" content="{e(title)}" />
<meta property="og:description" content="{e(summary)}" />
<meta property="og:type" content="article" />
<meta property="og:url" content="{canonical}" />
<meta property="og:image" content="{e(image)}" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{e(title)}" />
<meta name="twitter:description" content="{e(summary)}" />
<meta name="twitter:image" content="{e(image)}" />
<link rel="stylesheet" href="/style.css" />
<script type="application/ld+json">
{json_ld}
</script>
</head>
<body>
  <header class="site-header">
    <div class="inner">
      <a class="brand" href="/">직장인 연차 계산기</a>
      <nav class="site-nav">
        <a href="/">연차 계산기</a>
        <a href="/guide.html">연차휴가 가이드</a>
        <a href="/blog/" class="active">연차 이야기</a>
        <a href="/about.html">소개</a>
        <a href="/contact.html">문의</a>
      </nav>
      <button id="themeToggle" class="theme-toggle" aria-label="테마 전환"></button>
    </div>
  </header>

  <main>
    <h1 class="page-title">{e(title)}</h1>
    <span class="post-category-badge">{e(category)}</span>
    <p class="page-lead">{date_str.replace('-', '.')}</p>
    <img src="{e(image)}" alt="{e(post['alt_text'])}" style="width:100%; border-radius:0.75rem; margin-bottom:1.5rem;" loading="lazy" />

    <article>
{sections_html}    </article>
    <p><a href="/blog/">&larr; 연차 이야기 목록으로</a></p>
  </main>

  <footer class="site-footer">
    <nav>
      <a href="/about.html">소개</a>
      <a href="/privacy.html">개인정보처리방침</a>
      <a href="/terms.html">이용약관</a>
      <a href="/contact.html">문의</a>
    </nav>
    <p>&copy; 2026 직장인 연차 계산기. 본 사이트의 계산 결과는 참고용이며 법적 효력이 없습니다.</p>
  </footer>
<script src="/theme.js"></script>
</body>
</html>
"""


def update_posts_json(posts, entry):
    posts.insert(0, entry)
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
        f.write("\n")


def update_sitemap(slug, date_str):
    with open(SITEMAP, "r", encoding="utf-8") as f:
        content = f.read()

    new_url = (
        f'  <url><loc>{SITE_URL}/blog/{slug}.html</loc>'
        f'<lastmod>{date_str}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>\n'
    )

    blog_index_pattern = re.compile(
        r'(  <url><loc>' + re.escape(f"{SITE_URL}/blog/") + r'</loc><lastmod>)\d{4}-\d{2}-\d{2}(</lastmod>[^\n]*\n)'
    )
    content, n = blog_index_pattern.subn(rf"\g<1>{date_str}\g<2>", content, count=1)
    if n == 0:
        raise RuntimeError("Could not find blog index <url> entry in sitemap.xml")

    marker = f'{SITE_URL}/blog/</loc>'
    idx = content.index(marker)
    line_end = content.index("\n", idx) + 1
    content = content[:line_end] + new_url + content[line_end:]

    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    posts = load_posts()
    existing_slugs = {p["slug"] for p in posts}

    prompt = build_prompt(posts)
    generated = call_gemini(prompt)

    slug = generated.get("slug", "")
    slug = re.sub(r"[^a-z0-9-]", "", slug.lower())
    if not slug or slug in existing_slugs:
        slug = slugify_fallback(generated.get("title", "post"), existing_slugs)

    category = generated.get("category", "").strip()
    if category not in CATEGORIES:
        category = CATEGORIES[0]

    date_str = os.environ.get("POST_DATE") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    image = pick_image(posts)

    post = {
        "title": generated["title"],
        "slug": slug,
        "category": category,
        "summary": generated["summary"],
        "alt_text": generated.get("alt_text", category),
        "sections": generated["sections"],
        "image": image,
    }

    html_out = render_html(post, date_str)
    out_path = os.path.join(BLOG_DIR, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    update_posts_json(
        posts,
        {
            "slug": slug,
            "title": post["title"],
            "summary": post["summary"],
            "date": date_str,
            "category": category,
            "image": image,
        },
    )
    update_sitemap(slug, date_str)

    print(f"Generated: {slug} ({category}) - {post['title']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
