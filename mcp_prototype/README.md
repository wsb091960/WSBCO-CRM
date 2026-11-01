# Read-only MCP prototype (development branch only)

This prototype is **not mounted** in the production FastAPI application and does not change requirements.txt or Render deployment settings.

## Local development

Install the application's existing dependencies in an isolated development environment, then install a reviewed, pinned version of the MCP Python SDK v2.

Run from repository root:

```bash
python -m mcp_prototype.server
```

This uses MCP stdio (local process only), **not a public HTTP endpoint**. Do not connect it to real customer/student data until authorization, data minimization, audit logging, and a security review are completed.

Tools are read-only by intent; database connections currently use the application's configured database. For testing, explicitly configure a disposable synthetic SQLite database before importing the server. Never run against production as a test.

## Next gates
1. Unit tests using synthetic SQLite records, including empty results and max limits.
2. Verify no database writes, transactions, or schema migrations.
3. Validate permission boundaries and audit logs.
4. Implement OAuth/scoped authorization before any remotely accessible Streamable HTTP endpoint.
5. Review privacy handling and require explicit approval before any production connection.

No production deployment or database migration is part of this prototype.
