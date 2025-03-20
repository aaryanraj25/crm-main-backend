from pydantic import BaseModel, EmailStr

class SuperAdmin(BaseModel):
    email: EmailStr
    password: str