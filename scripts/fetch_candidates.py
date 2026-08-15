"""Yahoo!ニュース検索結果から、エキスパートコメント候補になりそうな記事を集める。

ページに埋め込まれたNext.jsの初期状態(window.__PRELOADED_STATE__)を直接パースする。
(expert-news-feed/scripts/fetch_articles.py と同じ手法)
"""

from __future__ import annotations

import datetime
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
OUTPUT_PATH = BASE_DIR / "data" / "candidates.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
JST = datetime.timezone(datetime.timedelta(hours=9))
SEARCH_URL = "https://news.yahoo.co.jp/search?p={query}&ei=utf-8"
REQUEST_INTERVAL_SEC = 1.5  # Yahoo側への配慮


def fetch_html(keyword: str) -> str:
    url = SEARCH_URL.format(query=urllib.parse.quote(keyword))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read().decode("utf-8", errors="replace")


def extract_preloaded_state(html: str) -> dict:
    """`__PRELOADED_STATE__ = {...};` を波括弧の対応を数えて安全に取り出す。

    正規表現の非貪欲マッチだと文字列内の"};"で早期に打ち切られてしまうため。
    """
    marker = "__PRELOADED_STATE__"
    start = html.find(marker)
    if start == -1:
        raise ValueError("__PRELOADED_STATE__ が見つかりません（ページ構造が変わった可能性）")
    start = html.find("{", start)
    depth = 0
    in_str = False
    esc = False
    end = None
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("__PRELOADED_STATE__ の括弧が閉じていません")
    return json.loads(html[start:end])


def parse_publish_time(pub: dict, now_jst: datetime.datetime) -> str | None:
    """{"date": "8/11(火)", "time": "12:30"} をISO8601(JST)に変換する。

    年の表記が無いため、今日を基準に妥当な年を推定する
    (未来日にならないよう、必要なら前年扱いにする)。
    """
    date_s = (pub or {}).get("date", "")
    time_s = (pub or {}).get("time", "")
    if not date_s or not time_s:
        return None

    date_s = date_s.split("(")[0]  # 曜日を除去
    parts = date_s.split("/")
    try:
        if len(parts) == 3:
            year, month, day = (int(p) for p in parts)
        else:
            month, day = (int(p) for p in parts)
            year = now_jst.year
            candidate = datetime.datetime(year, month, day, tzinfo=JST)
            if candidate > now_jst + datetime.timedelta(days=1):
                year -= 1
        hour, minute = (int(p) for p in time_s.split(":"))
        dt = datetime.datetime(year, month, day, hour, minute, tzinfo=JST)
    except ValueError:
        return None
    return dt.isoformat()


def is_excluded(title: str, category: str, exclude_patterns: list[str], exclude_categories: list[str]) -> bool:
    """除外条件（タイトル中のNGワード / カテゴリ）に当てはまるか。"""
    if any(ng in title for ng in exclude_patterns):
        return True
    if category in exclude_categories:
        return True
    return False


def matching_keywords(title: str, keywords: list[str]) -> list[str]:
    """タイトルに含まれるキーワードを返す（空白区切りは全語を含む場合のみ該当）。"""
    return [kw for kw in keywords if all(w in title for w in kw.split())]


def load_previous(
    cutoff_iso: str,
    keywords: list[str],
    exclude_patterns: list[str],
    exclude_categories: list[str],
) -> dict[str, dict]:
    """前回までに収集した記事のうち、まだ収集期間内のものを読み込む。

    Yahoo!ニュース検索は1キーワードにつき最新60件しか返さず、ページ送りも
    埋め込みJSONには効かない。そのため「コンビニ」のような多ヒット語では
    1回の実行で数時間分しかさかのぼれない。毎回上書きすると実行間隔より
    短い範囲しか残らないため、過去の収集結果に積み増していく。

    引き継ぐ際は現在の設定（キーワード・除外条件）で判定し直す。そうしないと、
    設定を変更しても既に集めたノイズが収集期間いっぱい（最大168時間）残り続ける。
    """
    if not OUTPUT_PATH.exists():
        return {}
    try:
        prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    kept = {}
    for a in prev.get("articles", []):
        cid = a.get("content_id")
        if not cid or not a.get("published_at"):
            continue
        if a["published_at"] < cutoff_iso:
            continue

        title = a.get("title", "")
        if is_excluded(title, a.get("category", ""), exclude_patterns, exclude_categories):
            continue

        # 現在のキーワードで判定し直し、どれにも当てはまらなくなった記事は捨てる
        matched = matching_keywords(title, keywords)
        if not matched:
            continue
        a["matched_keywords"] = matched

        kept[cid] = a
    return kept


def search_keyword(
    keyword: str,
    exclude_patterns: list[str],
    exclude_categories: list[str],
    now_jst: datetime.datetime,
) -> list[dict]:
    html = fetch_html(keyword)
    state = extract_preloaded_state(html)
    contents = (state.get("search") or {}).get("contents") or []

    words = keyword.split()
    results = []
    for item in contents:
        headline = (item.get("highlightSearchText") or {}).get("headline", "")
        # Yahoo側のハイライト用制御文字(\x02, \x03など)が地の文に混入しているため除去。
        # 放置すると、複合キーワード判定がハイライト境界をまたぐ箇所で誤って不一致になる
        # (例:「コンビニ」がハイライトされた"コンビニ大手"が"コンビニ大手"に一致しない)
        headline = "".join(ch for ch in headline if ch >= " " or ch == "\t").strip()
        permalink = item.get("permalink", "")
        if not headline or not permalink:
            continue

        # Yahoo!ニュース エキスパートの記事（/expert/articles/...）は対象外。
        # 一般ニュースへの「コメント」候補を探すのが目的で、他エキスパートの
        # 実食レビューや自分の記事はコメント対象にならないため。
        if "/expert/articles/" in permalink:
            continue

        # 本文中のたまたまの一致（有名人ネタ、事件記事など）を除くため、
        # キーワードの構成語がすべてタイトルに含まれるものだけ採用する
        if not all(w in headline for w in words):
            continue

        categories = item.get("categories") or []
        category = categories[0]["name"] if categories else ""
        if is_excluded(headline, category, exclude_patterns, exclude_categories):
            continue

        published_at = parse_publish_time(item.get("publishTime"), now_jst)
        if not published_at:
            continue

        thumb = ((item.get("thumbnail") or {}).get("resizedImageUrl") or {}).get("jpeg") or (
            item.get("thumbnail") or {}
        ).get("url")

        results.append(
            {
                "content_id": item.get("contentId"),
                "title": headline,
                "url": permalink,
                "source": (item.get("media") or {}).get("name", ""),
                "category": category,
                "thumb": thumb,
                "published_at": published_at,
                "matched_keywords": [keyword],
            }
        )
    return results


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    keywords = config.get("keywords", [])
    exclude_patterns = config.get("exclude_patterns", [])
    exclude_categories = config.get("exclude_categories", [])
    hours_window = config.get("hours_window", 48)

    now_jst = datetime.datetime.now(tz=JST)
    cutoff_iso = (now_jst - datetime.timedelta(hours=hours_window)).isoformat()

    # 前回までの収集結果に積み増す（1回の実行では数時間分しか取れないため）
    articles: dict[str, dict] = load_previous(
        cutoff_iso, keywords, exclude_patterns, exclude_categories
    )
    carried_over = len(articles)
    errors: list[str] = []

    for i, kw in enumerate(keywords):
        try:
            items = search_keyword(kw, exclude_patterns, exclude_categories, now_jst)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            # TimeoutErrorはURLErrorの派生ではないため個別に捕捉する。
            # 1語の失敗で全体が落ちると、その回の収集結果がまるごと失われる。
            errors.append(f"{kw}: {e}")
            continue

        for it in items:
            if it["published_at"] < cutoff_iso:
                continue
            cid = it["content_id"]
            if not cid:
                continue
            if cid in articles:
                merged = articles[cid].setdefault("matched_keywords", [])
                if kw not in merged:
                    merged.append(kw)
            else:
                articles[cid] = it

        if i < len(keywords) - 1:
            time.sleep(REQUEST_INTERVAL_SEC)

    article_list = sorted(articles.values(), key=lambda a: a["published_at"], reverse=True)

    output = {
        "generated_at": now_jst.isoformat(),
        "hours_window": hours_window,
        "keywords": keywords,
        "errors": errors,
        "articles": article_list,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"{len(article_list)}件（前回から引き継ぎ {carried_over}件 / "
        f"今回の新規 {len(article_list) - carried_over}件、エラー{len(errors)}件） -> {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
