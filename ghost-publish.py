#!/usr/bin/env python3
"""
Ghost CMS Publisher — push articles to blog.theoforgesolutions.com via Admin API
Usage:  python3 ghost-publish.py <title> <file.md>
        python3 ghost-publish.py --draft <title> <file.md>
        python3 ghost-publish.py --list
        python3 ghost-publish.py --status
"""

import sys, json, time, hmac, hashlib, base64, urllib.request, urllib.error, argparse

GHOST_URL = "https://blog.theoforgesolutions.com"
API_KEY = "b2c3d4e5f6a7b8c9d0e1f2a3:edaa37b8708fa472d6c6ed4f65e8240b971a4b7fbc6fc81c79405c162918bf9c"

def b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def make_jwt():
    """Generate a Ghost Admin API JWT"""
    kid, secret = API_KEY.split(":", 1)
    iat = int(time.time())
    exp = iat + 300  # 5 minutes
    header = b64encode(json.dumps({"alg": "HS256", "kid": kid, "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64encode(json.dumps({"iat": iat, "exp": exp, "aud": "/admin/"}, separators=(",", ":")).encode())
    msg = f"{header}.{payload}"
    # Ghost Admin API secrets are hex-encoded. Signing with secret.encode()
    # produces INVALID_JWT even when the key is correct.
    sig = b64encode(hmac.new(bytes.fromhex(secret), msg.encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"

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
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}

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

def create_post(title, markdown_path, publish=True):
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
    
    post_data = {
        "posts": [{
            "title": title,
            "html": html,
            "status": "published" if publish else "draft",
        }]
    }
    
    result = api("POST", "posts/", post_data)
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    
    post = result.get("posts", [{}])[0]
    url = f"{GHOST_URL}/{post.get('slug', '')}/"
    print(f"✅ Published: {post.get('title')}")
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
    parser.add_argument("title", nargs="?", help="Post title")
    parser.add_argument("file", nargs="?", help="Markdown file path")
    
    args = parser.parse_args()
    
    if args.list:
        list_posts()
    elif args.status:
        site_status()
    elif args.title and args.file:
        create_post(args.title, args.file, publish=not args.draft)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python3 ghost-publish.py --status")
        print("  python3 ghost-publish.py --list")
        print('  python3 ghost-publish.py "My Post" /path/to/post.md')
        print('  python3 ghost-publish.py --draft "Draft" /path/to/draft.md')
