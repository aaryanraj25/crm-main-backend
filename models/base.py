from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class TimeStampedModel(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None