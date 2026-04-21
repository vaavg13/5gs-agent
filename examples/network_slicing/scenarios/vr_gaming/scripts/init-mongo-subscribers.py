#!/usr/bin/env python3
"""Initialize MongoDB with Open5GS subscriber data.

This script reads subscriber data from a YAML file and provisions it
into MongoDB using the Open5GS subscriber document schema.
"""

import os
import sys
import time
import socket
import subprocess

# Install required packages
print("Installing required packages...")
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pymongo", "pyyaml"])

import yaml
from pymongo import MongoClient

MONGO_HOST = os.environ.get('MONGO_HOST', 'mongo')
MONGO_DB = os.environ.get('MONGO_DB', 'open5gs')
INPUT_FILE = '/etc/open5gs/subscribers.yaml'


def wait_for_mongodb(host: str, port: int = 27017, timeout: int = 120) -> bool:
    """Wait for MongoDB to be reachable."""
    print(f"Waiting for MongoDB at {host}:{port}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                print("MongoDB is reachable")
                return True
        except Exception:
            pass
        print(f"  Waiting... ({int(time.time() - start_time)}s)")
        time.sleep(2)
    return False


def build_subscriber_document(sub: dict) -> dict:
    """Build an Open5GS subscriber document from YAML data."""
    imsi = sub.get('imsi', '')
    k = sub.get('k', '')
    opc = sub.get('opc', '')
    amf_val = sub.get('amf', '8000')
    sst = sub.get('sst', 1)
    sd_raw = sub.get('sd', '0x000001')

    # Convert SD to 6-digit hex string format (Open5GS expects string "000001")
    if isinstance(sd_raw, str) and sd_raw.startswith('0x'):
        sd = f"{int(sd_raw, 16):06d}"
    elif isinstance(sd_raw, int):
        sd = f"{sd_raw:06d}"
    else:
        sd = "000001"

    apn = sub.get('apn', 'internet')

    return {
        "imsi": imsi,
        "msisdn": [],
        "imeisv": [],
        "mme_host": [],
        "mme_realm": [],
        "purge_flag": [],
        "security": {
            "k": k,
            "amf": amf_val,
            "op": None,
            "opc": opc
        },
        "ambr": {
            "downlink": {"value": 1, "unit": 3},
            "uplink": {"value": 1, "unit": 3}
        },
        "slice": [
            {
                "sst": sst,
                "sd": sd,
                "default_indicator": True,
                "session": [
                    {
                        "name": apn,
                        "type": 3,
                        "dnn": apn,
                        "qos": {
                            "index": 9,
                            "arp": {
                                "priority_level": 8,
                                "pre_emption_capability": 1,
                                "pre_emption_vulnerability": 1
                            }
                        },
                        "ambr": {
                            "downlink": {"value": 1, "unit": 3},
                            "uplink": {"value": 1, "unit": 3}
                        }
                    }
                ]
            }
        ],
        "access_restriction_data": 32,
        "subscriber_status": 0,
        "network_access_mode": 0
    }


def main():
    # Wait for MongoDB
    if not wait_for_mongodb(MONGO_HOST):
        print("ERROR: MongoDB did not become reachable in time")
        sys.exit(1)

    # Give MongoDB a moment to fully initialize
    time.sleep(3)

    # Connect to MongoDB
    try:
        client = MongoClient(f"mongodb://{MONGO_HOST}:27017")
        db = client[MONGO_DB]
        collection = db.subscribers
        print(f"Connected to MongoDB: {MONGO_HOST}/{MONGO_DB}")
    except Exception as e:
        print(f"ERROR: Failed to connect to MongoDB: {e}")
        sys.exit(1)

    # Load subscribers from YAML
    try:
        with open(INPUT_FILE) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: {INPUT_FILE} not found, skipping")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: Failed to read {INPUT_FILE}: {e}")
        sys.exit(1)

    subscribers = data.get('subscribers', [])
    print(f"Found {len(subscribers)} subscribers to provision")

    # Provision each subscriber
    for sub in subscribers:
        if sub.get('status') != 'active':
            print(f"Skipping inactive subscriber: {sub.get('imsi')}")
            continue

        imsi = sub.get('imsi', '')
        doc = build_subscriber_document(sub)

        try:
            result = collection.update_one(
                {"imsi": imsi},
                {"$set": doc},
                upsert=True
            )
            if result.upserted_id:
                print(f"  Added subscriber: {imsi}")
            else:
                print(f"  Updated subscriber: {imsi}")
        except Exception as e:
            print(f"  ERROR provisioning {imsi}: {e}")

    print("Subscriber provisioning complete!")


if __name__ == "__main__":
    main()
