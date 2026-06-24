from pydantic import BaseModel


class AuthDTO(BaseModel):
    login: str
    password: str


class RegisterDTO(AuthDTO):
    email: str | None = None
    notify_recommendations: bool = False
