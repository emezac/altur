from pydantic import BaseModel, ConfigDict
from datetime import datetime

class CallUploadResponse(BaseModel):
    call_id: str
    status: str
    filename: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)
