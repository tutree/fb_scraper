from pydantic import BaseModel
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str = "user"

class TokenData(BaseModel):
    username: Optional[str] = None
    role: str = "user"

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str
