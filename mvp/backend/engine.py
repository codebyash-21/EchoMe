"""EchoMe's decision logic: capacity, promise negotiation, Push/Protect/Gentle, personal manual, About Me.

Every function works with plain rules. When a local Ollama model is available, it is used only
to phrase messages and parse free text more flexibly; results are validated and fall back to rules.
"""
import re
from datetime import datetime, timedelta
from statistics import mean

from . import llm

# ----------------------------------------------------------------------------- helpers
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "a": 1, "an": 1, "half": 0.5}
UNIT_MINUTES = {  # rough effort per unit, in focused minutes
    "chapter": 45, "chapters": 45, "lecture": 60, "lectures": 60, "problem": 15, "problems": 15,
    "question": 10, "questions": 10, "page": 6, "pages": 6, "topic": 40, "topics": 40,
    "module": 60, "modules": 60, "paper": 45, "papers": 45, "unit": 60, "units": 60, "exercise": 20, "exercises": 20, "sets": 30, "set": 30, "video": 30, "videos": 30, "assignment": 180, "assignments": 180,
    "hour": 60, "hours": 60, "hr": 60, "hrs": 60, "minute": 1, "minutes": 1, "mins": 1,
}
WHOLE_WORDS = ("whole", "entire", "everything", "all of", "complete", "full")


def round15(m):
    return int(max(15, round(m / 15) * 15))


def now():
    return datetime.now()


# ----------------------------------------------------------------------------- body & capacity
def baselines(health):
    """health: list of dicts sorted by date ascending (excluding today is fine)."""
    past = health[-15:-1] if len(health) > 1 else health
    sl = [h["sleep_hours"] for h in past if h.get("sleep_hours") is not None] or [7.0]
    hr = [h["resting_hr"] for h in past if h.get("resting_hr") is not None] or [66]
    return {"sleep": round(mean(sl), 1), "rhr": round(mean(hr))}


def body_state(today, base):
    """Return (score 0-100, label, reasons, depleted?)."""
    if not today:
        return 70, "Medium", ["No watch data yet today"], False
    score = 100.0
    reasons = []
    sleep, rhr, stress = today.get("sleep_hours"), today.get("resting_hr"), today.get("stress")
    if sleep is not None:
        deficit = base["sleep"] - sleep
        if deficit > 0:
            score -= deficit * 14
            reasons.append(f"you slept {sleep:g}h, {deficit:.1f}h less than usual")
        if sleep < 5:
            score -= 10
    if rhr is not None and rhr - base["rhr"] > 2:
        score -= (rhr - base["rhr"]) * 3
        reasons.append(f"your resting heart rate is up {rhr - base['rhr']} bpm")
    if stress is not None and stress > 50:
        score -= (stress - 50) * 0.5
        reasons.append(f"your stress is {stress}/100")
    score = max(15, min(100, round(score)))
    label = "High" if score >= 70 else "Medium" if score >= 45 else "Low"
    depleted = (
        (sleep is not None and (sleep < 5.5 or base["sleep"] - sleep >= 1.5))
        or (rhr is not None and rhr - base["rhr"] >= 6)
        or (stress is not None and stress >= 75)
    )
    if not reasons:
        reasons.append("your body looks well rested")
    return score, label, reasons, depleted


def capacity_minutes(score, history_minutes=None):
    """Focused minutes you can realistically do today. Blends body score with your own history."""
    from_body = 240 * score / 100
    if history_minutes:
        return round15(0.6 * from_body + 0.4 * history_minutes)
    return round15(from_body)


def similar_day_history(promises, health_by_date, sleep_today):
    """Average minutes of *kept* promises on days with similar sleep (±1h)."""
    if sleep_today is None:
        return None
    mins = []
    for p in promises:
        if p["status"] != "kept" or not p.get("est_minutes"):
            continue
        h = health_by_date.get(p["created_at"][:10])
        if h and h.get("sleep_hours") is not None and abs(h["sleep_hours"] - sleep_today) <= 1:
            mins.append(p["est_minutes"])
    return mean(mins) if len(mins) >= 2 else None


# ----------------------------------------------------------------------------- promises
def parse_promise(text):
    """Return {task, quantity, unit, est_minutes}. Tries the local LLM first, then rules."""
    t = text.lower()
    ai = llm.generate(
        "Extract the commitment from this sentence as JSON with keys "
        "task (short), quantity (number or null), unit (singular noun or null), est_minutes "
        f"(realistic focused minutes for a student). Sentence: \"{text}\"", want_json=True)
    if isinstance(ai, dict) and isinstance(ai.get("est_minutes"), (int, float)) and 5 <= ai["est_minutes"] <= 720:
        q = ai.get("quantity") if isinstance(ai.get("quantity"), (int, float)) else None
        return {"task": str(ai.get("task") or text), "quantity": q, "unit": ai.get("unit"),
                "est_minutes": int(ai["est_minutes"]), "source": "local-llm"}

    qty, unit = None, None
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?", t)
    for i, w in enumerate(words):
        if w[0].isdigit() or w in NUM_WORDS:
            for nxt in words[i + 1:i + 4]:          # allow an adjective: "2 research papers"
                if nxt in UNIT_MINUTES:
                    qty = float(w) if w[0].isdigit() else NUM_WORDS[w]
                    unit = nxt
                    break
            if unit:
                break
    if qty is not None and unit:
        est = qty * UNIT_MINUTES[unit]
    elif any(w in t for w in WHOLE_WORDS):
        est = 240
    elif "finish" in t:
        est = 150
    else:
        est = 90
    return {"task": text.strip(), "quantity": qty, "unit": unit, "est_minutes": int(est), "source": "rules"}


def due_label(hour):
    h = hour % 24
    return f"{(h - 1) % 12 + 1}:00 {'AM' if h < 12 else 'PM'}"


def negotiate(text, cap_minutes, body_label, reasons):
    """Return a suggested, right-sized promise with a concrete if-then plan."""
    p = parse_promise(text)
    est = p["est_minutes"]
    n = now()
    due_hour = min(n.hour + max(2, round(cap_minutes / 60) + 1), 22)
    if n.hour >= 20:
        due_hour = 23
    start_hour = min(n.hour + 1, due_hour - 1)
    fits = est <= cap_minutes * 1.1

    if fits:
        suggested = f"{text.strip().rstrip('.')} by {due_label(due_hour)}"
        verdict = "fits"
    elif p["quantity"] and p["unit"] and p["unit"] not in ("hour", "hours", "hr", "hrs", "minute", "minutes", "mins"):
        q = max(1, int(p["quantity"] * cap_minutes / est))
        unit = p["unit"] if q != 1 else p["unit"].rstrip("s")
        left = p["quantity"] - q
        rest = f", and the other {left:g} tomorrow morning" if left > 0 else ""
        suggested = f"Do {q} {unit} by {due_label(due_hour)}{rest}"
        verdict = "resized"
    elif p["unit"] in ("hour", "hours", "hr", "hrs"):
        suggested = f"Focus for {cap_minutes} minutes by {due_label(due_hour)}, then stop"
        verdict = "resized"
    else:
        suggested = f"Finish just the first part (about {cap_minutes} minutes) by {due_label(due_hour)}"
        verdict = "resized"

    why = "; ".join(reasons)
    if verdict == "fits":
        message = f"That's about {est} focused minutes, and today you have roughly {cap_minutes}. Looks doable. Lock it in?"
    else:
        message = (f"That's about {est} focused minutes of work. Today you have roughly {cap_minutes}: "
                   f"{why}. Want a promise you'll actually keep?")
    ai = llm.generate(
        "You are EchoMe, a warm, concise buddy. In at most 2 short sentences, tell the user why a smaller "
        f"promise is smarter today. Facts: their promise '{text}' needs ~{est} min; capacity today ~{cap_minutes} min; "
        f"reasons: {why}. Suggest: '{suggested}'. No numbers about health beyond the facts given.") if verdict != "fits" else None
    if ai and len(ai) < 400:
        message = ai
    return {
        "original": text.strip(),
        "suggested": suggested,
        "verdict": verdict,
        "est_minutes": est,
        "capacity_minutes": cap_minutes,
        "body_label": body_label,
        "if_then": f"IF it's {due_label(start_hour)}, THEN desk, phone in another room",
        "due_at": n.replace(hour=due_hour % 24, minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
        "parsed_by": p["source"],
        "message": message,
    }


# ----------------------------------------------------------------------------- Push / Protect / Gentle
DISTRESS = ("hopeless", "worthless", "want to die", "kill myself", "end it all", "no point living",
            "can't go on", "cant go on", "nothing matters", "hate myself", "panic attack", "breaking down",
            "self harm", "hurt myself")
GIVING_UP = ("give up", "giving up", "gonna quit", "going to quit", "i quit", "can't do this", "cant do this",
             "done with this", "too tired", "so tired", "no motivation", "not doing this", "skip it", "forget it")
DRIFT = ("youtube", "instagram", "reels", "netflix", "scrolling", "distracted", "procrastinat")


def classify(text):
    t = text.lower()
    if any(k in t for k in DISTRESS):
        return "distress"
    if any(k in t for k in GIVING_UP):
        return "giving_up"
    if any(k in t for k in DRIFT):
        return "drift"
    return "neutral"


def choose_mode(kind, depleted):
    if kind == "distress":
        return "gentle"
    if kind in ("giving_up", "drift"):
        return "protect" if depleted else "push"
    return "neutral"


def mode_reply(mode, name, reasons, promise=None, north_star=None, has_why=False):
    task = promise["final_text"] if promise else "today's promise"
    if mode == "gentle":
        return ("That sounds really heavy, and I'm glad you told me. I'm not going to push you right now. "
                "Would it help to talk to someone you trust? You can also call Tele-MANAS on 14416, "
                "free and confidential, 24x7.")
    if mode == "protect":
        why = "; ".join(reasons)
        return (f"You're not giving up, {name}. Your body is running low: {why}. Pushing on now usually "
                f"costs you tomorrow. I've moved \"{task}\" to tomorrow at 10:00 AM, with no penalty. Rest now.")
    if mode == "push":
        goal = f" Remember why you started: {north_star}." if north_star else ""
        tail = " Here's what you told me earlier. Just 15 more minutes?" if has_why else " Just 15 more minutes, then decide."
        return (f"Your body is actually in good shape today, so this sounds like resistance, not exhaustion."
                f"{goal}{tail}")
    return "Got it, I've noted that. How's today's promise going?"


# ----------------------------------------------------------------------------- personal manual
def pattern_rules(promises, health_by_date):
    """Find simple, honest patterns. Returns list of {key, text, evidence}."""
    done = [p for p in promises if p["status"] in ("kept", "broken")]
    rules = []

    late = [p for p in done if int(p["created_at"][11:13]) >= 23 or int(p["created_at"][11:13]) < 5]
    if len(late) >= 3:
        broken = sum(1 for p in late if p["status"] == "broken")
        if broken / len(late) >= 0.6:
            rules.append({"key": "late_night",
                          "text": "You break most promises made after 11 PM.",
                          "evidence": f"{broken} of {len(late)} late-night promises broken"})

    def keep_rate(group):
        return sum(1 for p in group if p["status"] == "kept") / len(group) if group else None

    well, poor = [], []
    for p in done:
        h = health_by_date.get(p["created_at"][:10])
        if not h or h.get("sleep_hours") is None:
            continue
        (well if h["sleep_hours"] >= 7 else poor if h["sleep_hours"] < 6 else []).append(p)
    if len(well) >= 2 and len(poor) >= 2:
        kw, kp = keep_rate(well), keep_rate(poor)
        if kw - kp >= 0.25:
            rules.append({"key": "sleep_keep",
                          "text": f"You keep {kw:.0%} of promises after 7h+ sleep, but only {kp:.0%} after under 6h.",
                          "evidence": f"{len(well)} well-rested vs {len(poor)} short-sleep promises"})

    morning = [p for p in done if 6 <= int(p["created_at"][11:13]) < 12]
    if len(morning) >= 2 and keep_rate(morning) >= 0.7:
        rules.append({"key": "morning_focus",
                      "text": "Promises you make in the morning usually get done. Plan big work early.",
                      "evidence": f"{sum(1 for p in morning if p['status']=='kept')} of {len(morning)} morning promises kept"})

    big = [p for p in done if (p.get("est_minutes") or 0) > (p.get("capacity_minutes") or 999)]
    if len(big) >= 2 and keep_rate(big) <= 0.4:
        rules.append({"key": "oversized",
                      "text": "When you promise more than your capacity, you usually don't finish. Smaller wins work better for you.",
                      "evidence": f"{sum(1 for p in big if p['status']=='kept')} of {len(big)} oversized promises kept"})
    return rules


def said_vs_data(about_facts, promises):
    """Compare what the user says about themselves with what the data shows."""
    insights = []
    text = " ".join(f["text"].lower() for f in about_facts)
    done = [p for p in promises if p["status"] in ("kept", "broken")]
    if "night owl" in text and done:
        morning = [p for p in done if 6 <= int(p["created_at"][11:13]) < 12]
        night = [p for p in done if int(p["created_at"][11:13]) >= 21 or int(p["created_at"][11:13]) < 5]
        if morning and night:
            km = sum(p["status"] == "kept" for p in morning) / len(morning)
            kn = sum(p["status"] == "kept" for p in night) / len(night)
            if km > kn:
                insights.append(f"You said you're a night owl, but you keep {km:.0%} of morning promises "
                                f"and only {kn:.0%} of late-night ones. Want to update that?")
    return insights


# ----------------------------------------------------------------------------- About Me
CATEGORY_RULES = [
    ("Upcoming", ("exam", "interview", "deadline", "next week", "tomorrow", "on monday", "on tuesday", "on wednesday",
                  "on thursday", "on friday", "on saturday", "on sunday", "in december", "in january", "this week")),
    ("Goal", ("want to", "goal", "dream", "become", "aim to", "hoping to")),
    ("Weak spot", ("distracted", "procrastinat", "addicted", "can't focus", "struggle", "lazy", "scroll")),
    ("Habit", ("night owl", "morning person", "work best", "usually", "every day", "gym", "music", "i sleep", "i study")),
    ("Preference", ("hate", "don't like", "dont like", "prefer", "love", "please don't", "no pushing")),
    ("Identity", ("i'm a", "i am a", "student", "year", "engineer", "studying", "my name")),
]


def extract_facts(text):
    """Split a self-introduction into categorised facts for the user to confirm."""
    ai = llm.generate(
        "Split this self-introduction into short facts. Return JSON {\"facts\": [{\"category\": one of "
        "Identity|Goal|Habit|Weak spot|Preference|Upcoming, \"text\": short fact in second person, "
        f"\"temporary\": true if it expires soon}}]}}. Text: \"{text}\"", want_json=True)
    if isinstance(ai, dict) and isinstance(ai.get("facts"), list) and ai["facts"]:
        out = []
        for f in ai["facts"][:12]:
            if isinstance(f, dict) and f.get("text"):
                cat = f.get("category") if f.get("category") in dict(CATEGORY_RULES) else "Identity"
                out.append({"category": cat, "text": str(f["text"])[:160], "temporary": bool(f.get("temporary"))})
        if out:
            return out
    parts = [s.strip(" .!") for s in re.split(r"[.!?\n]|,\s*(?:and\s+)?|\band\b", text) if len(s.strip()) > 3]
    facts = []
    for s in parts:
        low = s.lower()
        cat = next((c for c, keys in CATEGORY_RULES if any(k in low for k in keys)), None)
        if not cat:
            continue
        facts.append({"category": cat, "text": s[0].upper() + s[1:], "temporary": cat == "Upcoming"})
    return facts
