from pydantic import BaseModel


class UserInfoDTO(BaseModel):
    login: str
    role: str
