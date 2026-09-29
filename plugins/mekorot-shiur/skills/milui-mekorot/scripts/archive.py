#!/usr/bin/env python3
"""Call the Gal Einai archive MCP server directly over HTTP.

Fallback for sessions where the galeinai-archive connector did not connect:
the server is stateless JSON-RPC, so a plain POST of `tools/call` works
without any MCP client. Standard library only.

  archive.py search "דבר הוי' מירושלם" [--scope footnotes|titles|headings]
                    [--tree lessons|books|audio] [--year 5777] [--limit 10] [--full]
  archive.py doc <doc_id> [--section "..."] [--max-chars 6000]
  archive.py ask "שאלה" --keywords "מלה מלה"
  archive.py years [filter]
  archive.py ping
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

URL = "https://galeinai-mcp.vercel.app/api/mcp"


def rpc(method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "user-agent": "mekorot-shiur-plugin",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"archive: HTTP {e.code} from {URL}")
    except urllib.error.URLError as e:
        sys.exit(f"archive: cannot reach {URL} ({e.reason}) – "
                 "network may be blocked in this session; skip the archive step")
    if "error" in data:
        sys.exit(f"archive: {data['error'].get('message', data['error'])}")
    return data["result"]


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
