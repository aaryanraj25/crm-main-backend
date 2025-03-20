from pydantic import BaseModel, EmailStr, Field

class AdminModel(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=3, max_length=100)
    phone: str = Field(..., pattern="^[0-9]{10}$")
    organization: str  # ✅ Add this if you need the name
    
    address: str
    emp_count: int = Field(..., ge=1)
    is_verified: bool = False
class SetPasswordRequest(BaseModel):
    email: EmailStr
    password: str