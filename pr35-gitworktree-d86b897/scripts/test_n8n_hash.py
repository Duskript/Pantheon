import subprocess
import sqlite3

# Step 1: Generate hash INSIDE the container  
result = subprocess.run(
    ['sg', 'docker', '-c', 
     r"""docker exec n8n sh -c 'cd /usr/local/lib/node_modules/n8n && node -e "const bcrypt = require(\"bcryptjs\"); console.log(bcrypt.hashSync(\"olympus2026\", 10));"'"""],
    capture_output=True, text=True
)
hash_output = result.stdout.strip()
print(f"Generated hash: [{hash_output}]")

# Step 2: Verify inside the container using a temp file to avoid shell escaping
verify_script = f'const bcrypt = require("bcryptjs"); console.log(bcrypt.compareSync("olympus2026", "{hash_output}"));'
result2 = subprocess.run(
    ['sg', 'docker', '-c', 
     f'docker exec n8n node -e \'{verify_script}\''],
    capture_output=True, text=True,
    cwd='/usr/local/lib/node_modules/n8n'  # This won't work since it's on the host
)
print(f"Verify stdout: [{result2.stdout.strip()}]")
print(f"Verify stderr: [{result2.stderr.strip()}]")
