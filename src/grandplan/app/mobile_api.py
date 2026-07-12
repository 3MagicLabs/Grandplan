"""Mobile surface: JSON serializers + the self-contained web app that gives the phone parity.

grandplan's `--serve` HTTP server (LAN / Tailscale, token-gated) exposes the SAME capture line and
review inbox the desktop tray has, so from a phone browser you can watch the queue and
approve/discard captures — the decision is resolved through the coordinator's shared handle
(`app.coordinator`), first surface wins. Everything here is pure/data (serializers + one static HTML
page) so it is unit-tested offline; the socket routing that calls it lives in `adapters.http_intake`
(`pragma: no cover`).

Auth model: the page at `GET /` is a public shell (no data). It reads the token from its own URL
(`?token=…`) and sends it as `Authorization: Bearer …` on every `/api/*` call, which ARE gated. So a
phone opens `http://<host>:8765/?token=<secret>` once; the data endpoints stay protected.
"""

from __future__ import annotations

from collections.abc import Sequence

from grandplan.app.coordinator import PendingReviewView, QueueItem


def queue_item_to_dict(item: QueueItem) -> dict[str, object]:
    """One live-queue row as JSON — mirrors the desktop queue view's row model."""
    return {
        "id": item.id,
        "snippet": item.snippet,
        "source": item.source,
        "state": item.state.value,
        "stage": item.stage.value if item.stage is not None else None,
        "position": item.position,
        "detail": item.detail,
    }


def queue_to_json(items: Sequence[QueueItem]) -> list[dict[str, object]]:
    return [queue_item_to_dict(item) for item in items]


def pending_view_to_dict(view: PendingReviewView) -> dict[str, object]:
    """One awaiting-review capture as JSON — everything the phone needs to render + decide on it."""
    state = view.state
    return {
        "id": view.id,
        "source": view.source,
        "snippet": view.snippet,
        "title": state.title,
        "note_type": state.note_type,
        "tags": list(state.tags),
        "original_text": state.original_text,
        "related_titles": list(state.related_titles),
        "is_probable_duplicate": state.is_probable_duplicate,
        "requires_review": state.requires_review,
        "links": [list(link) for link in state.links],
        "is_status_update": state.is_status_update,
        "update_target_title": state.update_target_title,
        "update_status": state.update_status,
        "is_edit": state.is_edit,
        "edit_target_title": state.edit_target_title,
        "edit_summary": state.edit_summary,
    }


def pending_to_json(views: Sequence[PendingReviewView]) -> list[dict[str, object]]:
    return [pending_view_to_dict(view) for view in views]


def parse_decision_path(path: str) -> tuple[str, bool] | None:
    """Parse `/api/pending/<id>/approve|discard` → `(id, approve)`, else None (not a decision route).

    The id is opaque (a monotonic counter today) and is passed straight back to the coordinator, which
    only acts if it matches the current pending review — so an unknown/stale id is a harmless no-op."""
    parts = [segment for segment in path.strip("/").split("/") if segment]
    if len(parts) != 4 or parts[0] != "api" or parts[1] != "pending":
        return None
    pending_id, action = parts[2], parts[3]
    if action == "approve":
        return pending_id, True
    if action == "discard":
        return pending_id, False
    return None


# The whole phone UI: one self-contained page (no external requests — CSP-safe, offline). It reads
# the token from its own URL and polls /api/queue + /api/pending, rendering the pending inbox (with
# Approve/Discard) and the live pipeline, and toasting each newly finished capture.
MOBILE_APP_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>grandplan</title>
<style>
  :root { color-scheme: light dark; --bg:#fff; --fg:#111; --mut:#666; --card:#f5f5f7;
          --line:#e3e3e6; --accent:#2d7dff; --ok:#1a9c4e; --bad:#d33; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0d0d10; --fg:#eee; --mut:#9a9aa2; --card:#1a1a1f; --line:#2a2a31; } }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; font:15px/1.45 -apple-system,system-ui,sans-serif; background:var(--bg);
         color:var(--fg); padding:0 12px calc(24px + env(safe-area-inset-bottom)); }
  header { position:sticky; top:0; background:var(--bg); padding:14px 2px 8px;
           display:flex; align-items:center; gap:8px; border-bottom:1px solid var(--line); }
  header h1 { font-size:17px; margin:0; flex:1; }
  #dot { width:9px; height:9px; border-radius:50%; background:var(--mut); }
  #dot.live { background:var(--ok); }
  h2 { font-size:11px; letter-spacing:1px; text-transform:uppercase; color:var(--mut);
       margin:20px 2px 8px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:12px; margin-bottom:10px; }
  .snip { font-weight:600; overflow-wrap:anywhere; }
  .meta { color:var(--mut); font-size:13px; margin-top:3px; }
  .tags { margin-top:6px; display:flex; flex-wrap:wrap; gap:5px; }
  .tag { font-size:12px; background:var(--bg); border:1px solid var(--line);
         border-radius:20px; padding:1px 9px; color:var(--mut); }
  .badge { font-size:11px; font-weight:700; border-radius:6px; padding:1px 7px; margin-left:6px; }
  .badge.dup { background:#8a6d00; color:#fff; } .badge.rev { background:var(--bad); color:#fff; }
  .btns { display:flex; gap:8px; margin-top:12px; }
  button { flex:1; font:600 15px/1 inherit; border:0; border-radius:10px; padding:12px;
           color:#fff; }
  button:active { opacity:.7; }
  .approve { background:var(--ok); } .discard { background:var(--bad); }
  button:disabled { opacity:.4; }
  .row { display:flex; align-items:center; gap:8px; padding:8px 2px; border-bottom:1px solid var(--line); }
  .row:last-child { border-bottom:0; }
  .row .snip { flex:1; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .st { font-size:12px; color:var(--mut); }
  .st.now { color:var(--accent); font-weight:700; }
  .st.ok { color:var(--ok); }
  .empty { color:var(--mut); text-align:center; padding:22px; }
  #toasts { position:fixed; left:12px; right:12px; bottom:calc(14px + env(safe-area-inset-bottom));
            display:flex; flex-direction:column; gap:8px; pointer-events:none; }
  .toast { background:var(--fg); color:var(--bg); border-radius:10px; padding:10px 14px;
           font-size:14px; opacity:.96; box-shadow:0 4px 16px rgba(0,0,0,.25); }
  #err { color:var(--bad); font-size:13px; padding:10px 2px; }
</style>
</head>
<body>
<header><span id="dot"></span><h1>grandplan</h1></header>
<div id="err"></div>
<h2>Review</h2><div id="pending"></div>
<h2>Queue</h2><div id="queue"></div>
<div id="toasts"></div>
<script>
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const H = TOKEN ? { Authorization: "Bearer " + TOKEN } : {};
const el = id => document.getElementById(id);
const esc = s => (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let seenDone = new Set(), first = true;

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: H }, opts||{}));
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.status === 204 ? null : r.json();
}
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  el("toasts").appendChild(t); setTimeout(() => t.remove(), 3200);
}
async function decide(id, approve) {
  document.querySelectorAll("[data-id='"+id+"'] button").forEach(b => b.disabled = true);
  try { await api("/api/pending/" + encodeURIComponent(id) + "/" + (approve?"approve":"discard"),
                  { method: "POST" }); await refresh(); }
  catch (e) { el("err").textContent = "" + e; }
}
function pendingCard(p) {
  const badge = p.is_probable_duplicate ? '<span class="badge dup">possible duplicate</span>'
             : p.requires_review ? '<span class="badge rev">needs review</span>' : '';
  let head = p.is_status_update ? 'Mark <b>'+esc(p.update_target_title)+'</b> → '+esc(p.update_status)
           : p.is_edit ? 'Edit <b>'+esc(p.edit_target_title)+'</b>: '+esc(p.edit_summary)
           : esc(p.title || p.snippet);
  const tags = (p.tags||[]).map(t => '<span class="tag">'+esc(t)+'</span>').join("");
  const rel = (p.related_titles||[]).length ? '<div class="meta">related: '
              + p.related_titles.map(esc).join(", ") + '</div>' : '';
  return '<div class="card" data-id="'+esc(p.id)+'">'
       + '<div class="snip">'+head+badge+'</div>'
       + '<div class="meta">'+esc(p.note_type)+' · from '+esc(p.source)+'</div>'
       + (tags ? '<div class="tags">'+tags+'</div>' : '') + rel
       + '<div class="btns"><button class="approve" data-act="approve" data-id="'+esc(p.id)
       + '">Save</button><button class="discard" data-act="discard" data-id="'+esc(p.id)
       + '">Discard</button></div></div>';
}
el("pending").addEventListener("click", e => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  decide(b.dataset.id, b.dataset.act === "approve");
});
function queueRow(q) {
  const icon = /phone/i.test(q.source) ? "\\uD83D\\uDCF1" : "\\uD83D\\uDDA5\\uFE0F";
  let st = "queued", cls = "st";
  if (q.state === "in_flight") { st = q.stage || "working"; cls = "st now"; }
  else if (q.state === "queued") { st = "#" + q.position + " in line"; }
  else if (q.state === "saved") { st = "saved \\u2713"; cls = "st ok"; }
  else if (q.state === "discarded") { st = "discarded"; }
  else if (q.state === "failed") { st = "failed"; }
  return '<div class="row"><span>'+icon+'</span><span class="snip">'+esc(q.snippet)
       + '</span><span class="'+cls+'">'+esc(st)+'</span></div>';
}
async function refresh() {
  try {
    const [pending, queue] = await Promise.all([api("/api/pending"), api("/api/queue")]);
    el("err").textContent = ""; el("dot").className = "live";
    el("pending").innerHTML = pending.length ? pending.map(pendingCard).join("")
        : '<div class="empty">Nothing to review.</div>';
    el("queue").innerHTML = queue.length ? queue.map(queueRow).join("")
        : '<div class="empty">Queue is empty.</div>';
    for (const q of queue) {
      if (["saved","discarded","failed"].includes(q.state)) {
        if (!seenDone.has(q.id) && !first)
          toast((q.state==="saved"?"Saved \\u2713 ":q.state==="failed"?"Failed: ":"Discarded: ") + q.snippet);
        seenDone.add(q.id);
      }
    }
    first = false;
  } catch (e) { el("dot").className = ""; el("err").textContent = "" + e; }
}
refresh(); setInterval(refresh, 1500);
</script>
</body>
</html>
"""
