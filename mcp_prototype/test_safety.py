"""Static safety regression checks; run: python -m unittest discover -s mcp_prototype -p 'test_*.py'"""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("server.py")

class MCPPrototypeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_local_stdio_only(self):
        self.assertIn("mcp.run()", self.source)
        self.assertNotIn("streamable-http", self.source)
        self.assertNotIn("uvicorn.run", self.source)

    def test_explicit_synthetic_data_gate(self):
        self.assertIn("WSBCO_MCP_DEV_ONLY", self.source)
        self.assertIn("WSBCO_MCP_SYNTHETIC_DATA", self.source)

    def test_no_explicit_database_mutations(self):
        prohibited = {"commit", "flush", "delete", "add", "add_all", "execute_write"}
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call)]
        methods = {n.func.attr for n in calls if isinstance(n.func, ast.Attribute)}
        self.assertFalse(methods & prohibited, methods & prohibited)

    def test_no_network_requests(self):
        self.assertNotIn("httpx", self.source)
        self.assertNotIn("requests.", self.source)
        self.assertNotIn("urlopen", self.source)

if __name__ == "__main__":
    unittest.main()
