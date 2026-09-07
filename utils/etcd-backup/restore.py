#!/usr/bin/env python3
import argparse
import gzip
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from minio import Minio
from minio.error import S3Error

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("etcd-restore")

# --- Configuration from Environment ---
ETCDCTL_PATH = os.getenv("ETCDCTL_PATH", "/usr/local/bin/etcdctl")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio.example.com:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "etcd-backups")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PREFIX = os.getenv("MINIO_PREFIX", "etcd-snapshots").strip("/")


def get_minio_client() -> Minio:
    if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
        logger.error("MINIO_ACCESS_KEY and MINIO_SECRET_KEY environment variables must be set.")
        sys.exit(1)

    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def list_snapshots(client: Minio):
    """List all available snapshots in MinIO ordered by date."""
    prefix = f"{MINIO_PREFIX}/" if MINIO_PREFIX else ""
    objects = client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True)
    
    snapshots = [
        obj for obj in objects 
        if obj.object_name.endswith((".db", ".db.gz"))
    ]
    snapshots.sort(key=lambda x: x.last_modified, reverse=True)
    return snapshots


def decompress_gzip(src_file: str, dst_file: str):
    logger.info(f"Decompressing {src_file} -> {dst_file}...")
    with gzip.open(src_file, "rb") as f_in:
        with open(dst_file, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)


def verify_snapshot(snapshot_file: str):
    logger.info("Verifying snapshot integrity with etcdctl...")
    env = os.environ.copy()
    env["ETCDCTL_API"] = "3"

    cmd = [ETCDCTL_PATH, "snapshot", "status", snapshot_file, "--write-out=table"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        for line in res.stdout.strip().splitlines():
            logger.info(line)
    except FileNotFoundError:
        logger.warning(f"'{ETCDCTL_PATH}' not found. Skipping local integrity validation.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Snapshot integrity check failed: {e.stderr.strip()}")
        sys.exit(1)


def download_snapshot(client: Minio, object_name: str, target_dir: str) -> str:
    os.makedirs(target_dir, exist_ok=True)
    base_name = os.path.basename(object_name)
    download_path = os.path.join(target_dir, base_name)

    logger.info(f"Downloading s3://{MINIO_BUCKET}/{object_name} -> {download_path}...")
    client.fget_object(MINIO_BUCKET, object_name, download_path)

    # Decompress if gzip
    if download_path.endswith(".gz"):
        uncompressed_path = download_path[:-3]  # remove .gz
        decompress_gzip(download_path, uncompressed_path)
        os.remove(download_path)
        final_path = uncompressed_path
    else:
        final_path = download_path

    verify_snapshot(final_path)
    return final_path


def main():
    parser = argparse.ArgumentParser(description="Fetch and prepare etcd snapshots from MinIO.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List available snapshots in MinIO")
    group.add_argument("--latest", action="store_true", help="Fetch the most recent snapshot")
    group.add_argument("--snapshot", type=str, help="Specific snapshot object name to fetch")
    
    parser.add_argument("--output-dir", default="/var/lib/etcd-restore", help="Destination folder (default: /var/lib/etcd-restore)")
    args = parser.parse_args()

    client = get_minio_client()

    if args.list:
        snaps = list_snapshots(client)
        if not snaps:
            print("No snapshots found.")
            return

        print(f"\nAvailable snapshots in '{MINIO_BUCKET}':")
        print(f"{'Object Name':<60} {'Size (MB)':<12} {'Created (UTC)'}")
        print("-" * 95)
        for s in snaps:
            size_mb = f"{s.size / (1024 * 1024):.2f}"
            date_str = s.last_modified.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{s.object_name:<60} {size_mb:<12} {date_str}")
        print()
        return

    selected_object = None
    if args.latest:
        snaps = list_snapshots(client)
        if not snaps:
            logger.error("No snapshots found in bucket.")
            sys.exit(1)
        selected_object = snaps[0].object_name
        logger.info(f"Selected latest snapshot: {selected_object}")
    elif args.snapshot:
        selected_object = args.snapshot

    final_file = download_snapshot(client, selected_object, args.output_dir)

    print("\n" + "=" * 65)
    print(f"SUCCESS: Snapshot prepared and ready at:\n  --> {final_file}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
