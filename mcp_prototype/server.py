"""Local-only, read-only MCP prototype. Never mount this in the production app."""
import os
from mcp.server.fastmcp import FastMCP

# Fail closed: require explicit opt-in and an isolated test database.
if os.getenv('WSBCO_MCP_DEV_ONLY') != '1':
    raise RuntimeError('Set WSBCO_MCP_DEV_ONLY=1 for isolated local development')
if os.getenv('WSBCO_MCP_SYNTHETIC_DATA') != '1':
    raise RuntimeError('Synthetic-data confirmation required')
from sqlalchemy import select
from app.database import SessionLocal
from app.call_list_v1 import candidates, selection_reason, active_batch
from app.golf_integration import GolfProfile
from app.models import Lead

mcp = FastMCP("WSBCO CRM - local read-only prototype")

@mcp.tool()
def preview_call_candidates(limit: int = 10) -> list[dict]:
    """Preview eligible manual calls without creating or replacing a batch."""
    limit = max(1, min(int(limit), 10))
    with SessionLocal() as db:
        return [
            {"contact_id": lead.id, "name": f"{lead.first_name} {lead.last_name}".strip(),
             "reason": selection_reason(lead), "status": lead.status}
            for lead in candidates(db)[:limit]
        ]

@mcp.tool()
def list_golf_inquiries(limit: int = 10) -> list[dict]:
    """List existing golf inquiries without exposing phone or email."""
    limit = max(1, min(int(limit), 25))
    with SessionLocal() as db:
        rows = db.execute(select(GolfProfile, Lead).join(
            Lead, Lead.id == GolfProfile.lead_id
        ).order_by(GolfProfile.id.desc()).limit(limit)).all()
        return [
            {"contact_id": lead.id, "name": f"{lead.first_name} {lead.last_name}".strip(),
             "stage": profile.stage, "program": profile.program}
            for profile, lead in rows
        ]

if __name__ == "__main__":
    # stdio is local development only; no network listener or remote authentication.
    mcp.run()
