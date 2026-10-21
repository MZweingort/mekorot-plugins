# mekorot-plugins – notes for every Claude session that edits this repo

The owner is not a developer. Messages to him are in Hebrew, short and plain;
code, comments and commits may be English.

## The archive address – do not "fix" it

- The MCP endpoint of the Gal Einai archive is **https://galeinai-mcp.vercel.app/api/mcp**.
  `plugins/mekorot-shiur/.mcp.json` and `scripts/archive.py` point there.
- **https://galeinai.org.il/mcp/ is not the endpoint.** It is the site's "connect to AI"
  page for people: GET returns HTML, POST returns 405 with HTML. It looks like the
  canonical address, which is why it was put into the plugin twice by mistake
  (up to 0.2.0, and again 0.4.3–0.5.0). Each time the connector failed with
  "Unexpected content type: text/html" and archive.py died.
- archive.py follows the page: when an address answers HTML it reads the endpoint
  address printed on that page and tries it. If the endpoint ever moves, update the
  page (galeinai-v3, `web/app/(site)/mcp/page.tsx`) and both constants here.
- Check before pushing: `python3 plugins/mekorot-shiur/skills/milui-mekorot/scripts/archive.py ping`
  must print `ok: galeinai-archive …`, and a POST of `initialize` to the address in
  `.mcp.json` must answer `content-type: application/json`.

## Releasing

- Every change bumps `version` in `plugins/mekorot-shiur/.claude-plugin/plugin.json`
  and gets a `vX.Y.Z: …` commit, pushed to `main`.
- Installed copies do not all follow `main` by themselves:
  - Claude Code: `/plugin marketplace update mekorot-plugins` (copies live in
    `~/.claude/plugins/cache/mekorot-plugins/mekorot-shiur/<version>`).
  - Claude desktop / Cowork: Customize → Plugins → mekorot-plugins → **Update**. Its copy
    did not pull 0.5.1 for eight days on its own (the installed version is in the
    session's `rpm/manifest.json`, `updatedAt`). Tell the owner to press Update after a
    release that matters.
  - A copy installed by dragging a `.plugin` file sits under "My Uploads" and never updates.
