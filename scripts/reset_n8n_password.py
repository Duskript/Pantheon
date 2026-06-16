import subprocess
import sqlite3

# Generate the bcrypt hash using the n8n container
result = subprocess.run(
    ['sg', 'docker', '-c', 
     "docker exec n8n sh -c 'cd /usr/local/lib/node_modules/n8n && node -e \"const bcrypt = require(\\\"bcryptjs\\\"); console.log(bcrypt.hashSync(\\\"olympus2026\\\", 10));\"'"],
    capture_output=True, text=True
)

hash_output = result.stdout.strip()
print(f"Generated hash: {hash_output}")

# Verify the hash
verify = subprocess.run(
    ['sg', 'docker', '-c', 
     f'docker exec n8n sh -c \'cd /usr/local/lib/node_modules/n8n && node -e "const bcrypt = require(\\"bcryptjs\\"); console.log(bcrypt.compareSync(\\"olympus2026\\", \\"{hash_output}\\"));"\''],
    capture_output=True, text=True
)
print(f"Verify: {verify.stdout.strip()}")

# Update the database
db = sqlite3.connect('/home/konan/n8n-data/database.sqlite')
db.execute("UPDATE user SET password = ? WHERE email = 'admin@pantheon.local'", (hash_output,))
db.commit()

cursor = db.execute("SELECT password FROM user WHERE email = 'admin@pantheon.local'")
stored = cursor.fetchone()[0]
print(f"Stored: {stored}")
print(f"Match: {stored == hash_output}")
db.close()