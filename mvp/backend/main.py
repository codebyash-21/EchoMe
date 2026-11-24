"""EchoMe MVP – FastAPI backend. Serves the web app and a small JSON API, all on localhost.

Run from the mvp/ folder:
    uvicorn backend.main:app --reload
then open http://localhost:8000
"""
import csv
import io
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cloud, db, engine, llm, seed

BASE_DIR = db.BASE_DIR
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = FastAPI(title="EchoMe MVP", version="0.1.0")


@app.on_event("startup")
def startup():
    db.init_db()
    with db.connect() as c:
        if not db.one(c, "SELECT id FROM user_profile WHERE id = 1"):
            seed.seed(reset=False)


# ----------------------------------------------------------------------------- shared state
def load(c):
    profile = db.one(c, "SELECT * FROM user_profile WHERE id = 1") or {"name": "there", "north_star": None, "self_trust": 60}
    health = db.rows(c, "SELECT * FROM health_logs ORDER BY date")
    promises = db.rows(c, "SELECT * FROM promises ORDER BY created_at")
    return profile, health, promises


def today_context(c):
    profile, health, promises = load(c)
    today_str = datetime.now().date().isoformat()
    today = next((h for h in health if h["date"] == today_str), None)
    base = engine.baselines(health)
    score, label, reasons, depleted = engine.body_state(today, base)
    by_date = {h["date"]: h for h in health}
    hist = engine.similar_day_history(promises, by_date, today["sleep_hours"] if today else None)
    cap = engine.capacity_minutes(score, hist)
    return {"profile": profile, "health": health, "promises": promises, "today": today, "base": base,
            "score": score, "label": label, "reasons": reasons, "depleted": depleted, "capacity": cap,
            "by_date": by_date}


def buddy_mood(ctx, last_mode=None):
    if last_mode == "protect":
        return "sleepy"
    if last_mode in ("push", "gentle"):
        return "caring"
    if ctx["label"] == "Low":
        return "groggy"
    if ctx["label"] == "High":
        return "happy"
    return "calm"


def adjust_trust(c, delta, reason):
    c.execute("UPDATE user_profile SET self_trust = MAX(0, MIN(100, self_trust + ?)) WHERE id = 1", (delta,))
    c.execute("INSERT INTO trust_events (created_at, delta, reason) VALUES (?,?,?)",
              (datetime.now().isoformat(timespec="minutes"), delta, reason))


def refresh_rules(c, ctx):
    found = engine.pattern_rules(ctx["promises"], ctx["by_date"])
    existing = {r["key"]: r for r in db.rows(c, "SELECT * FROM manual_rules")}
    for r in found:
        if r["key"] in existing:
            c.execute("UPDATE manual_rules SET text = ?, evidence = ? WHERE key = ?", (r["text"], r["evidence"], r["key"]))
        else:
            c.execute("INSERT INTO manual_rules (key, text, evidence) VALUES (?,?,?)", (r["key"], r["text"], r["evidence"]))


# ----------------------------------------------------------------------------- API: state
@app.get("/api/state")
def state():
    with db.connect() as c:
        ctx = today_context(c)
        active = [p for p in ctx["promises"] if p["status"] == "active"]
        recent = list(reversed(ctx["promises"]))[:8]
        last = db.one(c, "SELECT * FROM checkins ORDER BY id DESC LIMIT 1")
        return {
            "name": ctx["profile"]["name"],
            "north_star": ctx["profile"]["north_star"],
            "self_trust": ctx["profile"]["self_trust"],
            "today": ctx["today"],
            "baseline": ctx["base"],
            "body": {"score": ctx["score"], "label": ctx["label"], "reasons": ctx["reasons"], "depleted": ctx["depleted"]},
            "capacity_minutes": ctx["capacity"],
            "active_promises": active,
            "recent_promises": recent,
            "buddy": buddy_mood(ctx, last["mode"] if last and datetime.fromisoformat(last["created_at"]) > datetime.now() - timedelta(minutes=60) else None),
            "llm": {"available": llm.available(), "model": llm.OLLAMA_MODEL},
            "health_history": ctx["health"][-14:],
        }


# ----------------------------------------------------------------------------- API: watch data
class HealthIn(BaseModel):
    sleep_hours: float
    resting_hr: int
    steps: int = 0
    stress: int = 50


@app.post("/api/health/sync")
def health_sync(h: HealthIn):
    """Simulated watch sync for demos (writes today's row)."""
    with db.connect() as c:
        c.execute("UPDATE checkins SET created_at = '2000-01-01T00:00' WHERE created_at > ?",
                  ((datetime.now() - timedelta(minutes=60)).isoformat(timespec="minutes"),))
        c.execute("INSERT OR REPLACE INTO health_logs VALUES (?,?,?,?,?)",
                  (datetime.now().date().isoformat(), h.sleep_hours, h.resting_hr, h.steps, h.stress))
    return state()


@app.post("/api/health/import")
async def health_import(file: UploadFile = File(...)):
    """Import a CSV export with columns: date, sleep_hours, resting_hr, steps, stress."""
    text = (await file.read()).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    n = 0
    with db.connect() as c:
        for r in reader:
            try:
                d = datetime.fromisoformat(r["date"].strip()).date().isoformat()
                c.execute("INSERT OR REPLACE INTO health_logs VALUES (?,?,?,?,?)",
                          (d, float(r.get("sleep_hours") or 0) or None, int(float(r.get("resting_hr") or 0)) or None,
                           int(float(r.get("steps") or 0)), int(float(r.get("stress") or 50))))
                n += 1
            except (KeyError, ValueError):
                continue
    if n == 0:
        raise HTTPException(400, "No valid rows. Expected columns: date, sleep_hours, resting_hr, steps, stress")
    return {"imported": n}


# ----------------------------------------------------------------------------- API: promises
class PromiseIn(BaseModel):
    text: str


class AcceptIn(BaseModel):
    original: str
    final_text: str
    est_minutes: int | None = None
    capacity_minutes: int | None = None
    due_at: str | None = None


class StatusIn(BaseModel):
    status: str  # kept | broken | moved


@app.post("/api/promise/propose")
def propose(p: PromiseIn):
    if not p.text.strip():
        raise HTTPException(400, "Say what you want to get done.")
    with db.connect() as c:
        ctx = today_context(c)
    return engine.negotiate(p.text, ctx["capacity"], ctx["label"], ctx["reasons"])


@app.post("/api/promise/accept")
def accept(a: AcceptIn):
    with db.connect() as c:
        cur = c.execute(
            "INSERT INTO promises (created_at, original_text, final_text, est_minutes, capacity_minutes, due_at)"
            " VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="minutes"), a.original, a.final_text, a.est_minutes,
             a.capacity_minutes, a.due_at))
        return db.one(c, "SELECT * FROM promises WHERE id = ?", (cur.lastrowid,))


@app.post("/api/promise/{pid}/why")
async def upload_why(pid: int, file: UploadFile = File(...), why_text: str = ""):
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "Clip too long")
    ext = ".webm" if "webm" in (file.content_type or "") else ".ogg" if "ogg" in (file.content_type or "") else ".m4a"
    name = f"why_{pid}_{int(datetime.now().timestamp())}{ext}"
    with open(os.path.join(db.CLIPS_DIR, name), "wb") as f:
        f.write(data)
    with db.connect() as c:
        c.execute("UPDATE promises SET why_clip = ?, why_text = COALESCE(NULLIF(?, ''), why_text) WHERE id = ?",
                  (name, why_text, pid))
    return {"ok": True, "clip": f"/clips/{name}"}


class WhyTextIn(BaseModel):
    why_text: str


@app.post("/api/promise/{pid}/why-text")
def why_text(pid: int, w: WhyTextIn):
    with db.connect() as c:
        c.execute("UPDATE promises SET why_text = ? WHERE id = ?", (w.why_text, pid))
    return {"ok": True}


@app.post("/api/promise/{pid}/status")
def set_status(pid: int, s: StatusIn):
    if s.status not in ("kept", "broken", "moved"):
        raise HTTPException(400, "status must be kept, broken or moved")
    with db.connect() as c:
        p = db.one(c, "SELECT * FROM promises WHERE id = ?", (pid,))
        if not p:
            raise HTTPException(404, "Promise not found")
        c.execute("UPDATE promises SET status = ? WHERE id = ?", (s.status, pid))
        if s.status == "kept":
            adjust_trust(c, 3, f"Kept: {p['final_text']}")
        elif s.status == "broken":
            adjust_trust(c, -2, f"Broken: {p['final_text']}")
        ctx = today_context(c)
        refresh_rules(c, ctx)
    return state()


# ----------------------------------------------------------------------------- API: check-ins & nudges
class CheckinIn(BaseModel):
    text: str


def respond(c, kind, text):
    ctx = today_context(c)
    mode = engine.choose_mode(kind, ctx["depleted"])
    nowiso = datetime.now().isoformat(timespec="minutes")
    active = [p for p in ctx["promises"] if p["status"] == "active"]
    current = [p for p in active if p["created_at"] <= nowiso]
    promise = (current or active or [None])[-1]
    has_why = bool(promise and (promise.get("why_clip") or promise.get("why_text")))
    reply = engine.mode_reply(mode, ctx["profile"]["name"], ctx["reasons"], promise, ctx["profile"]["north_star"], has_why)
    moved_to = None
    if mode == "protect" and promise:
        tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        c.execute("UPDATE promises SET status = 'moved' WHERE id = ?", (promise["id"],))
        c.execute(
            "INSERT INTO promises (created_at, original_text, final_text, est_minutes, capacity_minutes, due_at, why_clip, why_text)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (tomorrow.isoformat(timespec="minutes"), promise["original_text"], promise["final_text"],
             promise["est_minutes"], promise["capacity_minutes"], tomorrow.isoformat(timespec="minutes"),
             promise["why_clip"], promise["why_text"]))
        moved_to = tomorrow.isoformat(timespec="minutes")
    c.execute("INSERT INTO checkins (created_at, text, mode, reply) VALUES (?,?,?,?)",
              (datetime.now().isoformat(timespec="minutes"), text, mode, reply))
    return {
        "mode": mode,
        "kind": kind,
        "reply": reply,
        "body": {"label": ctx["label"], "reasons": ctx["reasons"], "depleted": ctx["depleted"]},
        "promise": promise,
        "why_clip": f"/clips/{promise['why_clip']}" if mode == "push" and promise and promise.get("why_clip") else None,
        "why_text": promise.get("why_text") if mode == "push" and promise else None,
        "moved_to": moved_to,
        "self_trust": db.one(c, "SELECT self_trust FROM user_profile WHERE id = 1")["self_trust"],
    }


@app.post("/api/checkin")
def checkin(ci: CheckinIn):
    with db.connect() as c:
        return respond(c, engine.classify(ci.text), ci.text)


@app.post("/api/drift")
def drift():
    """Simulates the activity tracker spotting 40 minutes on YouTube during a promise."""
    with db.connect() as c:
        return respond(c, "drift", "[activity] 40 min on YouTube during a promise")


# ----------------------------------------------------------------------------- API: personal manual
@app.get("/api/manual")
def manual():
    with db.connect() as c:
        ctx = today_context(c)
        refresh_rules(c, ctx)
        rules = db.rows(c, "SELECT * FROM manual_rules WHERE status != 'rejected'")
        facts = db.rows(c, "SELECT * FROM about_me")
        return {"rules": rules, "said_vs_data": engine.said_vs_data(facts, ctx["promises"])}


class RuleIn(BaseModel):
    status: str


@app.post("/api/manual/{key}")
def set_rule(key: str, r: RuleIn):
    if r.status not in ("confirmed", "rejected", "proposed"):
        raise HTTPException(400, "bad status")
    with db.connect() as c:
        c.execute("UPDATE manual_rules SET status = ? WHERE key = ?", (r.status, key))
    return manual()


@app.get("/api/manual/export.md")
def export_manual():
    with db.connect() as c:
        name = db.one(c, "SELECT name FROM user_profile WHERE id = 1")["name"]
        rules = db.rows(c, "SELECT * FROM manual_rules WHERE status = 'confirmed'")
    md = f"# {name}'s Manual (EchoMe)\n\n" + "\n".join(f"- {r['text']}  _({r['evidence']})_" for r in rules)
    return Response(md or "# No confirmed rules yet", media_type="text/markdown",
                    headers={"Content-Disposition": "attachment; filename=my-manual.md"})


# ----------------------------------------------------------------------------- API: About Me
class IntroIn(BaseModel):
    text: str


class FactsIn(BaseModel):
    facts: list[dict]


@app.get("/api/aboutme")
def aboutme():
    with db.connect() as c:
        return db.rows(c, "SELECT * FROM about_me ORDER BY id DESC")


@app.post("/api/aboutme/extract")
def aboutme_extract(i: IntroIn):
    return {"facts": engine.extract_facts(i.text)}


@app.post("/api/aboutme/confirm")
def aboutme_confirm(f: FactsIn):
    with db.connect() as c:
        for fact in f.facts:
            if fact.get("text"):
                c.execute("INSERT INTO about_me (category, text, temporary, created_at) VALUES (?,?,?,?)",
                          (fact.get("category", "Identity"), fact["text"][:200], int(bool(fact.get("temporary"))),
                           datetime.now().isoformat(timespec="minutes")))
    return aboutme()


@app.delete("/api/aboutme/{fid}")
def aboutme_delete(fid: int):
    with db.connect() as c:
        c.execute("DELETE FROM about_me WHERE id = ?", (fid,))
    return aboutme()


# ----------------------------------------------------------------------------- API: My Data
@app.get("/api/mydata")
def mydata():
    with db.connect() as c:
        counts = {t: db.one(c, f"SELECT COUNT(*) AS n FROM {t}")["n"]
                  for t in ("health_logs", "promises", "checkins", "about_me", "manual_rules")}
    clips = len(os.listdir(db.CLIPS_DIR)) if os.path.isdir(db.CLIPS_DIR) else 0
    return {"counts": counts, "clips": clips, "location": db.DB_PATH, "cloud_bytes_sent": 0,
            "llm": "local Ollama" if llm.available() else "built-in rules (no AI model installed)"}


@app.get("/api/export")
def export_all():
    with db.connect() as c:
        dump = {t: db.rows(c, f"SELECT * FROM {t}") for t in
                ("user_profile", "health_logs", "promises", "checkins", "about_me", "manual_rules", "trust_events")}
    return Response(json.dumps(dump, indent=2), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=echome-export.json"})


@app.post("/api/forget")
def forget():
    db.wipe_everything()
    with db.connect() as c:
        c.execute("INSERT INTO user_profile (id, name, north_star, self_trust) VALUES (1, 'there', NULL, 60)")
    return {"ok": True}


@app.post("/api/demo/reset")
def demo_reset():
    seed.seed(reset=True)
    return state()


# ----------------------------------------------------------------------------- optional cloud: ElevenLabs + AWS
privacy_filter = cloud.privacy_filter


class TTSIn(BaseModel):
    text: str


@app.post("/api/tts")
def tts(t: TTSIn):
    """Pip's voice. ElevenLabs if configured (opt-in, privacy-filtered); otherwise the device voice."""
    audio = cloud.elevenlabs_tts(t.text)
    if audio:
        return Response(audio, media_type="audio/mpeg", headers={"X-Voice": "elevenlabs"})
    return JSONResponse({"fallback": "local", "text": t.text})


@app.get("/api/cloud/status")
def cloud_status():
    return {
        "elevenlabs": {"configured": cloud.elevenlabs_configured()},
        "aws": {**cloud.s3_status(), "encryption_available": cloud.crypto_available()},
        "preview_filtered_text": cloud.privacy_filter(
            "You're running low: you slept 4.5h, 1.8h less than usual; your resting heart rate is up 8 bpm. Rest now."),
    }


class PassIn(BaseModel):
    passphrase: str


def _check_pass(p: str):
    if len(p) < 6:
        raise HTTPException(400, "Use a passphrase of at least 6 characters.")
    if not cloud.crypto_available():
        raise HTTPException(400, "Encryption library missing. Run: pip install -r requirements-cloud.txt")


@app.post("/api/cloud/backup")
def cloud_backup(p: PassIn):
    _check_pass(p.passphrase)
    try:
        return cloud.backup(p.passphrase)
    except Exception as e:
        raise HTTPException(502, f"Backup failed: {e}")


@app.post("/api/cloud/restore")
def cloud_restore(p: PassIn):
    _check_pass(p.passphrase)
    try:
        return cloud.restore(p.passphrase)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Restore failed: {e}")


@app.get("/api/cloud/backup/{name}")
def cloud_backup_download(name: str):
    if not re.fullmatch(r"echome-\d{8}-\d{6}\.enc", name):
        raise HTTPException(404, "Not found")
    path = os.path.join(cloud.BACKUP_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="application/octet-stream", filename=name)


# ----------------------------------------------------------------------------- static files
app.mount("/clips", StaticFiles(directory=db.CLIPS_DIR, check_dir=False), name="clips")


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
