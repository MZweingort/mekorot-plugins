#!/usr/bin/env python3
"""
footnotes_tool.py – כלי למילוי הערות שוליים ב-docx במעקב שינויים.

שימוש:
  python footnotes_tool.py list  in.docx [--all]
      מדפיס את ההערות הריקות / המכילות ??? (או את כולן עם --all), ולכל אחת את
      קטע הטקסט בגוף המסמך שאליו היא מפנה (כדי לדעת מה צריך מקור).

  python footnotes_tool.py apply in.docx fills.json out.docx [--author Claude]
      מחיל את המילויים מ-fills.json במעקב שינויים (w:ins / w:del) ומוסיף
      comments להערות מסומנות כלא-ודאיות.

מבנה fills.json (UTF-8):
{
  "fill":    {"92": "זהר ח\"ב קכא, א.", "98": "שמות לג, כג."},
  "replace": [{"id": 106, "old": "(???)", "new": "(בראשית ב, ד)"}],
  "replace_runs": [{"id": 101, "first": "ראה ???", "last": "???", "new": "כמו ..."}],
  "comments": [{"id": 93, "text": "מקור לא ודאי – ..."}]
}
- fill: הערה ריקה ← מוסיף את הטקסט בסוף ההערה.
- replace: מחליף מחרוזת שנמצאת בתוך run אחד (מחיקה + הוספה במעקב).
- replace_runs: מוחק את כל ה-runs מהראשון שמכיל first עד האחרון שמכיל last, ומוסיף new.
- comments: מוסיף comment שמעוגן על סימן ההערה בגוף המסמך (לא בתוך ההערה – LibreOffice נשבר מזה).
"""
import sys, re, os, json, html, zipfile, shutil, datetime, tempfile, argparse
from xml.sax.saxutils import escape

RUN = re.compile(r'<w:r\b[^>]*>.*?</w:r>', re.S)


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
        self.date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        ids = [int(x) for x in re.findall(r'<w:(?:ins|del)\b[^>]*w:id="(\d+)"', doc.fn + doc.doc)]
        self._id = max(ids + [9000])

    def nid(self):
        self._id += 1
        return self._id

    RPR = '<w:rPr><w:rFonts w:hint="cs"/><w:rtl/></w:rPr>'

    def ins_run(self, text, rpr=None):
        return ('<w:ins w:id="%d" w:author="%s" w:date="%s"><w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:ins>'
                % (self.nid(), escape(self.author), self.date, rpr if rpr is not None else self.RPR, escape(text)))

    def del_run(self, run_xml):
        r = re.sub(r'<w:t(?: [^>]*)?>', '<w:delText xml:space="preserve">', run_xml).replace('</w:t>', '</w:delText>')
        return '<w:del w:id="%d" w:author="%s" w:date="%s">%s</w:del>' % (self.nid(), escape(self.author), self.date, r)

    def fill_empty(self, i, text):
        body = self.d.fn_match(i).group(2)
        k = body.rfind('</w:p>')
        self.d.set_fn(i, body[:k] + self.ins_run(text) + body[k:])

    def replace_in_run(self, i, old, new):
        body = self.d.fn_match(i).group(2)
        ms = [m for m in RUN.finditer(body) if old in run_text(m.group(0))]
        if len(ms) != 1:
            raise SystemExit('footnote %d: "%s" found in %d runs (need exactly 1; use replace_runs)' % (i, old, len(ms)))
        m = ms[0]
        r = m.group(0)
        rpr = re.search(r'<w:rPr>.*?</w:rPr>', r, re.S)
        rpr = rpr.group(0) if rpr else ''
        ropen = re.match(r'<w:r\b[^>]*>', r).group(0)
        a, b = run_text(r).split(old, 1)

        def mk(s):
            return '%s%s<w:t xml:space="preserve">%s</w:t></w:r>' % (ropen, rpr, escape(s))
        out = (mk(a) if a else '') + self.del_run(mk(old)) + self.ins_run(new, rpr) + (mk(b) if b else '')
        self.d.set_fn(i, body[:m.start()] + out + body[m.end():])

    def replace_runs(self, i, first, last, new):
        body = self.d.fn_match(i).group(2)
        runs = list(RUN.finditer(body))
        idx = [k for k, m in enumerate(runs) if first in run_text(m.group(0)) or last in run_text(m.group(0))]
        if not idx:
            raise SystemExit('footnote %d: markers not found' % i)
        s, e = idx[0], idx[-1]
        seg = body[runs[s].start():runs[e].end()]
        out = ''.join(self.del_run(m.group(0)) for m in RUN.finditer(seg))
        rpr = re.search(r'<w:rPr>.*?</w:rPr>', runs[s].group(0), re.S)
        out += self.ins_run(new, rpr.group(0) if rpr else None)
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


def cmd_list(args):
    d = Doc(args.docx)
    for i, body in d.footnotes():
        if i < 1:
            continue
        t = ''.join(html.unescape(x) for x in re.findall(r'<w:t[^>]*>([^<]*)</w:t>', body)).strip()
        if args.all or not t or '???' in t:
            tag = 'EMPTY' if not t else ('???' if '???' in t else 'ok')
            print('--- [%d] %s' % (i, tag))
        if not args.all and (not t or '???' in t):
            print('   הערה: %s' % (t[:300] or '(ריקה)'))
            print('   בגוף: %s' % d.context(i))
        elif args.all:
            print('   הערה: %s' % t[:200])
    shutil.rmtree(d.tmp)


def cmd_apply(args):
    d = Doc(args.docx)
    spec = json.load(open(args.fills, encoding='utf8'))
    e = Editor(d, args.author)
    for k, v in (spec.get('fill') or {}).items():
        e.fill_empty(int(k), v)
    for it in spec.get('replace') or []:
        e.replace_in_run(int(it['id']), it['old'], it['new'])
    for it in spec.get('replace_runs') or []:
        e.replace_runs(int(it['id']), it['first'], it['last'], it['new'])
    e.add_comments(spec.get('comments') or [])
    d.save(args.out)
    print('written', args.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('list'); a.add_argument('docx'); a.add_argument('--all', action='store_true')
    b = sub.add_parser('apply'); b.add_argument('docx'); b.add_argument('fills'); b.add_argument('out'); b.add_argument('--author', default='Claude')
    args = ap.parse_args()
    {'list': cmd_list, 'apply': cmd_apply}[args.cmd](args)


if __name__ == '__main__':
    main()
