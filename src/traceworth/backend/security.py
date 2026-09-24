"""Password and token primitives; raw API/session credentials never persist."""
import hashlib
import hmac
import secrets
from collections import defaultdict, deque
from threading import Lock
from time import monotonic


def digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def password_hash(password):
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f'scrypt${salt}${derived.hex()}'


def verify_password(password, stored):
    _, salt, expected = stored.split('$')
    actual = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


class AuthLimiter:
    """Bounded in-process limit; restart resets it (local MVP, single worker)."""
    def __init__(self):
        self.entries = defaultdict(deque)
        self.lock = Lock()

    def allow(self, identity):
        now = monotonic()
        with self.lock:
            expired = [key for key, values in self.entries.items() if not values or values[-1] <= now - 60]
            for key in expired:
                del self.entries[key]
            if identity not in self.entries and len(self.entries) >= 4096:
                return False
            values = self.entries[identity]
            while values and values[0] <= now - 60:
                values.popleft()
            if len(values) >= 10:
                return False
            values.append(now)
            return True
