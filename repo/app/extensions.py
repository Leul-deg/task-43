from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
jwt = JWTManager()
csrf = CSRFProtect()

def _rate_limit_key():
    try:
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            return str(identity)
    except Exception:
        pass
    return get_remote_address()

limiter = Limiter(key_func=_rate_limit_key)
