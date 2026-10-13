#!/usr/bin/env python3
"""Verify a citation against the Sefaria library before writing it into a footnote.

A source filled from memory is a guess until the words are seen on the page.
Two questions, two commands (standard library only):

  sefaria.py search "נגוף למצרים ורפוא לישראל" [--slop 0] [--size 8] [--in Zohar]
        where does this exact phrase appear? (--slop N allows N words in between;
        --in keeps only results whose reference contains the given text)
  sefaria.py text "Sanhedrin 111a" [--grep "ארך אפים"] [--max-chars 3000]
        read a reference; with --grep show only the lines around a word
        (matching ignores nikud and te'amim). Hebrew references work too:
        "סנהדרין קיא א", "משנה פסחים י ו", "רש\"י על פסחים ד א".
  sefaria.py ping

Sefaria answers scripted requests only when they carry a browser User-Agent
(a bare one gets HTTP 403), hence the header below.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.sefaria.org"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MARKS = re.compile(r"[֑-ׇ]")          # nikud + te'amim
TAGS = re.compile(r"<[^>]+>")
PUNCT = re.compile(r"[\"'״׳“”‘’.,:;!?()\[\]{}־–—\-]+")


def call(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"user-agent": UA, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"sefaria: HTTP {e.code} for {path}")
    except urllib.error.URLError as e:
        sys.exit(f"sefaria: cannot reach {BASE} ({e.reason}) – no network in this "
                 "session; skip verification and mark the source as unverified")


def plain(s):
    return MARKS.sub("", TAGS.sub("", s))


def loose(s):
    """For matching only: no nikud, no punctuation or quote marks, single spaces.
    The printed Talmud writes ״ארך אפים״ ראה – a search for «ארך אפים ראה» must still find it."""
    return re.sub(r"\s+", " ", PUNCT.sub(" ", plain(s))).strip()


def flatten(x):
    if isinstance(x, list):
        return "\n".join(flatten(i) for i in x if i)
    return str(x or "")


def cmd_search(o):
    d = call("/api/search-wrapper", {"query": o.query, "type": "text", "size": o.size * 4,
                                     "field": "naive_lemmatizer", "slop": o.slop})
    hits = d.get("hits", {})
    print(f"«{o.query}» – {hits.get('total', 0)} מופעים")
    seen, shown = set(), 0
    for h in hits.get("hits", []):
        ref = re.sub(r" \([^()]*\[[a-z]+\]\)$", "", h.get("_id", ""))   # drop the edition suffix
        if ref in seen or (o.within and o.within.lower() not in ref.lower()):
            continue
        seen.add(ref)
        snippet = plain(" … ".join(sum(h.get("highlight", {}).values(), [])))
        print(f"  {ref}\n      {snippet[:260]}")
        shown += 1
        if shown >= o.size:
            break
    if not shown:
        print("  (אין תוצאות – לנסות ניסוח קצר יותר, --slop 2, או בלי --in)")


def cmd_text(o):
    d = call("/api/v3/texts/" + urllib.parse.quote(o.ref) + "?version=hebrew")
    if d.get("error"):
        sys.exit(f"sefaria: {d['error']}")
    versions = d.get("versions") or []
    if not versions:
        sys.exit(f"sefaria: no Hebrew text for {o.ref}")
    text = plain(flatten(versions[0].get("text")))
    print(f"{d.get('heRef', o.ref)}  [{d.get('ref', '')}]  – {len(text)} תווים")
    if o.grep:
        needle, text = loose(o.grep), loose(text)
        found = [m.start() for m in re.finditer(re.escape(needle), text)]
        if not found:
            print(f"  «{o.grep}» לא נמצא בהפניה הזו")
            sys.exit(1)
        for k in found[:6]:
            a, b = max(0, k - 160), min(len(text), k + len(needle) + 260)
            print("  …" + text[a:b].replace("\n", " ") + "…")
    else:
        print(text[:o.max_chars])


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--slop", type=int, default=0)
    s.add_argument("--size", type=int, default=8)
    s.add_argument("--in", dest="within")
    t = sub.add_parser("text")
    t.add_argument("ref")
    t.add_argument("--grep")
    t.add_argument("--max-chars", type=int, default=3000)
    sub.add_parser("ping")
    o = p.parse_args()
    if o.cmd == "ping":
        d = call("/api/v3/texts/" + urllib.parse.quote("Genesis 1:1") + "?version=hebrew")
        print("ok:", d.get("heRef"))
    elif o.cmd == "search":
        cmd_search(o)
    else:
        cmd_text(o)


if __name__ == "__main__":
    main()
