#!/usr/bin/env python3
"""
Pantheon Vaultwarden Setup — creates the org, collections, and initial secrets
via the Vaultwarden API directly. Run once after Vaultwarden is deployed.
Uses the standard Bitwarden client-side password hashing.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import urllib.parse
import urllib.request
import uuid

VAULT_URL = os.environ.get("VAULT_URL", "http://127.0.0.1:8222")
ADMIN_EMAIL = "admin@pantheon.local"
ADMIN_PASSWORD = os.environ.get("PANTHEON_VAULT_PASS", "")

# ============================================================
# Password hashing (standard Bitwarden client-side KDF)
# ============================================================

def make_master_password_hash(email: str, password: str, kdf_iter: int = 100000) -> str:
    """Compute the master password hash exactly as Bitwarden clients do."""
    master_key = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), email.lower().encode(), kdf_iter, 32
    )
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", master_key, password.encode(), 1, 32
    )
    return pw_hash.hex()


# ============================================================
# Vaultwarden API client
# ============================================================

class VaultwardenClient:
    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.access_token = None

    def _request(self, method: str, path: str, data=None, headers: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.access_token:
            req_headers["Authorization"] = f"Bearer {self.access_token}"
        if headers:
            req_headers.update(headers)

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()[:500]
            raise RuntimeError(f"HTTP {e.code} on {method} {path}: {err_body}")

    def login(self):
        """OAuth2 password grant login."""
        pw_hash = make_master_password_hash(self.email, self.password)
        device_id = str(uuid.uuid4())
        payload = {
            "grant_type": "password",
            "username": self.email,
            "password": pw_hash,
            "scope": "api offline_access",
            "client_id": "web",
            "deviceType": "2",
            "deviceName": "pantheon-setup",
            "deviceIdentifier": device_id,
        }
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/identity/connect/token",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Auth-Email": self.email,
            },
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            self.access_token = result["access_token"]
            print(f"✓ Logged in as {self.email}")
            return self.access_token

    def create_organization(self, name: str) -> dict:
        """Create a new organization."""
        # Need to generate org keys — for simplicity we create a basic org
        org_data = {
            "name": name,
            "billingEmail": self.email,
            "keys": {
                "publicKey": "",
                "encryptedPrivateKey": "",
            },
        }
        result = self._request("POST", "/api/organizations", org_data)
        print(f"✓ Created organization: {name} (ID: {result.get('id', 'unknown')})")
        return result

    def create_collection(self, org_id: str, name: str) -> dict:
        """Create a collection within an organization."""
        col_data = {
            "organizationId": org_id,
            "name": name,
            "externalId": None,
        }
        result = self._request("POST", f"/api/organizations/{org_id}/collections", col_data)
        print(f"✓ Created collection: {name} (ID: {result.get('id', 'unknown')})")
        return result

    def create_cipher(self, data: dict) -> dict:
        """Create a vault item (cipher)."""
        result = self._request("POST", "/api/ciphers", data)
        print(f"✓ Created cipher: {data.get('name', 'unnamed')}")
        return result


# ============================================================
# Main setup
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Pantheon Vaultwarden Setup")
    print("=" * 60)

    if not ADMIN_PASSWORD:
        # Try to read from .env file
        env_path = os.path.expanduser("~/pantheon/vaultwarden/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("PANTHEON_VAULT_PASS="):
                        ADMIN_PASSWORD = line.strip().split("=", 1)[1]
    
    if not ADMIN_PASSWORD:
        print("ERROR: PANTHEON_VAULT_PASS not set. Export it or set in .env")
        exit(1)

    client = VaultwardenClient(VAULT_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    client.login()

    # Create Pantheon organization
    org = client.create_organization("Pantheon")
    org_id = org["id"]

    # Create collections for each god
    gods = {
        "Hermes": "Infrastructure, ops, cron, gateway config",
        "Thoth": "Research, deep knowledge, codexes, entity extraction",
        "Marvin": "Engineering lead, code, builds, architecture",
        "Hephaestus": "Design, branding, visual assets, CSS/themes",
        "Iris": "Messaging, notifications, social media",
        "Kairos": "Marketing, content, campaigns, SEO",
        "Clara": "Medical client operations, patient data gate",
        "Hades": "Consolidation, archival, night audits",
        "Ichor": "Memory, gates, harness, strategic goals",
    }

    collections = {}
    for god, description in gods.items():
        col = client.create_collection(org_id, god)
        collections[god] = {"id": col["id"], "description": description}

    # Store initial bootstrapping secrets
    # These are the secrets the gods need to bootstrap themselves
    print("\n✓ Vaultwarden structure created!")
    print(f"  Organization: Pantheon ({org_id})")
    print(f"  Collections: {', '.join(collections.keys())}")
    print("\n  Collection IDs:")
    for god, info in collections.items():
        print(f"    {god}: {info['id']}")
    
    # Save the structure
    output = {
        "organization_id": org_id,
        "collections": {k: v["id"] for k, v in collections.items()},
        "user": ADMIN_EMAIL,
    }
    output_path = os.path.expanduser("~/pantheon/vaultwarden/vault-structure.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n✓ Structure saved to {output_path}")
