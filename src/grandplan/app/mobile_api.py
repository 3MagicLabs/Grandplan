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

import json
from collections.abc import Callable, Sequence

from grandplan.adapters.http_intake import IntakeResult, check_auth
from grandplan.app.coordinator import PendingReviewView, QueueItem
from grandplan.app.review import ReviewEdits

QueueProvider = Callable[[], list[dict[str, object]]]
PendingProvider = Callable[[], list[dict[str, object]]]
DecideFn = Callable[[str, bool, "ReviewEdits | None"], bool]


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
        "proposed_updates": [list(update) for update in state.proposed_updates],
        "body": state.body,  # the proposed note body — shown + editable before Save
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


def handle_mobile_get(
    path: str,
    provided_token: str | None,
    *,
    token: str,
    queue: QueueProvider,
    pending: PendingProvider,
) -> IntakeResult:
    """Route a GET: `/` → the web app shell (public), `/api/queue` + `/api/pending` → JSON (gated)."""
    normalized = path.split("?", 1)[0].rstrip("/") or "/"
    if normalized == "/":  # public shell — no data, just HTML that then authenticates its API calls
        return IntakeResult(200, text=MOBILE_APP_HTML, content_type="text/html; charset=utf-8")
    if normalized in ("/api/queue", "/api/pending"):
        if not check_auth(token, provided_token):
            return IntakeResult(401, {"error": "unauthorized"})
        payload: dict[str, object] = (
            {"queue": queue()} if normalized == "/api/queue" else {"pending": pending()}
        )
        return IntakeResult(200, payload)
    return IntakeResult(404, {"error": "not found"})


def parse_review_edits(raw: bytes) -> ReviewEdits | None:
    """Parse the optional JSON body of an approve POST — `{title?, body?, tags?, note_type?}` — into
    ReviewEdits. Returns None when the body is empty/garbled or carries no usable field (= no edits),
    so a plain approve with no body behaves exactly as before. Lenient: bad field types are dropped."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    title = data.get("title")
    body = data.get("body")
    tags = data.get("tags")
    note_type = data.get("note_type")
    edits = ReviewEdits(
        title=title if isinstance(title, str) else None,
        body=body if isinstance(body, str) else None,
        tags=tuple(t for t in tags if isinstance(t, str)) if isinstance(tags, list) else None,
        note_type=note_type if isinstance(note_type, str) else None,
    )
    return edits if edits != ReviewEdits() else None  # nothing provided → no edits


def handle_mobile_decision(
    path: str,
    provided_token: str | None,
    *,
    token: str,
    decide: DecideFn,
    body: bytes = b"",
) -> IntakeResult:
    """Route POST `/api/pending/<id>/approve|discard` → resolve the parked review (gated). An approve
    may carry a JSON body of edits (title/body/tags/type) applied to the note before it is saved."""
    if not check_auth(token, provided_token):
        return IntakeResult(401, {"error": "unauthorized"})
    parsed = parse_decision_path(path.split("?", 1)[0])
    if parsed is None:
        return IntakeResult(404, {"error": "not found"})
    pending_id, approve = parsed
    edits = parse_review_edits(body) if approve else None
    return IntakeResult(200, {"resolved": decide(pending_id, approve, edits)})


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
  .orig { margin-top:8px; padding:8px 10px; background:var(--bg); border:1px solid var(--line);
          border-radius:8px; font-size:13px; white-space:pre-wrap; overflow-wrap:anywhere;
          max-height:180px; overflow-y:auto; }
  .orig-label { margin-top:8px; font-size:11px; letter-spacing:.5px; text-transform:uppercase;
                color:var(--mut); }
  .fld { display:block; margin-top:10px; }
  .fld-l { display:block; font-size:11px; letter-spacing:.5px; text-transform:uppercase;
           color:var(--mut); margin-bottom:3px; }
  input, select, textarea { width:100%; font:14px/1.4 inherit; color:var(--fg); background:var(--bg);
           border:1px solid var(--line); border-radius:8px; padding:9px 10px; }
  input:focus, select:focus, textarea:focus { outline:2px solid var(--accent); border-color:transparent; }
  textarea { resize:vertical; min-height:70px; }
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
let seenDone = new Set(), first = true, renderedPendingKey = null;

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: H }, opts||{}));
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.status === 204 ? null : r.json();
}
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  el("toasts").appendChild(t); setTimeout(() => t.remove(), 3200);
}
const NOTE_TYPES = ["idea","reference","task","project","goal","decision","question","entity"];
function fld(label, inner) {
  return '<label class="fld"><span class="fld-l">'+label+'</span>'+inner+'</label>';
}
async function decide(id, approve) {
  const card = el("pending").querySelector('.card[data-id="'+CSS.escape(id)+'"]');
  if (card) card.querySelectorAll("button").forEach(b => b.disabled = true);
  const opts = { method: "POST" };
  if (approve && card) {  // send the (possibly edited) fields; the server applies them before saving
    const v = sel => { const e = card.querySelector(sel); return e ? e.value : undefined; };
    const tags = v(".edit-tags");
    opts.headers = Object.assign({ "Content-Type": "application/json" }, H);
    opts.body = JSON.stringify({
      title: v(".edit-title"), body: v(".edit-body"), note_type: v(".edit-type"),
      tags: tags === undefined ? undefined : tags.split(",").map(s => s.trim()).filter(Boolean)
    });
  }
  try { await api("/api/pending/" + encodeURIComponent(id) + "/" + (approve?"approve":"discard"), opts);
        renderedPendingKey = null; await refresh(); }
  catch (e) { el("err").textContent = "" + e; }
}
function pendingCard(p) {
  const badge = p.is_probable_duplicate ? '<span class="badge dup">possible duplicate</span>'
             : p.requires_review ? '<span class="badge rev">needs review</span>' : '';
  const meta = '<div class="meta">from '+esc(p.source)+'</div>';
  const links = (p.links||[]).length ? '<div class="meta">relationships: '
              + p.links.map(l => esc(l[0]) + ' ' + esc(l[1])).join(", ") + '</div>' : '';
  const upd = (p.proposed_updates||[]).length ? '<div class="meta">also updating on save: '
              + p.proposed_updates.map(u => esc(u[0]) + ' → ' + esc(u[1])).join(", ") + '</div>' : '';
  const orig = p.original_text
              ? '<div class="orig-label">original (verbatim)</div><div class="orig">'
                + esc(p.original_text) + '</div>' : '';
  const btns = '<div class="btns"><button class="approve" data-act="approve" data-id="'+esc(p.id)
             + '">Save</button><button class="discard" data-act="discard" data-id="'+esc(p.id)
             + '">Discard</button></div>';
  if (p.is_status_update || p.is_edit) {  // an update/edit to an EXISTING note — not editable here
    const head = p.is_status_update ? 'Mark <b>'+esc(p.update_target_title)+'</b> → '+esc(p.update_status)
                                    : 'Edit <b>'+esc(p.edit_target_title)+'</b>: '+esc(p.edit_summary);
    return '<div class="card" data-id="'+esc(p.id)+'"><div class="snip">'+head+badge+'</div>'
         + meta + orig + btns + '</div>';
  }
  const types = NOTE_TYPES.includes(p.note_type) ? NOTE_TYPES : [p.note_type].concat(NOTE_TYPES);
  const typeOpts = types.map(t => '<option'+(t===p.note_type?' selected':'')+'>'+esc(t)+'</option>').join("");
  const form = fld('title', '<input class="edit-title" value="'+esc(p.title||"")+'">')
             + fld('type', '<select class="edit-type">'+typeOpts+'</select>')
             + fld('tags', '<input class="edit-tags" value="'+esc((p.tags||[]).join(", "))
                   +'" placeholder="comma, separated">')
             + fld('body', '<textarea class="edit-body" rows="4">'+esc(p.body||"")+'</textarea>');
  return '<div class="card" data-id="'+esc(p.id)+'">'
       + (badge ? '<div class="snip">'+badge+'</div>' : '') + meta + form + links + upd + orig + btns + '</div>';
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
    const [pRes, qRes] = await Promise.all([api("/api/pending"), api("/api/queue")]);
    const pending = pRes.pending || [], queue = qRes.queue || [];
    el("err").textContent = ""; el("dot").className = "live";
    // Only re-render the review section when the pending item actually CHANGES — otherwise the 1.5s
    // poll would wipe the fields you're editing mid-review (and steal focus).
    const pkey = pending.map(p => p.id).join(",");
    if (pkey !== renderedPendingKey) {
      renderedPendingKey = pkey;
      el("pending").innerHTML = pending.length ? pending.map(pendingCard).join("")
          : '<div class="empty">Nothing to review.</div>';
    }
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
