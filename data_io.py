"""Wczytywanie i zapis data.json. Wspiera GitHub Contents API + bezpieczny lokalny fallback.

P0 fixes (audyt):
- atomic write (tmp + os.replace) zamiast truncate-then-write,
- sanityzacja komunikatu błędu (nie wycieka body GitHub API do UI),
- audit log każdego save → audit_log.jsonl,
- hmac.compare_digest na hasło admina, brak hardcoded fallbacka,
- session timeout 30 min.
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import requests
import streamlit as st

logger = logging.getLogger("konkurs.data_io")

DATA_FILE = "data.json"
AUDIT_LOG = "audit_log.jsonl"
SESSION_TIMEOUT_MIN = 30


def _gh_headers() -> dict:
    token = st.secrets.get("github_token", "")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


@st.cache_data(ttl=60, show_spinner=False)
def load_data() -> Tuple[dict, Optional[str]]:
    """Wczytuje data.json. Zwraca (data, sha) - sha to None gdy lokalnie."""
    repo = st.secrets.get("github_repo", "")
    if repo:
        url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}"
        try:
            r = requests.get(url, headers=_gh_headers(), timeout=10)
            if r.ok:
                j = r.json()
                content = base64.b64decode(j["content"]).decode("utf-8")
                return json.loads(content), j["sha"]
            logger.warning("GitHub load failed: %s", r.status_code)
        except Exception as exc:
            logger.exception("GitHub load error: %s", exc)
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return {}, None


def _atomic_local_write(payload: bytes, path: str = DATA_FILE) -> None:
    """Atomic write: zapis do tmp w tym samym katalogu, potem os.replace.

    Crash w połowie nie niszczy istniejącego pliku.
    """
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _append_audit(action: str, info: dict) -> None:
    """Dopisuje wpis do audit_log.jsonl. Nie wyrzuca błędu jeśli IO padnie."""
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "action": action,
        "info": info,
    }
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("audit log write failed")


def save_data(data: dict, sha: Optional[str]) -> Tuple[bool, str]:
    """Zapisuje data.json. Najpierw GitHub (jeśli skonfigurowane), potem lokalny atomic write.

    Zwraca (ok, msg_dla_uzytkownika). Pełne błędy idą do logów, nie do UI.
    """
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    repo = st.secrets.get("github_repo", "")

    if repo and sha:
        url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}"
        body = {
            "message": f"update [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
            "content": base64.b64encode(payload).decode(),
            "sha": sha,
            "committer": {"name": "KonkursBot", "email": "bot@konkurs.pl"},
        }
        try:
            r = requests.put(url, headers=_gh_headers(), json=body, timeout=15)
            if r.ok:
                load_data.clear()
                _invalidate_derived_caches()
                _append_audit("save_github", {"sha_old": sha, "bytes": len(payload)})
                return True, "Zapisano do GitHub ✓"
            if r.status_code == 409:
                logger.warning("GitHub 409 conflict (sha=%s)", sha)
                load_data.clear()
                return False, (
                    "Konflikt zapisu (ktoś inny zapisał równolegle). "
                    "Strona zostanie odświeżona — sprawdź czy Twoje zmiany trzeba ponowić."
                )
            logger.error("GitHub save failed status=%s body=%s", r.status_code, r.text[:500])
            return False, f"Błąd zapisu GitHub (HTTP {r.status_code}). Szczegóły w logach."
        except requests.RequestException as exc:
            logger.exception("GitHub network error: %s", exc)
            return False, "Błąd sieci przy zapisie do GitHub. Szczegóły w logach."

    try:
        _atomic_local_write(payload)
        load_data.clear()
        _invalidate_derived_caches()
        _append_audit("save_local", {"bytes": len(payload)})
        return True, "Zapisano lokalnie ✓"
    except Exception as exc:
        logger.exception("local atomic write failed: %s", exc)
        return False, "Błąd zapisu lokalnego. Szczegóły w logach."


def _invalidate_derived_caches() -> None:
    """Po save_data czyść cache build_history / build_hourly_history (memory leak fix)."""
    try:
        from history import _build_history_cached, _build_hourly_history_cached
        _build_history_cached.clear()
        _build_hourly_history_cached.clear()
    except Exception:
        logger.exception("derived cache invalidation failed")


def verify_admin(pwd: str) -> bool:
    """Bezpieczne porównanie hasła. Brak fallbacku - bez secret = brak admina.

    Wymaga st.secrets["admin_password"] albo zmiennej środowiskowej
    KONKURS_ADMIN_PASSWORD.
    """
    expected = st.secrets.get("admin_password") or os.environ.get(
        "KONKURS_ADMIN_PASSWORD"
    )
    if not expected:
        return False
    return hmac.compare_digest(str(pwd or ""), str(expected))


def admin_session_active() -> bool:
    """Czy sesja admina jeszcze ważna (≤ SESSION_TIMEOUT_MIN od logowania)."""
    if not st.session_state.get("admin_ok"):
        return False
    login_ts = st.session_state.get("admin_login_ts")
    if not login_ts:
        return False
    try:
        login_dt = datetime.fromisoformat(login_ts)
    except (TypeError, ValueError):
        return False
    return datetime.utcnow() - login_dt < timedelta(minutes=SESSION_TIMEOUT_MIN)


def admin_login() -> None:
    """Loguje admina w session_state z timestampem."""
    st.session_state.admin_ok = True
    st.session_state.admin_login_ts = datetime.utcnow().isoformat(timespec="seconds")
    _append_audit("admin_login", {"ts": st.session_state.admin_login_ts})


def admin_logout() -> None:
    _append_audit("admin_logout", {})
    st.session_state.admin_ok = False
    st.session_state.pop("admin_login_ts", None)


def data_hash(data: dict) -> str:
    """SHA256 z payloadu data.json - używane jako checksum w raporcie KNF."""
    import hashlib
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def load_audit_log(limit: int = 500) -> list[dict]:
    """Zwraca ostatnie N wpisów z audit_log.jsonl."""
    path = Path(AUDIT_LOG)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
