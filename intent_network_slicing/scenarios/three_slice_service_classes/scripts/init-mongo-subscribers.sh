#!/bin/bash
# init-mongo-subscribers.sh - Provision Open5GS subscribers into MongoDB
# Uses open5gs-dbctl to add subscribers
set -e

MONGO_HOST="${MONGO_HOST:-mongo}"
MONGO_DB="${MONGO_DB:-open5gs}"
INPUT_FILE="/etc/open5gs/subscribers.yaml"
DB_URI="mongodb://${MONGO_HOST}/${MONGO_DB}"

echo "Provisioning subscribers from $INPUT_FILE..."
echo "Database URI: $DB_URI"

# Export for Python script
export DB_URI MONGO_HOST INPUT_FILE

# Use Python to wait for MongoDB, parse YAML, and add subscribers
python3 << 'PYTHON_SCRIPT'
import yaml
import subprocess
import os
import sys
import time
import socket

MONGO_HOST = os.environ.get('MONGO_HOST', 'mongo')
DB_URI = os.environ.get('DB_URI', 'mongodb://mongo/open5gs')
INPUT_FILE = os.environ.get('INPUT_FILE', '/etc/open5gs/subscribers.yaml')

# Wait for MongoDB to be reachable on port 27017
print(f"Waiting for MongoDB at {MONGO_HOST}:27017...")
max_attempts = 60
for attempt in range(max_attempts):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((MONGO_HOST, 27017))
        sock.close()
        if result == 0:
            print("MongoDB is reachable")
            break
    except Exception as e:
        pass
    print(f"  Waiting... (attempt {attempt + 1}/{max_attempts})")
    time.sleep(2)
else:
    print("ERROR: MongoDB did not become reachable")
    sys.exit(1)

# Give MongoDB a moment to fully initialize
time.sleep(5)

# Load subscribers
try:
    with open(INPUT_FILE) as f:
        data = yaml.safe_load(f)
except FileNotFoundError:
    print(f"Warning: {INPUT_FILE} not found, skipping")
    sys.exit(0)
except Exception as e:
    print(f"Error reading {INPUT_FILE}: {e}")
    sys.exit(1)

subscribers = data.get('subscribers', [])
print(f"Found {len(subscribers)} subscribers to provision")

for sub in subscribers:
    if sub.get('status') != 'active':
        print(f"Skipping inactive subscriber {sub.get('imsi')}")
        continue

    imsi = sub.get('imsi', '')
    k = sub.get('k', '')
    opc = sub.get('opc', '')

    # open5gs-dbctl add <imsi> <k> <opc>
    cmd = ['open5gs-dbctl', '--db_uri', DB_URI, 'add', imsi, k, opc]
    print(f"Adding subscriber: {imsi}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  Success: {imsi}")
    else:
        stderr = result.stderr.strip().lower()
        stdout = result.stdout.strip().lower()
        # Check if subscriber already exists
        if 'already' in stderr or 'already' in stdout or 'duplicate' in stderr:
            print(f"  Already exists: {imsi}")
        else:
            print(f"  Output: {result.stdout.strip()}")
            print(f"  Error: {result.stderr.strip()}")

print("Subscriber provisioning complete")
PYTHON_SCRIPT

echo "Done!"
