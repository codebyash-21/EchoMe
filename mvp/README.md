# EchoMe MVP – run it locally

A working first version of EchoMe. Everything runs on your own computer: a Python (FastAPI) backend, a local SQLite database and a plain HTML/JavaScript frontend. No account, no cloud.

## Run it (2 minutes)

**Requirements:** Python 3.10 or newer.

**Windows:** double-click `run.bat`

**macOS / Linux:**
```bash
./run.sh
```

**Or manually**, from this `mvp/` folder:
```bash
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000
```

Then open **http://localhost:8000** in your browser.

On first launch, EchoMe loads a 15-day sample persona ("Riya") so every screen has data. Use **My Data → Reload sample data** to reset it anytime.

### Optional: local AI with Ollama
EchoMe works fully offline with built-in rules. To let a local model phrase replies and parse free text:
```bash
# install Ollama from https://ollama.com, then:
ollama pull gemma3:4b
```
Restart EchoMe; the top-right chip changes to **AI: local gemma3:4b**. The model runs on your machine; nothing is sent to the cloud.

### Optional cloud integrations: ElevenLabs + AWS (opt-in)

Both are off by default and never receive raw personal data. Install the extra libraries first:
```bash
pip install -r requirements-cloud.txt
```

**ElevenLabs – Pip's voice.** Set your key, then use **Hear Pip** (Today tab) or **My Data → Test Pip's voice**. A privacy filter strips health numbers and bracketed details before any text is sent.
```bash
# macOS / Linux                                   # Windows (PowerShell)
export ELEVENLABS_API_KEY=your_key               $env:ELEVENLABS_API_KEY="your_key"
export ELEVENLABS_VOICE_ID=optional_voice_id     $env:ELEVENLABS_VOICE_ID="optional_voice_id"
```

**AWS S3 – encrypted backup and restore.** The database is encrypted on your device (PBKDF2 + Fernet/AES with your passphrase) and only the encrypted file is uploaded, with S3 server-side encryption on top. Set a bucket and normal AWS credentials, then use **My Data → Back up now / Restore latest backup**.
```bash
export ECHOME_S3_BUCKET=your-bucket-name
export AWS_REGION=ap-south-1
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...   # or use ~/.aws/credentials
```
Without a bucket, the encrypted backup is saved locally in `data/backups/` so the feature still works offline.

## 2-minute demo script

1. **Today tab:** Pip looks groggy, capacity is LOW after a 4.5h night.
2. Type **"I'll study five chapters tonight"** → **Check it**. EchoMe explains your capacity and suggests *"Do 1 chapter… and the other 4 tomorrow morning"*. Click **Accept suggestion**.
3. **Record your why** (allow the microphone) or type it → **Save my why**.
4. Click **"I'm gonna give up"** → **PROTECT**: the promise moves to tomorrow with no penalty.
5. Click **Watch sync → Rested**, make a new promise, record a why, then click **Simulate: 40 min on YouTube** → **PUSH**: your own recorded voice plays back.
6. Mark a promise **✓ Kept** → self-trust goes up (no streaks).
7. **Manual tab:** rules learned from your history, plus a *said vs. data* insight. Confirm one, then **Export .md**.
8. **About Me tab:** paste a short self-introduction → **Understand this** → confirm the facts.
9. **My Data tab:** see that everything is local, export JSON, or **Forget everything**.
10. **My Data → Optional cloud:** see exactly what would be sent to ElevenLabs after the privacy filter, test Pip's voice, and make an encrypted backup (to AWS S3 if configured), then restore it with your passphrase.

Typing *"I feel hopeless"* triggers **GENTLE** mode: Push turns off and EchoMe suggests support (Tele-MANAS 14416).

## What's inside

```
mvp/
├── backend/
│   ├── main.py      FastAPI app: API routes + serves the frontend
│   ├── engine.py    capacity score, promise negotiation, Push/Protect/Gentle, manual rules, About Me parsing
│   ├── llm.py       optional local Ollama client with safe fallback
│   ├── cloud.py     opt-in ElevenLabs voice + AWS S3 encrypted backup/restore
│   ├── db.py        SQLite schema and helpers (data/echome.db)
│   └── seed.py      15-day sample persona
├── frontend/        index.html, style.css, app.js (no build step)
├── sample_data/     health_export_sample.csv (try Watch sync → Import CSV)
├── requirements.txt
├── requirements-cloud.txt   optional: cryptography + boto3
├── run.bat / run.sh
└── data/            created on first run: database + voice clips (git-ignored)
```

## How the logic works (short)

- **Capacity:** compares today's sleep, resting heart rate and stress with your own 14-day baseline → a score → focused minutes (blended with how much you actually finished on similar past days).
- **Negotiation:** estimates the effort of your promise (e.g. 5 chapters ≈ 225 min) and, if it exceeds capacity, scales it down and adds an if-then plan.
- **Modes:** distress words → **Gentle**; giving-up words or a distraction → **Protect** if your body is depleted, otherwise **Push** with your own why-clip.
- **Manual:** simple statistics over your promise history (late-night promises, sleep vs. keep rate, morning focus, oversized promises). Rules appear only when the data supports them.

## MVP limits (honest)

- Watch data comes from the simulator or a CSV export; direct Health Connect / Apple Health sync needs a mobile app (next step).
- Activity tracking is simulated with the "40 min on YouTube" button; ActivityWatch integration is planned.
- Speech-to-text (faster-whisper) for spoken promises is planned; today you type promises and record why-clips as audio.
