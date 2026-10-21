#!/usr/bin/env python3
"""Call the Gal Einai archive MCP server directly over HTTP.

Fallback for sessions where no archive connector is connected: the server
is stateless JSON-RPC, so a plain POST of `tools/call` works without any MCP
client. Standard library only.

  archive.py search "דבר הוי' מירושלם" [--scope footnotes|titles|headings]
                    [--tree lessons|books|audio] [--year 5777] [--limit 10] [--full]
  archive.py doc <doc_id> [--section "..."] [--max-chars 6000]
  archive.py ask "שאלה" --keywords "מלה מלה"
  archive.py years [filter]
  archive.py ping

The endpoint is https://galeinai-mcp.vercel.app/api/mcp. https://galeinai.org.il/mcp/
is the site's "connect to AI" page for people (HTML), and it prints the
endpoint's address – so when an address answers HTML, the address is read off
that page and tried instead. If the endpoint ever moves, the page carries the
new address and this script follows it. GALEINAI_MCP_URL overrides both.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://galeinai-mcp.vercel.app/api/mcp"
PAGE = "https://galeinai.org.il/mcp/"
UA = "mekorot-shiur-plugin"


def _post(url, body):
    req = urllib.request.Request(url, data=body, headers={
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "user-agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.headers.get("content-type", ""), r.read().decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        return e.headers.get("content-type", ""), e.read().decode("utf8", "replace")


def _decode(ctype, text):
    """The JSON-RPC message, or None when the answer is not one (an HTML page)."""
    if "event-stream" in ctype:
        text = "\n".join(l[5:].strip() for l in text.splitlines() if l.startswith("data:"))
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and ("result" in data or "error" in data) else None


def _addresses_on(url):
    """MCP addresses printed on a page – the site's /mcp/ page hands out the endpoint."""
    try:
        req = urllib.request.Request(url, headers={"user-agent": UA, "accept": "text/html"})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode("utf8", "replace")
    except (urllib.error.URLError, ValueError):
        return []
    return list(dict.fromkeys(re.findall(r'https://[^\s"\'<>]+/mcp/?(?=[\s"\'<>]|$)', page)))


def rpc(method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}}).encode()
    todo = [u for u in (os.environ.get("GALEINAI_MCP_URL"), ENDPOINT, PAGE) if u]
    tried, why = [], []
    while todo:
        url = todo.pop(0)
        if url in tried:
            continue
        tried.append(url)
        try:
            ctype, text = _post(url, body)
        except urllib.error.URLError as e:
            why.append(f"{url}: cannot reach ({e.reason})")
            continue
        data = _decode(ctype, text)
        if data is None:
            # not the endpoint (most likely the page for people) – take the address it gives
            why.append(f"{url}: answered {ctype or 'something'} instead of JSON-RPC")
            todo += [u for u in _addresses_on(url) if u not in tried]
            continue
        if "error" in data:
            sys.exit(f"archive: {data['error'].get('message', data['error'])}")
        return data["result"]
    sys.exit("archive: no address answered as the MCP server – " + "; ".join(why) +
             ". If none could be reached, the network is blocked in this session: skip the archive step.")


def call(tool, args):
    res = rpc("tools/call", {"name": tool, "arguments": args})
    for part in res.get("content", []):
        if part.get("type") == "text":
            print(part["text"])
    if res.get("isError"):
        sys.exit(1)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--scope", choices=["titles", "headings", "footnotes"])
    s.add_argument("--tree", choices=["books", "lessons", "audio"])
    s.add_argument("--year", type=int)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--full", action="store_true", help="full passage text")
    d = sub.add_parser("doc")
    d.add_argument("doc_id")
    d.add_argument("--section")
    d.add_argument("--max-chars", type=int)
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--keywords")
    y = sub.add_parser("years")
    y.add_argument("query", nargs="?")
    sub.add_parser("ping")
    o = p.parse_args()

    if o.cmd == "ping":
        info = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "mekorot-shiur", "version": "1"}})
        print("ok:", info["serverInfo"]["name"], info["serverInfo"].get("version"))
    elif o.cmd == "search":
        args = {"query": o.query, "limit": o.limit}
        for k in ("scope", "tree", "year"):
            if getattr(o, k):
                args[k] = getattr(o, k)
        if o.full:
            args["include_text"] = True
        call("search_archive", args)
    elif o.cmd == "doc":
        args = {"doc_id": o.doc_id}
        if o.section:
            args["section"] = o.section
        if o.max_chars:
            args["max_chars"] = o.max_chars
        call("get_document", args)
    elif o.cmd == "ask":
        args = {"question": o.question}
        if o.keywords:
            args["keywords"] = o.keywords
        call("ask_archive", args)
    elif o.cmd == "years":
        args = {"kind": "years"}
        if o.query:
            args["query"] = o.query
        call("browse_topics", args)


if __name__ == "__main__":
    main()
