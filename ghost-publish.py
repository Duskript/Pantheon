#!/usr/bin/env python3
"""
Ghost CMS Publisher — push articles to blog.theoforgesolutions.com via Admin API
Usage:  python3 ghost-publish.py <title> <file.md>
        python3 ghost-publish.py --draft <title> <file.md>
        python3 ghost-publish.py --list
        python3 ghost-publish.py --status
"""

import sys, os, json, time, hmac, hashlib, base64, urllib.request, urllib.error, argparse, mimetypes
from pathlib import Path

GHOST_URL = os.environ.get("GHOST_ADMIN_URL", "https://blog.theoforgesolutions.com").rstrip("/")

# Admin API key resolution — NEVER hardcode a key in this file.
# Order: 1) $GHOST_ADMIN_API_KEY  2) ~/.hermes/ghost-admin-key (0600)  3) /etc/pantheon/ghost-admin-key
_KEY_FILES = (
    Path.home() / ".hermes" / "ghost-admin-key",
    Path("/etc/pantheon/ghost-admin-key"),
)


def _resolve_api_key():
    """Return the Ghost Admin API key as '<id>:<secret>' or exit with instructions."""
    key = (os.environ.get("GHOST_ADMIN_API_KEY") or "").strip()
    if not key:
        for candidate in _KEY_FILES:
            try:
                if candidate.is_file():
                    key = candidate.read_text().strip()
                    if key:
                        break
            except OSError:
                continue
    if not key or ":" not in key:
        raise SystemExit(
            "Ghost Admin API key not found. Set GHOST_ADMIN_API_KEY (id:secret) or write it "
            "to ~/.hermes/ghost-admin-key — see the relay7-ghost-blog-posting skill."
        )
    return key


def b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def make_jwt():
    """Generate a Ghost Admin API JWT"""
    kid, secret = _resolve_api_key().split(":", 1)
    iat = int(time.time())
    exp = iat + 300  # 5 minutes
    header = b64encode(json.dumps({"alg": "HS256", "kid": kid, "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64encode(json.dumps({"iat": iat, "exp": exp, "aud": "/admin/"}, separators=(",", ":")).encode())
    msg = f"{header}.{payload}"
    # Ghost Admin API secrets are hex-encoded. Signing with secret.encode()
    # produces INVALID_JWT even when the key is correct.
    sig = b64encode(hmac.new(bytes.fromhex(secret), msg.encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"

def _read_json_response(resp):
    """Decode a Ghost Admin API response body into JSON.

    Ghost answers successful ``DELETE`` (and some ``PUT``) requests with
    ``204 No Content`` — an empty body, not JSON. Calling ``json.loads("")``
    raises ``Expecting value: line 1 column 1 (char 0)`` and the caller reports
    a failed call even though the server already applied the change. An empty
    body therefore maps to a success envelope carrying the HTTP status.

    Args:
        resp: An open ``http.client.HTTPResponse`` from ``urlopen``.

    Returns:
        The decoded JSON object, or ``{"ok": True, "status": <int>}`` when the
        body is empty/whitespace.
    """
    raw = resp.read().decode()
    if not raw.strip():
        return {"ok": True, "status": getattr(resp, "status", None)}
    return json.loads(raw)


def api(method, path, data=None):
    """Make an Admin API call"""
    token = make_jwt()
    url = f"{GHOST_URL}/ghost/api/admin/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Ghost {token}",
        "Content-Type": "application/json",
        "Accept-Version": "v5.0",
        "User-Agent": "Hermes-Kairos/1.0"
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return _read_json_response(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def upload_image(image_path):
    """Upload a local image to Ghost and return its public URL."""
    path = Path(str(image_path)).expanduser()
    if not path.exists():
        return {"error": f"feature image not found: {path}"}
    token = make_jwt()
    boundary = f"----HermesGhostImage{int(time.time() * 1000)}"
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = path.read_bytes()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{GHOST_URL}/ghost/api/admin/images/upload/",
        data=body,
        headers={
            "Authorization": f"Ghost {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept-Version": "v5.0",
            "User-Agent": "Hermes-Kairos/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:300]
        return {"error": f"HTTP {e.code}: {body_text}"}
    except Exception as e:
        return {"error": str(e)}
    image = (result.get("images") or [{}])[0]
    url = image.get("url") or image.get("src")
    if not url:
        return {"error": f"Ghost image upload returned no URL: {str(result)[:300]}"}
    return {"ok": True, "url": url, "result": result}

def list_posts():
    """List all posts"""
    result = api("GET", "posts/?limit=50&include=tags")
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    posts = result.get("posts", [])
    if not posts:
        print("No posts found.")
        return
    for p in posts:
        status = "📝" if p["status"] == "draft" else "✅"
        print(f"  {status} {p['title']} ({p['slug']}) — {p['status']}")

def create_post(title, markdown_path, publish=True, feature_image=None):
    """Create a post from a markdown file"""
    try:
        with open(markdown_path) as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: file not found: {markdown_path}")
        return
    
    # Convert markdown to Ghost HTML (basic conversion)
    html_lines = []
    for line in content.split("\n"):
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[2:]}</h3>")
        elif line.strip() == "":
            html_lines.append("")
        else:
            html_lines.append(f"<p>{line}</p>")
    
    html = "\n".join(html_lines)
    
    post = {
        "title": title,
        "html": html,
        "status": "published" if publish else "draft",
    }
    if feature_image:
        image_value = str(feature_image)
        if image_value.startswith(("http://", "https://")):
            post["feature_image"] = image_value
        else:
            uploaded = upload_image(image_value)
            if "error" in uploaded:
                print(f"Error: feature image upload failed: {uploaded['error']}")
                return
            post["feature_image"] = uploaded["url"]
            print(f"   Feature image: {uploaded['url']}")
    post_data = {"posts": [post]}
    
    result = api("POST", "posts/", post_data)
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    
    post = result.get("posts", [{}])[0]
    url = f"{GHOST_URL}/{post.get('slug', '')}/"
    label = "Published" if post.get("status") == "published" else "Draft created"
    print(f"✅ {label}: {post.get('title')}")
    print(f"   URL: {url}")
    print(f"   Status: {post.get('status')}")
    return post

def site_status():
    """Check blog health"""
    settings = api("GET", "settings/")
    if "error" in settings:
        print(f"Error: {settings['error']}")
        return
    for s in settings.get("settings", []):
        if s["key"] in ("title", "description", "accent_color", "timezone"):
            print(f"  {s['key']}: {s['value']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ghost CMS Publisher")
    parser.add_argument("--list", action="store_true", help="List posts")
    parser.add_argument("--status", action="store_true", help="Show blog status")
    parser.add_argument("--draft", action="store_true", help="Save as draft (don't publish)")
    parser.add_argument("--feature-image", help="Local image path or public URL to use as the Ghost featured image")
    parser.add_argument("title", nargs="?", help="Post title")
    parser.add_argument("file", nargs="?", help="Markdown file path")
    
    args = parser.parse_args()
    
    if args.list:
        list_posts()
    elif args.status:
        site_status()
    elif args.title and args.file:
        create_post(args.title, args.file, publish=not args.draft, feature_image=args.feature_image)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python3 ghost-publish.py --status")
        print("  python3 ghost-publish.py --list")
        print('  python3 ghost-publish.py "My Post" /path/to/post.md')
        print('  python3 ghost-publish.py --draft --feature-image /path/to/hero.png "Draft" /path/to/draft.md')
