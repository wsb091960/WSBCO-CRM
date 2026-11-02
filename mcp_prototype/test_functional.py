"""Functional tests using only synthetic SQLite records."""
import os
import tempfile
import unittest
from pathlib import Path

class CRMMCPFunctionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="wsbco-mcp-crm-")
        cls.root = Path(cls.temp.name)
        (cls.root / ".wsbco-mcp-synthetic").touch()
        os.environ["WSBCO_MCP_DEV_ONLY"] = "1"
        os.environ["WSBCO_MCP_SYNTHETIC_DATA"] = "1"
        os.environ["WSBCO_MCP_TEST_DIR"] = str(cls.root)
        os.environ["CRM_DATA_DIR"] = str(cls.root)
        from app import models
        from app.database import Base, engine, SessionLocal
        from app import call_list_v1, golf_integration
        Base.metadata.create_all(engine)
        cls.models, cls.SessionLocal = models, SessionLocal
        cls.GolfProfile = golf_integration.GolfProfile
        from mcp_prototype import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_candidate_and_golf_inquiry_without_writes(self):
        from sqlalchemy import select, func
        m = self.models
        with self.SessionLocal() as db:
            db.add(m.Lead(id=1001, first_name="Synthetic", last_name="Caller",
                          phone="5415550101", status="New"))
            db.add(m.Lead(id=1002, first_name="Synthetic", last_name="DNC",
                          phone="5415550102", status="Do Not Call"))
            db.add(self.GolfProfile(lead_id=1001, stage="Inquiry", program="Lesson"))
            db.commit()
            before = (db.scalar(select(func.count()).select_from(m.Lead)),
                      db.scalar(select(func.count()).select_from(self.GolfProfile)))
        candidates = self.server.preview_call_candidates(limit=10)
        inquiries = self.server.list_golf_inquiries(limit=10)
        self.assertTrue(any(x["contact_id"] == 1001 for x in candidates))
        self.assertFalse(any(x["contact_id"] == 1002 for x in candidates))
        self.assertEqual(inquiries[0]["program"], "Lesson")
        self.assertNotIn("phone", str(candidates) + str(inquiries))
        with self.SessionLocal() as db:
            after = (db.scalar(select(func.count()).select_from(m.Lead)),
                     db.scalar(select(func.count()).select_from(self.GolfProfile)))
        self.assertEqual(before, after)
