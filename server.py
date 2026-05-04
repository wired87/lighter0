from typing import Optional, List, Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field


class AuthInput(BaseModel):
    """Auth block: user_id and session_id."""

    user_id: str = Field(default="public", description="User identifier")
    session_id: Optional[str] = Field(default=None, description="Session identifier")


class DataInput(BaseModel):
    """Data block: text (message) and optional files."""

    text: str = Field(default="", description="User message for classification")
    files: List[Any] = Field(default_factory=list, description="Optional file refs")



class CreatePayload(BaseModel):
    """Full relay payload: auth, data, type."""
    auth: AuthInput = Field(default_factory=AuthInput)
    data: DataInput = Field(default_factory=DataInput)




app = FastMCP(title="lighter0", version="1.0.0")



@app.post("/create", operation_id="relay_entry")
async def relay_entry(body: CreatePayload) -> Any:
    """
    Entry for Thalamus: receives relay payload, classifies type if None, dispatches handler.
    """
    try:
        payload = _to_relay_payload(body)
        user_id = (body.auth.user_id or "").strip() or "public"
        session_id = (body.auth.session_id or "").strip() or None

        orch = _get_orchestrator()
        result = await orch.handle_relay_payload(
            payload=payload,
            user_id=user_id,
            session_id=session_id,
        )
        return result if result is not None else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




