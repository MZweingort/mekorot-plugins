#!/usr/bin/env python3
"""Verify a citation against the Sefaria library before writing it into a footnote.

A source filled from memory is a guess until the words are seen on the page.
Three questions, three commands (standard library only):

  sefaria.py search "נגוף למצרים ורפוא לישראל" [--slop 0] [--size 8] [--in Zohar]
        where does this exact phrase appear? (--slop N allows N words in between;
        --in keeps only results whose reference contains the given text)
  sefaria.py text "Sanhedrin 111a" [--grep "ארך אפים"] [--max-chars 3000]
        read a reference; with --grep show only the lines around a word
        (matching ignores nikud and te'amim). Hebrew references work too:
        "סנהדרין קיא א", "משנה פסחים י ו", "רש\"י על פסחים ד א".
  sefaria.py zohar 'ח"א קכב, ב' [--grep "מאן דאיהו זעיר"] [--max-chars 3000]
        is the phrase on this daf of the Zohar? Sefaria cannot say: it addresses the
        Zohar by parasha and paragraph and rejects "Zohar 1:122b" (HTTP 400). The daf
        is read from Hebrew Wikisource, which has one page per amud. A miss looks at
        the two adjacent amudim as well, because Wikisource does not always break the
        page where the printed edition does.
  sefaria.py verse "קהלת א ב" [--words "הבל הבלים אמר קהלת"]
        the verse with nikud, as a verse quoted inside a footnote must be written
        (4 words or more): no te'amim, meteg or sof pasuq, maqaf as a space, the qere
        (not the ketiv), and the Name as הוי'. --words prints only that part of the
        verse (matched by its letters; ו/י and nikud in the request do not matter).
  sefaria.py ping

Sefaria answers scripted requests only when they carry a browser User-Agent
(a bare one gets HTTP 403), hence the header below.
"""
import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.sefaria.org"
WIKI = "https://he.wikisource.org/w/index.php?action=render&title="
UA =("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
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


NAME = re.compile(r"(?<![א-תְ-ּׁׂ])((?:[ובלכמשה][ְ-ּׁׂ]*)?)י[ְ-ּׁׂ]*ה[ְ-ּׁׂ]*ו[ְ-ּׁׂ]*ה[ְ-ּׁׂ]*(?![א-ת])")


def vocalized(raw):
    """Masorah text → the way a verse is quoted with nikud in Gal Einai texts."""
    t = re.sub(r'<span class="mam-kq-k">.*?</span>', "", raw)        # ketiv out, qere stays
    t = html.unescape(TAGS.sub("", t))
    t = re.sub(r"\{[פס]\}", "", t).replace("[", "").replace("]", "")
    t = re.sub(r"[֑-ֽ֯׀׃ׅׄ׆]", "", t)          # te'amim, meteg, paseq, sof pasuq, dots
    t = t.replace("־", " ").replace("ׇ", "ָ")     # maqaf → space, qamats qatan → qamats
    t = NAME.sub(lambda m: m.group(1) + "הוי'", t)
    return re.sub(r"\s+", " ", t).strip()


def skeleton(word):
    """Letters only, without ו/י (full and defective spelling compare equal); the Name in any
    of its written forms (הוי' ה' ד' יהוה, with a prefix letter) compares equal too."""
    w = re.sub(r"[״\"׳’]", "'", plain(word))
    m = re.fullmatch(r"([ובלכמשה]?)(?:הוי'|ה'|ד'|יהוה|הויה)", re.sub(r"[^א-ת']", "", w))
    if m:
        return re.sub(r"[וי]", "", m.group(1)) + "הה"
    return re.sub(r"[^א-ת]|[וי]", "", w)


def cmd_verse(o):
    d = call("/api/v3/texts/" + urllib.parse.quote(o.ref) + "?version=hebrew")
    if d.get("error"):
        sys.exit(f"sefaria: {d['error']}")
    versions = d.get("versions") or []
    if not versions:
        sys.exit(f"sefaria: no Hebrew text for {o.ref}")
    raw = versions[0].get("text")
    text = vocalized(" ".join(flatten(raw).split("\n")))
    if not o.words:
        print(f"{d.get('heRef', o.ref)} | {text}")
        return
    words = text.split()
    want = [s for s in (skeleton(w) for w in re.split(r"[\s־]+", o.words)) if s]
    have = [skeleton(w) for w in words]
    for k in range(len(words) - len(want) + 1):
        if have[k:k + len(want)] == want:
            print(f"{d.get('heRef', o.ref)} | {' '.join(words[k:k + len(want)])}")
            return
    print(f"«{o.words}» לא נמצא כרצף ב-{d.get('heRef', o.ref)}:\n  {text}")
    sys.exit(1)


def zohar_title(ref):
    """«ח"א קכב, ב» / «זהר חלק א קכב ב» / «זח"ג קסח ע"א» → the Wikisource page title."""
    w = [x for x in re.sub(r"[\"'״׳]", "", ref).replace(",", " ").split()
         if x not in ("זהר", "זוהר", "חלק", "דף", "עמוד")]
    if len(w) == 3:
        vol, amud = re.sub(r"^ז?ח(?=.)", "", w[0]), re.sub(r"^ע(?=.)", "", w[2])
        if vol in ("א", "ב", "ג") and amud in ("א", "ב"):
            return f"זהר חלק {vol} {w[1]} {amud}"
    sys.exit(f"zohar: cannot read «{ref}» – write volume, daf, amud: 'ח\"א קכב, ב'")


def zohar_page(title):
    """One amud → ([(section, text)], previous title, next title); None if there is no such page.
    action=render is the page as displayed; action=raw returns only a transclusion stub."""
    req = urllib.request.Request(WIKI + urllib.parse.quote(title.replace(" ", "_")),
                                 headers={"user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            page = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        sys.exit(f"wikisource: HTTP {e.code} for {title}")
    except urllib.error.URLError as e:
        sys.exit(f"wikisource: cannot reach he.wikisource.org ({e.reason}) – no network in "
                 "this session; skip verification and mark the daf as unverified")

    def clean(s):
        s = html.unescape(TAGS.sub(" ", re.sub(r"(?s)<style.*?</style>", "", s)))
        s = re.sub(r"\s+", " ", MARKS.sub("", s)).strip()
        return re.sub(r"^מתוך:.{0,40}?\(\s*עריכה\s*\)\s*", "", s)

    def link(arrows):       # the «<<» and «>>» links in the page header
        m = re.search(r'title="([^"]+)">(?:%s)</a>' % arrows, page)
        return html.unescape(m.group(1)) if m else None

    # the header (links, a Hebrew translation on some pages) ends at the «דף קכב ב» heading;
    # after it the amud is one text, or <h2> sections: זהר / תוספתא / מדרש הנעלם / סתרי תורה
    body = re.split(r"<h3[^>]*>(?:\s*<[^>]+>)*דף [^<]*(?:<[^>]+>\s*)*</h3>", page, maxsplit=1)[-1]
    parts = re.split(r"(?s)<h2[^>]*>(.*?)</h2>", body)      # text, name, text, name, text…
    names = ["זהר"] + [clean(n) for n in parts[1::2]]
    sections = [(n, t) for n, t in zip(names, map(clean, parts[::2])) if t]
    return sections, link("&lt;&lt;|<<"), link("&gt;&gt;|>>")


def cmd_zohar(o):
    title = zohar_title(o.ref)
    page = zohar_page(title)
    if not page:
        sys.exit(f"wikisource: אין עמוד «{title}»")
    here, before, after = page
    if not o.grep:
        print(title)
        print("\n".join(f"== {name}\n{body}" for name, body in here)[:o.max_chars])
        return
    needle = loose(o.grep)

    def show(sections, where):
        for name, body in sections:
            text = loose(body)
            k = text.find(needle)
            if k >= 0:
                print(f"«{o.grep}» – {where} [{name}]")
                print("  …" + text[max(0, k - 160):k + len(needle) + 260] + "…")
                return True

    if show(here, f"נמצא בעמוד שצוין, {title}"):
        return
    near = {t: dict((zohar_page(t) or [[]])[0]) for t in (before, after) if t}
    drift = "חלוקת העמודים בוויקיטקסט אינה תמיד זו של הדפוס, ולכן זו לא הוכחה שההפניה שגויה"
    for t, sections in near.items():
        if show(sections.items(), f"לא ב{title} אלא בעמוד הסמוך, {t}"):
            print(f"  ({drift})")
            return
    seam = [(name, " ".join([near.get(before, {}).get(name, ""), body,
                             near.get(after, {}).get(name, "")])) for name, body in here]
    if show(seam, f"על התפר בין {title} לעמוד סמוך"):
        return
    print(f"  «{o.grep}» לא נמצא ב{title} ולא בשני העמודים הסמוכים")
    sys.exit(1)


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
    z = sub.add_parser("zohar")
    z.add_argument("ref")
    z.add_argument("--grep")
    z.add_argument("--max-chars", type=int, default=3000)
    v = sub.add_parser("verse")
    v.add_argument("ref")
    v.add_argument("--words")
    sub.add_parser("ping")
    o = p.parse_args()
    if o.cmd == "ping":
        d = call("/api/v3/texts/" + urllib.parse.quote("Genesis 1:1") + "?version=hebrew")
        print("ok:", d.get("heRef"))
    elif o.cmd == "search":
        cmd_search(o)
    elif o.cmd == "zohar":
        cmd_zohar(o)
    elif o.cmd == "verse":
        cmd_verse(o)
    else:
        cmd_text(o)


if __name__ == "__main__":
    main()
