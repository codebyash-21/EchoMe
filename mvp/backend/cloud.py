"""Optional, opt-in cloud features. EchoMe works fully without them.

- ElevenLabs Text-to-Speech: a voice for Pip's replies. A privacy filter removes health numbers
  and bracketed details before any text leaves the device.
- AWS S3 encrypted backup: the database is encrypted ON THE DEVICE with a key derived from the
  user's passphrase, and only the encrypted file is uploaded. AWS cannot read it.

Configure with environment variables (see mvp/README.md):
  ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID (optional)
  ECHOME_S3_BUCKET, AWS_REGION (optional) + standard AWS credentials (env vars or ~/.aws)
"""
import base64
import json
import os
import re
import shutil
import urllib.request
from datetime import datetime

from . import db

BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")
MAGIC = b"ECHOME1"
S3_PREFIX = "echome-backups/"

# ----------------------------------------------------------------------------- privacy filter
SENSITIVE = re.compile(r"\(.*?\)|\b\d+(\.\d+)?\s*(h\b|hours?\b|hrs?\b|bpm\b|%|/100|steps\b|kg\b)", re.I)


def privacy_filter(text: str) -> str:
    """Remove health values and bracketed details before any text leaves the device."""
    t = SENSITIVE.sub("", text)
    t = re.sub(r"\s{2,}", " ", t).replace(" ,", ",").replace(" .", ".").replace(" :", ":").replace(" ;", ";")
    t = re.sub(r"[:;]\s*[,;:]", ":", t)
    return t.strip()


# ----------------------------------------------------------------------------- ElevenLabs
def elevenlabs_configured() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def elevenlabs_tts(text: str):
    """Return MP3 bytes from ElevenLabs, or None (caller falls back to the device voice)."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    body = json.dumps({"text": privacy_filter(text)[:600], "model_id": "eleven_multilingual_v2"}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}", data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except Exception:
        return None


# ----------------------------------------------------------------------------- encryption (on device)
def _crypto():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        return Fernet, hashes, PBKDF2HMAC
    except ImportError:
        return None


def crypto_available() -> bool:
    return _crypto() is not None


def _key(passphrase: str, salt: bytes) -> bytes:
    Fernet, hashes, PBKDF2HMAC = _crypto()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def encrypt_database(passphrase: str) -> bytes:
    Fernet, _, _ = _crypto()
    salt = os.urandom(16)
    with open(db.DB_PATH, "rb") as f:
        token = Fernet(_key(passphrase, salt)).encrypt(f.read())
    return MAGIC + salt + token


def decrypt_backup(blob: bytes, passphrase: str) -> bytes:
    from cryptography.fernet import InvalidToken
    Fernet, _, _ = _crypto()
    if not blob.startswith(MAGIC):
        raise ValueError("Not an EchoMe backup file")
    salt, token = blob[len(MAGIC):len(MAGIC) + 16], blob[len(MAGIC) + 16:]
    try:
        return Fernet(_key(passphrase, salt)).decrypt(token)
    except InvalidToken:
        raise ValueError("Wrong passphrase")


# ----------------------------------------------------------------------------- AWS S3
def _s3():
    bucket = os.environ.get("ECHOME_S3_BUCKET")
    if not bucket:
        return None, None
    try:
        import boto3
    except ImportError:
        return None, bucket
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return boto3.client("s3", region_name=region) if region else boto3.client("s3"), bucket


def s3_status():
    bucket = os.environ.get("ECHOME_S3_BUCKET")
    try:
        import boto3  # noqa: F401
        has_boto = True
    except ImportError:
        has_boto = False
    return {"configured": bool(bucket and has_boto), "bucket": bucket, "boto3": has_boto}


def backup(passphrase: str):
    """Encrypt on device, then upload to S3 if configured; otherwise keep the encrypted file locally."""
    blob = encrypt_database(passphrase)
    name = f"echome-{datetime.now().strftime('%Y%m%d-%H%M%S')}.enc"
    client, bucket = _s3()
    if client:
        client.put_object(Bucket=bucket, Key=S3_PREFIX + name, Body=blob,
                          ServerSideEncryption="AES256", ContentType="application/octet-stream")
        return {"stored": "aws-s3", "location": f"s3://{bucket}/{S3_PREFIX}{name}", "bytes": len(blob)}
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(os.path.join(BACKUP_DIR, name), "wb") as f:
        f.write(blob)
    return {"stored": "local", "location": f"data/backups/{name}", "name": name, "bytes": len(blob)}


def _latest_blob():
    client, bucket = _s3()
    if client:
        objs = client.list_objects_v2(Bucket=bucket, Prefix=S3_PREFIX).get("Contents", [])
        if not objs:
            raise ValueError("No backups found in S3")
        latest = max(objs, key=lambda o: o["LastModified"])
        return client.get_object(Bucket=bucket, Key=latest["Key"])["Body"].read(), f"s3://{bucket}/{latest['Key']}"
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".enc")) if os.path.isdir(BACKUP_DIR) else []
    if not files:
        raise ValueError("No backups found")
    with open(os.path.join(BACKUP_DIR, files[-1]), "rb") as f:
        return f.read(), f"data/backups/{files[-1]}"


def restore(passphrase: str, blob: bytes | None = None):
    """Decrypt a backup (latest, or an uploaded file) and replace the local database."""
    source = "uploaded file"
    if blob is None:
        blob, source = _latest_blob()
    plain = decrypt_backup(blob, passphrase)
    if not plain.startswith(b"SQLite format 3"):
        raise ValueError("Backup is damaged")
    tmp = db.DB_PATH + ".restore"
    with open(tmp, "wb") as f:
        f.write(plain)
    shutil.move(tmp, db.DB_PATH)
    return {"restored_from": source}
