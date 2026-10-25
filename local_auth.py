"""Single local user account for the desktop installation."""
import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USER_FILE = ROOT / 'data' / 'local_user.json'
ITERATIONS = 310_000
_LOCK = threading.RLock()


def _read():
    try:
        value = json.loads(USER_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def has_user():
    with _LOCK:
        return _read() is not None


def create_user(data):
    username = str(data.get('username') or '').strip().lower()
    display_name = ' '.join(str(data.get('name') or '').split())
    password = str(data.get('password') or '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,31}', username):
        raise ValueError('O usuário deve ter de 3 a 32 caracteres: letras, números, ponto, hífen ou sublinhado.')
    if len(display_name) < 2 or len(display_name) > 60:
        raise ValueError('Informe um nome de exibição de 2 a 60 caracteres.')
    if len(password) < 10 or len(password) > 200:
        raise ValueError('A senha deve ter de 10 a 200 caracteres.')
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS)
    user = {'username': username, 'name': display_name, 'salt': salt.hex(), 'password_hash': digest.hex(),
            'iterations': ITERATIONS}
    with _LOCK:
        if _read() is not None:
            raise ValueError('Este computador já tem um usuário cadastrado. Entre com esse usuário.')
        USER_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = USER_FILE.with_suffix('.tmp')
        temp.write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, USER_FILE)
    return {'username': username, 'name': display_name}


def verify_user(username, password):
    username = str(username or '').strip().lower()
    password = str(password or '')
    with _LOCK:
        user = _read()
    if not user or user.get('username') != username:
        # Keep an invalid username close to the real-password verification cost.
        hashlib.pbkdf2_hmac('sha256', password[:200].encode('utf-8'), b'historias-studio-local-auth', ITERATIONS)
        return None
    try:
        actual = hashlib.pbkdf2_hmac('sha256', password[:200].encode('utf-8'), bytes.fromhex(user['salt']),
                                     int(user.get('iterations', ITERATIONS))).hex()
        if not hmac.compare_digest(actual, user['password_hash']):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return {'username': username, 'name': user.get('name') or username}
