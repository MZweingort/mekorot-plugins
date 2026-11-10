#!/usr/bin/env python3
"""
footnotes_tool.py – כלי למילוי הערות שוליים ב-docx במעקב שינויים.

שימוש:
  python footnotes_tool.py list  in.docx [--all]
      מדפיס את ההערות הריקות / המכילות ?? או ??? (או את כולן עם --all), ולכל אחת את
      קטע הטקסט בגוף המסמך שאליו היא מפנה (כדי לדעת מה צריך מקור).

  python footnotes_tool.py dump  in.docx [--out dump.txt]
      כל המסמך כטקסט: פסקאות הגוף עם סימני [^N] במקום ההערות, ואחריהן כל ההערות.
      תחליף ל-pandoc (שאינו מותקן בכל מחשב) – לקריאת ההקשר המלא ולחיפוש (grep).

  python footnotes_tool.py verify out.docx [--original in.docx] [--fills fills.json]
      בודק את קובץ הפלט בלי כלים חיצוניים: שלמות ה-zip וה-XML, מעקב השינויים,
      שמספר ההערות לא השתנה, ושכל המילויים, הצבע הכחול וה-comments נכנסו.
      עם --original (ו---fills) בודק גם שגוף המסמך זהה למקור, ושדחיית כל השינויים
      (Reject All) מחזירה כל הערה לנוסח המקורי – חוץ מהמילויים שהוכנסו בכוונה בלי
      מעקב (fill_untracked / "tracked": false), שאותם הוא מצפה למצוא כלשונם.

  python footnotes_tool.py apply in.docx fills.json out.docx [--author Claude]
      מחיל את המילויים מ-fills.json – במעקב שינויים (w:ins / w:del) או בלעדיו –
      ומוסיף comments להערות מסומנות כלא-ודאיות.

מבנה fills.json (UTF-8):
{
  "fill_untracked": {"98": "שמות לג, כג."},
  "fill":    {"92": "ראה {{סוד ה' ליראיו}} ש\"ח. ובכ\"מ."},
  "replace": [{"id": 106, "old": "(???)", "new": "(בראשית ב, ד)", "tracked": false}],
  "replace_runs": [{"id": 101, "first": "ראה ???", "last": "???", "new": "כמו ..."}],
  "comments": [{"id": 93, "text": "מקור לא ודאי – ..."}]
}
- fill_untracked: הערה ריקה ← מוסיף את הטקסט בסוף ההערה, בלי מעקב שינויים
  (מקור ודאי ופשוט: פסוק, מאמר חז"ל מובהק שאומת, ערך מקובץ הערכים כלשונו).
- fill: הערה ריקה ← מוסיף את הטקסט בסוף ההערה, במעקב שינויים (כל מה שעין אנושית צריכה לאשר).
- replace: מחליף מחרוזת שנמצאת בתוך run אחד (מחיקה + הוספה במעקב; עם "tracked": false – בלי מעקב).
  אם המחרוזת מופיעה בכמה runs (למשל שני `???` באותה הערה) – "nth": 1/2/... בוחר את המופע (בסדר ההערה).
- replace_runs: מוחק את כל ה-runs מהראשון שמכיל first עד האחרון שמכיל last, ומוסיף new
  (גם כאן "tracked": false אפשרי).
- {{...}} בתוך טקסט של מילוי = שם ספר של הרב: נכתב בכחול (00B0F0), בלי הסוגריים.
- comments: מוסיף comment שמעוגן על סימן ההערה בגוף המסמך (לא בתוך ההערה – LibreOffice נשבר מזה).
"""
import sys, re, os, json, html, zipfile, shutil, datetime, tempfile, argparse
from xml.sax.saxutils import escape

RUN = re.compile(r'<w:r\b[^>]*>.*?</w:r>', re.S)

# Names of the Rav's books are written in this blue (the editor's own colour).
BLUE = '00B0F0'
MARKUP = re.compile(r'\{\{(.+?)\}\}')
# CT_RPr children that come after <w:color> – a colour must be inserted before them.
AFTER_COLOR = ('spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight', 'u', 'effect', 'bdr',
               'shd', 'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang', 'eastAsianLayout',
               'specVanish', 'oMath')
BOOKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references', 'sifrei-harav.md')


def segments(text):
    """'ראה {{סוד ה' ליראיו}} ש"ח.' → [('ראה ', False), ("סוד ה' ליראיו", True), (' ש"ח.', False)]"""
    out, pos = [], 0
    for m in MARKUP.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def unmark(text):
    return MARKUP.sub(r'\1', text)


def with_color(rpr, color=BLUE):
    if not rpr:
        return '<w:rPr><w:color w:val="%s"/></w:rPr>' % color
    if '<w:color ' in rpr:
        return re.sub(r'<w:color [^>]*/>', '<w:color w:val="%s"/>' % color, rpr)
    m = re.search(r'<w:(?:%s)[\s/>]' % '|'.join(AFTER_COLOR), rpr)
    k = m.start() if m else rpr.rfind('</w:rPr>')
    return rpr[:k] + '<w:color w:val="%s"/>' % color + rpr[k:]


def book_titles():
    """The Rav's books (references/sifrei-harav.md, lines '- title')."""
    try:
        lines = open(BOOKS_FILE, encoding='utf8').read().splitlines()
    except OSError:
        return []
    return [l[2:].strip() for l in lines if l.startswith('- ') and l[2:].strip()]


def norm_q(s):
    return s.replace('״', '"').replace('׳', "'").replace('’', "'")


def run_text(r):
    return html.unescape(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', r)))


def para_text(p):
    return html.unescape(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p)))


class Doc:
    def __init__(self, path):
        self.tmp = tempfile.mkdtemp()
        with zipfile.ZipFile(path) as z:
            z.extractall(self.tmp)
        self.fn_path = os.path.join(self.tmp, 'word', 'footnotes.xml')
        self.doc_path = os.path.join(self.tmp, 'word', 'document.xml')
        self.fn = open(self.fn_path, encoding='utf8').read()
        self.doc = open(self.doc_path, encoding='utf8').read()

    # ---------- footnotes
    def footnotes(self):
        for m in re.finditer(r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>', self.fn, re.S):
            yield int(m.group(1)), m.group(2)

    def fn_match(self, i):
        m = re.search(r'(<w:footnote\b[^>]*w:id="%d"[^>]*>)(.*?)(</w:footnote>)' % i, self.fn, re.S)
        if not m:
            raise SystemExit('footnote id %d not found' % i)
        return m

    def set_fn(self, i, body):
        m = self.fn_match(i)
        self.fn = self.fn[:m.start(2)] + body + self.fn[m.end(2):]

    # ---------- context in body
    def context(self, i, chars=220):
        m = re.search(r'<w:footnoteReference w:id="%d"/>' % i, self.doc)
        if not m:
            return ''
        pstart = self.doc.rfind('<w:p ', 0, m.start())
        pstart2 = self.doc.rfind('<w:p>', 0, m.start())
        pstart = max(pstart, pstart2)
        before = para_text(self.doc[pstart:m.start()])
        pend = self.doc.find('</w:p>', m.end())
        after = para_text(self.doc[m.end():pend])
        return before[-chars:] + ' [*] ' + after[:60]

    def save(self, out):
        open(self.fn_path, 'w', encoding='utf8').write(self.fn)
        open(self.doc_path, 'w', encoding='utf8').write(self.doc)
        if os.path.exists(out):
            os.remove(out)
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            ct = os.path.join(self.tmp, '[Content_Types].xml')
            z.write(ct, '[Content_Types].xml')
            for root, dirs, files in os.walk(self.tmp):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, self.tmp)
                    if rel == '[Content_Types].xml':
                        continue
                    z.write(full, rel)
        shutil.rmtree(self.tmp)


class Editor:
    def __init__(self, doc, author):
        self.d = doc
        self.author = author
        self.date = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ids = [int(x) for x in re.findall(r'<w:(?:ins|del)\b[^>]*w:id="(\d+)"', doc.fn + doc.doc)]
        self._id = max(ids + [9000])

    def nid(self):
        self._id += 1
        return self._id

    RPR = '<w:rPr><w:rFonts w:hint="cs"/><w:rtl/></w:rPr>'

    def runs(self, text, rpr=None):
        """Plain runs for text; {{...}} segments (the Rav's book names) in blue."""
        rpr = rpr if rpr is not None else self.RPR
        return ''.join('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (with_color(rpr) if blue else rpr, escape(s))
                       for s, blue in segments(text))

    def ins_run(self, text, rpr=None):
        return ('<w:ins w:id="%d" w:author="%s" w:date="%s">%s</w:ins>'
                % (self.nid(), escape(self.author), self.date, self.runs(text, rpr)))

    def new_runs(self, text, rpr=None, tracked=True):
        return self.ins_run(text, rpr) if tracked else self.runs(text, rpr)

    def del_run(self, run_xml):
        r = re.sub(r'<w:t(?: [^>]*)?>', '<w:delText xml:space="preserve">', run_xml).replace('</w:t>', '</w:delText>')
        return '<w:del w:id="%d" w:author="%s" w:date="%s">%s</w:del>' % (self.nid(), escape(self.author), self.date, r)

    def fill_empty(self, i, text, tracked=True):
        body = self.d.fn_match(i).group(2)
        k = body.rfind('</w:p>')
        self.d.set_fn(i, body[:k] + self.new_runs(text, tracked=tracked) + body[k:])

    def replace_in_run(self, i, old, new, nth=None, tracked=True):
        body = self.d.fn_match(i).group(2)
        ms = [m for m in RUN.finditer(body) if old in run_text(m.group(0))]
        if nth:
            if not 1 <= nth <= len(ms):
                raise SystemExit('footnote %d: "%s" found in %d runs, no match #%d' % (i, old, len(ms), nth))
            ms = [ms[nth - 1]]
        if len(ms) != 1:
            raise SystemExit('footnote %d: "%s" found in %d runs (need exactly 1; pass "nth" or use replace_runs)' % (i, old, len(ms)))
        m = ms[0]
        r = m.group(0)
        rpr = re.search(r'<w:rPr>.*?</w:rPr>', r, re.S)
        rpr = rpr.group(0) if rpr else ''
        ropen = re.match(r'<w:r\b[^>]*>', r).group(0)
        a, b = run_text(r).split(old, 1)

        def mk(s):
            return '%s%s<w:t xml:space="preserve">%s</w:t></w:r>' % (ropen, rpr, escape(s))
        gone = self.del_run(mk(old)) if tracked else ''
        out = (mk(a) if a else '') + gone + self.new_runs(new, rpr, tracked) + (mk(b) if b else '')
        self.d.set_fn(i, body[:m.start()] + out + body[m.end():])

    def replace_runs(self, i, first, last, new, tracked=True):
        body = self.d.fn_match(i).group(2)
        runs = list(RUN.finditer(body))
        idx = [k for k, m in enumerate(runs) if first in run_text(m.group(0)) or last in run_text(m.group(0))]
        if not idx:
            raise SystemExit('footnote %d: markers not found' % i)
        s, e = idx[0], idx[-1]
        seg = body[runs[s].start():runs[e].end()]
        out = ''.join(self.del_run(m.group(0)) for m in RUN.finditer(seg)) if tracked else ''
        rpr = re.search(r'<w:rPr>.*?</w:rPr>', runs[s].group(0), re.S)
        out += self.new_runs(new, rpr.group(0) if rpr else None, tracked)
        self.d.set_fn(i, body[:runs[s].start()] + out + body[runs[e].end():])

    # ---------- comments (anchored on the footnote reference in the body)
    def add_comments(self, items):
        if not items:
            return
        tmp = self.d.tmp
        cpath = os.path.join(tmp, 'word', 'comments.xml')
        styles = open(os.path.join(tmp, 'word', 'styles.xml'), encoding='utf8').read()
        st = re.search(r'w:styleId="([^"]+)"><w:name w:val="annotation reference"', styles)
        rstyle = '<w:rPr><w:rStyle w:val="%s"/></w:rPr>' % st.group(1) if st else ''
        W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        if os.path.exists(cpath):
            cx = open(cpath, encoding='utf8').read()
            existing = [int(x) for x in re.findall(r'<w:comment\b[^>]*w:id="(\d+)"', cx)]
            cid = max(existing + [-1]) + 1
        else:
            cx = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:comments xmlns:w="%s"></w:comments>' % W
            cid = 0
            # rels + content types
            rp = os.path.join(tmp, 'word', '_rels', 'document.xml.rels')
            rels = open(rp, encoding='utf8').read()
            n = 1
            while 'Id="rIdCmt%d"' % n in rels:
                n += 1
            rels = rels.replace('</Relationships>',
                                '<Relationship Id="rIdCmt%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/></Relationships>' % n)
            open(rp, 'w', encoding='utf8').write(rels)
            ctp = os.path.join(tmp, '[Content_Types].xml')
            ct = open(ctp, encoding='utf8').read()
            if 'comments.xml' not in ct:
                ct = ct.replace('</Types>', '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/></Types>')
                open(ctp, 'w', encoding='utf8').write(ct)
        for it in items:
            fid, text = int(it['id']), it['text']
            m = re.search(r'<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:footnoteReference w:id="%d"/></w:r>' % fid, self.d.doc, re.S)
            if not m:
                print('warning: footnote reference %d not found in body; comment skipped' % fid)
                continue
            self.d.doc = (self.d.doc[:m.start()] + '<w:commentRangeStart w:id="%d"/>' % cid + m.group(0)
                          + '<w:commentRangeEnd w:id="%d"/><w:r>%s<w:commentReference w:id="%d"/></w:r>' % (cid, rstyle, cid)
                          + self.d.doc[m.end():])
            cx = cx.replace('</w:comments>',
                            '<w:comment w:id="%d" w:author="%s" w:date="%s" w:initials="%s"><w:p><w:pPr><w:bidi/></w:pPr><w:r><w:rPr><w:rtl/></w:rPr><w:annotationRef/></w:r><w:r><w:rPr><w:rtl/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p></w:comment></w:comments>'
                            % (cid, escape(self.author), self.date, escape(self.author[:2]), escape(text)))
            cid += 1
        open(cpath, 'w', encoding='utf8').write(cx)


DEL = re.compile(r'<w:del\b.*?</w:del>', re.S)
INS = re.compile(r'<w:ins\b.*?</w:ins>', re.S)


def live_text(xml):
    """הטקסט כפי שהוא נראה אחרי קבלת כל השינויים (בלי מה שנמחק במעקב)."""
    return para_text(DEL.sub('', xml))


def original_text(xml):
    """הטקסט כפי שהוא נראה אחרי דחיית כל השינויים: בלי ההוספות, עם המחיקות."""
    return para_text(INS.sub('', xml).replace('w:delText', 'w:t'))


def cmd_list(args):
    d = Doc(args.docx)
    total = empty = marked = 0
    for i, body in d.footnotes():
        if i < 1:
            continue
        t = live_text(body).strip()
        # editors mark a missing source with ?? or ??? (also inside a longer note: "הערה??", "פרק??")
        need = not t or '??' in t
        total += 1
        empty += not t
        marked += bool(t) and '??' in t
        if args.all or need:
            tag = 'EMPTY' if not t else ('??' if '??' in t else 'ok')
            print('--- [%d] %s' % (i, tag))
        if not args.all and need:
            print('   הערה: %s' % (t[:300] or '(ריקה)'))
            print('   בגוף: %s' % d.context(i))
        elif args.all:
            print('   הערה: %s' % t[:200])
    print('=== למילוי: %d מתוך %d הערות (%d ריקות, %d עם ??)' % (empty + marked, total, empty, marked))
    shutil.rmtree(d.tmp)


def cmd_dump(args):
    d = Doc(args.docx)
    lines = []
    for m in re.finditer(r'<w:p\b[^>]*>.*?</w:p>', d.doc, re.S):
        p = re.sub(r'<w:footnoteReference w:id="(\d+)"/>', lambda r: '<w:t>[^%s]</w:t>' % r.group(1), m.group(0))
        t = live_text(p)
        if t.strip():
            lines.append(t)
    lines.append('')
    lines.append('===== הערות שוליים =====')
    for i, body in d.footnotes():
        if i >= 1:
            lines.append('[^%d]: %s' % (i, live_text(body).strip()))
    shutil.rmtree(d.tmp)
    out = '\n'.join(lines) + '\n'
    if args.out:
        open(args.out, 'w', encoding='utf8').write(out)
        print('written %s (%d שורות, %d תווים)' % (args.out, len(lines), len(out)))
    else:
        sys.stdout.write(out)


def cmd_apply(args):
    d = Doc(args.docx)
    spec = json.load(open(args.fills, encoding='utf8'))
    both = set(spec.get('fill') or {}) & set(spec.get('fill_untracked') or {})
    if both:
        raise SystemExit('footnote(s) %s appear in both "fill" and "fill_untracked" – choose one' % ', '.join(sorted(both)))
    e = Editor(d, args.author)
    for k, v in (spec.get('fill_untracked') or {}).items():
        e.fill_empty(int(k), v, tracked=False)
    for k, v in (spec.get('fill') or {}).items():
        e.fill_empty(int(k), v)
    for it in spec.get('replace') or []:
        e.replace_in_run(int(it['id']), it['old'], it['new'], it.get('nth'), it.get('tracked', True))
    for it in spec.get('replace_runs') or []:
        e.replace_runs(int(it['id']), it['first'], it['last'], it['new'], it.get('tracked', True))
    e.add_comments(spec.get('comments') or [])
    d.save(args.out)
    n_plain = len(spec.get('fill_untracked') or {}) + sum(1 for it in (spec.get('replace') or []) + (spec.get('replace_runs') or [])
                                                           if it.get('tracked', True) is False)
    print('written %s (%d without tracked changes)' % (args.out, n_plain))


def expected_after_reject(before, spec):
    """What each footnote should read after Reject All: the original, plus whatever was put in
    on purpose without tracking (fill_untracked, replace with "tracked": false)."""
    exp = dict(before)
    for k, v in (spec.get('fill_untracked') or {}).items():
        exp[str(k)] = exp.get(str(k), '') + unmark(v)
    for it in spec.get('replace') or []:
        if it.get('tracked', True) is False:
            k, t = str(it['id']), exp.get(str(it['id']), '')
            n, pos = it.get('nth') or 1, -1
            for _ in range(n):
                pos = t.find(it['old'], pos + 1)
            if pos >= 0:
                exp[k] = t[:pos] + unmark(it['new']) + t[pos + len(it['old']):]
    for it in spec.get('replace_runs') or []:
        if it.get('tracked', True) is False:
            # whole runs from `first` to `last` were swapped: the text is known only up to run
            # boundaries, so accept the note as it now reads if it holds the new text
            # and kept what came before `first` and after `last`.
            k, t = str(it['id']), exp.get(str(it['id']), '')
            a, b = t.find(it['first']), t.rfind(it['last'])
            if a >= 0 and b >= 0:
                exp[k] = ('runs', t[:a], unmark(it['new']), t[b + len(it['last']):])
    return exp


def matches(expected, actual):
    if isinstance(expected, tuple):          # untracked replace_runs, see above
        _, head, new, tail = expected
        actual = actual or ''
        k = actual.find(new)
        # the deleted runs may have held text before `first` / after `last`
        return k >= 0 and head.startswith(actual[:k]) and tail.endswith(actual[k + len(new):])
    return expected == actual


def quoted_spans(text):
    """Quotations inside a note («"..."»), skipping the gershayim of abbreviations (ח"ב, ע"פ)."""
    t = re.sub(r'(?<=[א-ת])["״](?=[א-ת])', '\x00', unmark(text))
    return [s.replace('\x00', '"') for s in re.findall(r'["“”״]([^"“”״]+)["“”״]', t)]



def cmd_verify(args):
    """בדיקה טהורה ב-python (בלי LibreOffice): שלמות הקובץ, מעקב השינויים, וההערות שמולאו."""
    import xml.etree.ElementTree as ET
    ok = True
    with zipfile.ZipFile(args.docx) as z:
        bad = z.testzip()
        if bad:
            print('FAIL  קובץ ה-zip פגום:', bad); return
        names = z.namelist()
        for n in names:
            if n.endswith('.xml') or n.endswith('.rels'):
                try:
                    ET.fromstring(z.read(n))
                except Exception as e:
                    print('FAIL  XML לא תקין ב-%s: %s' % (n, e)); ok = False
        fn = z.read('word/footnotes.xml').decode('utf8')
        doc = z.read('word/document.xml').decode('utf8')
        comments = z.read('word/comments.xml').decode('utf8') if 'word/comments.xml' in names else ''
    print('OK    מבנה הקובץ ו-XML תקינים' if ok else 'שגיאות מבנה למעלה')
    spec = json.load(open(args.fills, encoding='utf8')) if args.fills else {}
    edits = (spec.get('replace') or []) + (spec.get('replace_runs') or [])
    want_tracked = len(spec.get('fill') or {}) + sum(1 for it in edits if it.get('tracked', True) is not False)
    want_plain = len(spec.get('fill_untracked') or {}) + sum(1 for it in edits if it.get('tracked', True) is False)

    ins = re.findall(r'<w:ins\b[^>]*w:author="([^"]*)"', fn + doc)
    dele = re.findall(r'<w:del\b[^>]*w:author="([^"]*)"', fn + doc)
    print('OK    הוספות במעקב שינויים: %d, מחיקות: %d (מחברים: %s)%s'
          % (len(ins), len(dele), ', '.join(sorted(set(ins + dele))) or '-',
             '; בלי מעקב (מקורות ודאיים): %d' % want_plain if args.fills else ''))
    if (want_tracked if args.fills else True) and not ins:
        print('FAIL  אין אף הוספה במעקב שינויים'); ok = False

    total_fn = len(re.findall(r'<w:footnote\b[^>]*w:id="(?!(?:-1|0)")', fn))
    print('OK    הערות שוליים בקובץ: %d' % total_fn)

    if args.original:
        with zipfile.ZipFile(args.original) as z:
            ofn = z.read('word/footnotes.xml').decode('utf8')
            odoc = z.read('word/document.xml').decode('utf8')
        o = len(re.findall(r'<w:footnote\b[^>]*w:id="(?!(?:-1|0)")', ofn))
        if o != total_fn:
            print('FAIL  מספר ההערות השתנה: %d ← %d' % (o, total_fn)); ok = False
        else:
            print('OK    מספר ההערות לא השתנה (%d)' % o)
        if original_text(doc) != original_text(odoc):
            print('FAIL  טקסט גוף המסמך שונה מהמקור'); ok = False
        else:
            print('OK    גוף המסמך זהה למקור')
        FN = r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>'
        before = {m.group(1): original_text(m.group(2)) for m in re.finditer(FN, ofn, re.S)}
        after = {m.group(1): original_text(m.group(2)) for m in re.finditer(FN, fn, re.S)}
        expect = expected_after_reject(before, spec)
        moved = sorted((k for k in before if not matches(expect[k], after.get(k))), key=int)
        if moved:
            print('FAIL  הערות שהשתנו מחוץ למעקב השינויים בלי שהוגדרו כך ב-fills (fill_untracked / "tracked": false): %s%s'
                  % (', '.join(moved), '' if args.fills else ' – להריץ עם --fills')); ok = False
        else:
            print('OK    דחיית כל השינויים מחזירה כל הערה לנוסח המקורי%s'
                  % (' (חוץ מ-%d מילויים ודאיים שהוכנסו בלי מעקב)' % want_plain if want_plain else ''))

    if args.fills:
        plain = html.unescape(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', fn)))
        missing = []
        texts = [('fill %s' % k, v) for k, v in (spec.get('fill_untracked') or {}).items()]
        texts += [('fill %s' % k, v) for k, v in (spec.get('fill') or {}).items()]
        texts += [('replace %s' % it['id'], it['new']) for it in edits]
        for name, v in texts:
            if unmark(v)[:40] not in plain:
                missing.append(name)
        if missing:
            print('FAIL  טקסט שלא נמצא בקובץ הפלט: %s' % ', '.join(missing)); ok = False
        else:
            print('OK    כל המילויים מופיעים בקובץ')

        # the Rav's books in blue
        blue_runs = [run_text(m.group(0)) for m in RUN.finditer(fn) if 'w:val="%s"' % BLUE in m.group(0)]
        marked = [s for _, v in texts for s, b in segments(v) if b]
        not_blue = [s for s in marked if not any(s in r for r in blue_runs)]
        if not_blue:
            print('FAIL  שם ספר שסומן {{ }} ולא נצבע בכחול: %s' % '; '.join(not_blue)); ok = False
        elif marked:
            print('OK    שמות ספרי הרב בכחול: %d' % len(marked))
        titles = book_titles()
        loose = []
        for name, v in texts:
            rest = norm_q(''.join(s for s, b in segments(v) if not b))
            for t in titles:
                if norm_q(t) in rest:
                    loose.append('%s – "%s"' % (name, t))
        if loose:
            print('WARN  שם ספר של הרב בלי {{ }} (צריך להיות בכחול): %s' % '; '.join(loose))

        # a verse quoted inside a note: 4+ words → with nikud
        bare = []
        for name, v in texts:
            for q in quoted_spans(v):
                words = re.findall(r'[א-ת][א-ת֑-ׇ\'"]*', q)
                if len(words) >= 4 and not re.search(r'[ְ-ּׁׂ]', q):
                    bare.append('%s – "%s"' % (name, q[:40]))
        if bare:
            print('WARN  ציטוט של 4 מלים ומעלה בלי ניקוד – אם זה פסוק, לנקד (sefaria.py verse): %s' % '; '.join(bare))
        want = [int(c['id']) for c in (spec.get('comments') or [])]
        got = len(re.findall(r'<w:comment\b[^>]*w:id="\d+"', comments))
        anchors = len(re.findall(r'<w:commentReference w:id="\d+"/>', doc))
        if want:
            if got >= len(want) and anchors >= len(want):
                print('OK    הערות (comments): %d, מעוגנות בגוף המסמך: %d' % (got, anchors))
            else:
                print('FAIL  ציפינו ל-%d comments; נמצאו %d, מעוגנות %d' % (len(want), got, anchors)); ok = False

    still = [m.group(1) for m in re.finditer(r'<w:footnote\b[^>]*w:id="(\d+)"[^>]*>(.*?)</w:footnote>', fn, re.S)
             if int(m.group(1)) >= 1 and (not live_text(m.group(2)).strip() or '??' in live_text(m.group(2)))]
    print('INFO  נשארו פתוחות (ריקות / ??): %d%s' % (len(still), (' – ' + ', '.join(still)) if still else ''))

    print('\n' + ('הקובץ תקין ומוכן למסירה.' if ok else 'נמצאו בעיות – לא למסור לפני תיקון.'))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('list'); a.add_argument('docx'); a.add_argument('--all', action='store_true')
    b = sub.add_parser('apply'); b.add_argument('docx'); b.add_argument('fills'); b.add_argument('out'); b.add_argument('--author', default='Claude')
    c = sub.add_parser('verify'); c.add_argument('docx'); c.add_argument('--original'); c.add_argument('--fills')
    e = sub.add_parser('dump'); e.add_argument('docx'); e.add_argument('--out')
    args = ap.parse_args()
    {'list': cmd_list, 'apply': cmd_apply, 'verify': cmd_verify, 'dump': cmd_dump}[args.cmd](args)


if __name__ == '__main__':
    main()
