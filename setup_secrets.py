"""
One-time setup script: creates the Databricks secret scope and stores the
Lakebase URL (base64-encoded). Run this locally with the Databricks CLI configured.

Usage:
    python setup_secrets.py
"""

import base64
import getpass
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import workspace

w = WorkspaceClient()

scope_name = "database"
try:
    w.secrets.create_scope(scope=scope_name)
    print(f"✅ Scope '{scope_name}' created.")
except Exception as e:
    if "already exists" in str(e).lower():
        print(f"ℹ️ Scope '{scope_name}' already exists.")
    else:
        raise

print("\n📋 Paste your Lakebase connection URL.")
print("Format: postgresql://role:password@host:5432/database?sslmode=require")
raw_url = getpass.getpass("Lakebase URL: ")
encoded_url = base64.b64encode(raw_url.encode("utf-8")).decode("utf-8")

w.secrets.put_secret(
    scope=scope_name,
    key="lakebase-url",
    string_value=encoded_url
)
print(f"✅ Secret 'lakebase-url' stored in scope '{scope_name}'.")

try:
    w.secrets.put_acl(
        scope=scope_name,
        principal="users",
        permission=workspace.AclPermission.READ,
    )
    print(f"✅ Read permission granted to 'users' on scope '{scope_name}'.")
except Exception as e:
    print(f"⚠️ Could not set ACL: {e} (you can ignore if you're the only user).")

print("\n🎉 Setup complete! Your app can now connect to Lakebase.")