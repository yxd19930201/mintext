from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization


PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAh6ragAUdXS6aNxBt94gqXvGaLNXvLVKy+Aij9sGNjWo=
-----END PUBLIC KEY-----
"""


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _machine_guid() -> str:
    if os.name != "nt":
        return os.getenv("HOSTNAME", "unknown")
    try:
        import winreg
        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:
        return os.getenv("COMPUTERNAME", "unknown")


def machine_code() -> str:
    mac = f"{uuid.getnode():012X}"
    material = f"MINITEXT|{_machine_guid()}|{mac}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest().upper()[:24]
    return "MT-" + "-".join(digest[index:index + 4] for index in range(0, 24, 4))


def _license_path() -> Path:
    data_dir = Path(os.getenv("MINITEXT_DATA_DIR", Path(os.getenv("APPDATA", ".")) / "Mintext" / "server-data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "license.json"


def verify_license(license_key: str) -> dict:
    parts = license_key.strip().split(".")
    if len(parts) != 3 or parts[0] != "MINITEXT1":
        raise ValueError("激活码格式不正确")
    payload_bytes = _b64decode(parts[1])
    signature = _b64decode(parts[2])
    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
    public_key.verify(signature, payload_bytes)
    payload = json.loads(payload_bytes.decode("utf-8"))
    if payload.get("product") != "minitext":
        raise ValueError("激活码不属于本产品")
    if payload.get("machine_code") != machine_code():
        raise ValueError("激活码与本机机器码不匹配")
    expires_at_raw = payload.get("expires_at")
    if not expires_at_raw:
        raise ValueError("该激活码没有有效期，请联系卖家更换时效激活码")
    expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        raise ValueError("授权已到期，请联系卖家续费")
    return payload


def status() -> dict:
    code = machine_code()
    if os.getenv("MINITEXT_LICENSE_BYPASS") == "1":
        return {"activated": True, "machine_code": code, "license_id": "development"}
    path = _license_path()
    if not path.exists():
        return {"activated": False, "machine_code": code, "message": "软件尚未激活"}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        payload = verify_license(saved["license_key"])
        now = datetime.now(timezone.utc)
        last_seen_raw = saved.get("last_seen_at")
        if last_seen_raw:
            last_seen = datetime.fromisoformat(last_seen_raw.replace("Z", "+00:00"))
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if now < last_seen - timedelta(minutes=5):
                raise ValueError("检测到系统时间异常，请校准系统时间后重试")
        saved["last_seen_at"] = now.isoformat()
        path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        days_remaining = max(0, (expires_at - now).days + (1 if (expires_at - now).seconds else 0))
        return {
            "activated": True,
            "machine_code": code,
            "license_id": payload.get("license_id"),
            "issued_at": payload.get("issued_at"),
            "expires_at": payload.get("expires_at"),
            "days_remaining": days_remaining,
        }
    except Exception as exc:
        return {"activated": False, "machine_code": code, "message": str(exc) or "本机授权无效，请重新激活"}


def activate(license_key: str) -> dict:
    payload = verify_license(license_key)
    path = _license_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({
        "license_key": license_key.strip(),
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return {
        "activated": True,
        "machine_code": machine_code(),
        "license_id": payload.get("license_id"),
        "issued_at": payload.get("issued_at"),
        "expires_at": payload.get("expires_at"),
        "days_remaining": max(1, (datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).days + 1),
    }
