"""Load a realistic 14-day sample persona so the app feels alive on first launch.

Run:  python -m backend.seed          (resets the database)
"""
import random
from datetime import datetime, timedelta

from . import db

random.seed(7)


def seed(reset=True):
    if reset:
        db.wipe_everything()
    else:
        db.init_db()
    today = datetime.now().replace(second=0, microsecond=0)

    with db.connect() as c:
        c.execute("INSERT OR REPLACE INTO user_profile (id, name, north_star, self_trust) VALUES (1, ?, ?, ?)",
                  ("Riya", "become an ML engineer", 64))

        # 14 past days of watch data + today's rough night
        sleeps = [7.4, 5.3, 7.2, 5.0, 7.6, 4.8, 6.9, 7.5, 7.9, 5.4, 7.1, 5.6, 5.8, 5.1]
        for i, s in enumerate(sleeps):
            d = (today - timedelta(days=14 - i)).date().isoformat()
            rhr = 64 + (4 if s < 6 else 0) + random.randint(-1, 2)
            stress = 55 + (15 if s < 6 else 0) + random.randint(-8, 8)
            c.execute("INSERT OR REPLACE INTO health_logs VALUES (?,?,?,?,?)",
                      (d, s, rhr, random.randint(3500, 11000), stress))
        c.execute("INSERT OR REPLACE INTO health_logs VALUES (?,?,?,?,?)",
                  (today.date().isoformat(), 4.5, 74, 2100, 68))

        # past promises that create honest, learnable patterns
        past = [
            # (days ago, hour, text, est, cap, status)
            (14, 9, "Revise linear algebra notes", 60, 150, "kept"),
            (13, 23, "Finish the whole DBMS assignment tonight", 240, 120, "broken"),
            (12, 10, "Two chapters of OS", 90, 105, "kept"),
            (11, 0, "Watch all remaining ML lectures", 300, 90, "broken"),
            (10, 8, "Solve 6 DSA problems", 90, 135, "kept"),
            (9, 23, "Complete the entire project report", 240, 75, "broken"),
            (8, 18, "Practice 4 aptitude questions sets", 120, 105, "kept"),
            (7, 9, "Read 2 research papers", 90, 150, "kept"),
            (6, 11, "One module of the Coursera course", 60, 150, "kept"),
            (5, 23, "Study five chapters for the internal", 225, 90, "broken"),
            (4, 10, "Code the backprop function", 90, 120, "kept"),
            (3, 0, "Finish the whole lab record", 180, 75, "broken"),
            (2, 9, "Revise 3 topics of CN", 120, 135, "kept"),
            (1, 22, "Finish everything pending for the hackathon", 300, 120, "broken"),
        ]
        for days, hour, text, est, cap, status in past:
            created = (today - timedelta(days=days)).replace(hour=hour, minute=15)
            c.execute(
                "INSERT INTO promises (created_at, original_text, final_text, est_minutes, capacity_minutes, due_at, status, why_text)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (created.isoformat(timespec="minutes"), text, text, est, cap,
                 (created + timedelta(hours=3)).isoformat(timespec="minutes"), status,
                 "I want to actually understand this before my internship interview."))

        facts = [
            ("Identity", "3rd-year CS student", 0),
            ("Goal", "Become an ML engineer", 0),
            ("Habit", "I'm a night owl", 0),
            ("Weak spot", "Gets distracted by Reels", 0),
            ("Preference", "No pushing after 11 PM", 0),
            ("Upcoming", "Internals in two weeks", 1),
        ]
        for cat, text, temp in facts:
            c.execute("INSERT INTO about_me (category, text, temporary, created_at) VALUES (?,?,?,?)",
                      (cat, text, temp, today.isoformat(timespec="minutes")))
    print("Seeded sample persona 'Riya' with 15 days of data.")


if __name__ == "__main__":
    seed(reset=True)
