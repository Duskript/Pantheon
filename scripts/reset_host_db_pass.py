import subprocess
import sqlite3

# Generate hash with host n8n's bcryptjs
result = subprocess.run(
    ['node', '-e', 
     "const bcrypt = require('bcryptjs'); console.log(bcrypt.hashSync('olympus2026', 10));"],
    capture_output=True, text=True,
    cwd='/home/konan/.npm-global/lib/node_modules/.n8n-UAEjPYqq'
)
hash_output = result.stdout.strip()
print(f"Hash: {hash_output}")

# Update the CORRECT host database
db = sqlite3.connect('/home/konan/n8n-data/.n8n/database.sqlite')
db.execute("UPDATE user SET password = ? WHERE email = ?", (hash_output, 'admin@pantheon.local'))
db.commit()

row = db.execute("SELECT email FROM user WHERE email = ?", ('admin@pantheon.local',)).fetchone()
print(f"User updated: {row[0]}")
db.close()