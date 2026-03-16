from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.config import settings
from app.api.dependencies import get_db, get_current_admin
from app.core.security import verify_password, create_access_token, get_password_hash
from app.models.admin import AdminUser
from app.schemas.auth import Token, PasswordUpdate

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Token:
    """OAuth2 compatible token login, get an access token for future requests"""
    user = db.query(AdminUser).filter(AdminUser.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=create_access_token(
            user.username,
            role=user.role or "user",
            expires_delta=access_token_expires,
        ),
        token_type="bearer",
        role=user.role or "user",
    )

@router.get("/me")
def get_current_user_info(
    current_admin: AdminUser = Depends(get_current_admin),
):
    return {"username": current_admin.username, "role": current_admin.role or "user"}


@router.post("/update-password")
def update_password(
    password_data: PasswordUpdate,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Update current admin password"""
    if not verify_password(password_data.current_password, current_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password",
        )
    
    current_admin.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    db.refresh(current_admin)
    return {"msg": "Password updated successfully"}
