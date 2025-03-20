from pydantic import BaseModel, Field

class OrganizationModel(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    address: str
    total_employees: int = Field(default=0, ge=0)  # Default is 0, min value is 0
    emp_count: int = Field(..., ge = 1)