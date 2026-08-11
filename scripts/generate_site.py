"""data/candidates.json から docs/index.html を生成する。"""

from __future__ import annotations

import datetime
import json
import pathlib
from html import escape as esc

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
DATA_PATH = BASE_DIR / "data" / "candidates.json"
DOCS_DIR = BASE_DIR / "docs"


def format_dt(iso_str: str) -> str:
    dt = datetime.datetime.fromisoformat(iso_str)
    return dt.strftime("%m/%d %H:%M")


def render_card(a: dict) -> str:
    thumb_html = (
        f'<img class="thumb" src="{esc(a["thumb"])}" alt="" loading="lazy">'
        if a.get("thumb")
        else '<div class="thumb thumb-empty"></div>'
    )
    kw_badges = "".join(
        f'<span class="badge">{esc(kw)}</span>' for kw in a.get("matched_keywords", [])
    )
    return f"""<a class="card" href="{esc(a["url"])}" target="_blank" rel="noopener">
  {thumb_html}
  <div class="card-body">
    <div class="meta">
      <span class="source">{esc(a.get("source", ""))}</span>
      <span class="category">{esc(a.get("category", ""))}</span>
      <span class="time">{format_dt(a["published_at"])}</span>
    </div>
    <div class="title">{esc(a["title"])}</div>
    <div class="badges">{kw_badges}</div>
  </div>
</a>"""


def render_html(config: dict, data: dict) -> str:
    articles = data.get("articles", [])
    generated_at = data.get("generated_at", "")
    try:
        generated_label = datetime.datetime.fromisoformat(generated_at).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        generated_label = generated_at

    cards_html = "\n".join(render_card(a) for a in articles)
    keywords_label = " / ".join(config.get("keywords", []))
    errors = data.get("errors") or []
    error_html = ""
    if errors:
        items = "".join(f"<li>{esc(e)}</li>" for e in errors)
        error_html = f'<details class="errors"><summary>取得エラー ({len(errors)}件)</summary><ul>{items}</ul></details>'

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(config.get("site_title", "コメント候補ファインダー"))}</title>
<meta name="description" content="{esc(config.get("site_description", ""))}">
<meta name="robots" content="noindex, nofollow">
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f7f7f8;
    --card-bg: #fff;
    --text: #1a1a1a;
    --muted: #6b6b6b;
    --border: #e5e5e5;
    --accent: #0f766e;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #16171a;
      --card-bg: #1f2023;
      --text: #eaeaea;
      --muted: #9a9a9a;
      --border: #303136;
      --accent: #2dd4bf;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
    background: var(--bg);
    color: var(--text);
  }}
  header {{
    max-width: 720px;
    margin: 0 auto;
    padding: 24px 16px 8px;
  }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .desc {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 12px; }}
  .keywords {{ font-size: 0.75rem; color: var(--muted); line-height: 1.7; margin: 0 0 4px; }}
  .updated {{ font-size: 0.75rem; color: var(--muted); margin: 8px 0 0; }}
  .errors {{ font-size: 0.75rem; color: var(--muted); margin-top: 8px; }}
  main {{
    max-width: 720px;
    margin: 0 auto;
    padding: 8px 16px 40px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .empty {{ color: var(--muted); font-size: 0.9rem; padding: 24px 0; text-align: center; }}
  .card {{
    display: flex;
    gap: 12px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px;
    text-decoration: none;
    color: inherit;
  }}
  .card:hover {{ border-color: var(--accent); }}
  .thumb {{
    width: 88px;
    height: 88px;
    border-radius: 8px;
    object-fit: cover;
    flex-shrink: 0;
    background: var(--border);
  }}
  .card-body {{ min-width: 0; }}
  .meta {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.75rem;
    color: var(--muted);
    margin-bottom: 4px;
    flex-wrap: wrap;
  }}
  .source {{ font-weight: 600; color: var(--accent); }}
  .title {{
    font-size: 0.95rem;
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 6px;
  }}
  .badges {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .badge {{
    font-size: 0.65rem;
    border: 1px solid var(--muted);
    color: var(--muted);
    border-radius: 4px;
    padding: 1px 5px;
  }}
  footer {{
    max-width: 720px;
    margin: 0 auto;
    padding: 16px;
    color: var(--muted);
    font-size: 0.75rem;
  }}
</style>
</head>
<body>
<header>
  <h1>{esc(config.get("site_title", "コメント候補ファインダー"))}</h1>
  <p class="desc">{esc(config.get("site_description", ""))}</p>
  <p class="keywords">検索キーワード: {esc(keywords_label)}</p>
  <p class="updated">最終更新: {esc(generated_label)}（直近{data.get("hours_window", "?")}時間・{len(articles)}件）</p>
  {error_html}
</header>
<main>
{cards_html if articles else '<p class="empty">該当する記事が見つかりませんでした</p>'}
</main>
<footer>
  Yahoo!ニュース検索結果を自動収集しています。実際にコメント可能かは各記事でご確認ください。
</footer>
</body>
</html>
"""


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / ".nojekyll").touch()
    (DOCS_DIR / "index.html").write_text(render_html(config, data), encoding="utf-8")
    print(f"生成しました -> {DOCS_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
