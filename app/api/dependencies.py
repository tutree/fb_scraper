from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.core.config import settings
from app.core.database import get_db
from app.models.admin import AdminUser
from app.schemas.auth import TokenData

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login/access-token"
)

def get_current_admin(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> AdminUser:
    """Authenticate any logged-in user (admin or user role)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
        
    admin_user = db.query(AdminUser).filter(AdminUser.username == token_data.username).first()
    if admin_user is None:
        raise credentials_exception
    return admin_user


def require_admin(
    current_user: AdminUser = Depends(get_current_admin),
) -> AdminUser:
    """Require the 'admin' role. Returns 403 for regular users."""
    if (current_user.role or "user") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# Re-export get_db as the primary dependency
__all__ = ["get_db", "get_current_admin", "require_admin"]
