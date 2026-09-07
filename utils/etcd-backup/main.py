#!/usr/bin/env python3
import gzip
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from minio import Minio
from minio.error import S3Error

# --- Logging Configuration ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("etcd-backup")

# --- Environment & Configuration ---
ETCDCTL_PATH = os.getenv("ETCDCTL_PATH", "/usr/local/bin/etcdctl")
CACERT = os.getenv("ETCD_CACERT", "/etc/kubernetes/pki/etcd/ca.crt")
CERT = os.getenv("ETCD_CERT", "/etc/kubernetes/pki/etcd/healthcheck-client.crt")
KEY = os.getenv("ETCD_KEY", "/etc/kubernetes/pki/etcd/healthcheck-client.key")
ENDPOINTS = os.getenv("ETCD_ENDPOINTS", "https://127.0.0.1:2379")
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "120"))  # seconds

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio.storage.svc.cluster.local:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "etcd-backups")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PREFIX = os.getenv("MINIO_PREFIX", "etcd-snapshots").strip("/")

# Retention: 0 disables automated deletion
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "14"))
ENABLE_COMPRESSION = os.getenv("ENABLE_COMPRESSION", "true").lower() == "true"


def validate_config():
    """Ensure required secrets and files exist before proceeding."""
    missing = []
    if not MINIO_ACCESS_KEY:
        missing.append("MINIO_ACCESS_KEY")
    if not MINIO_SECRET_KEY:
        missing.append("MINIO_SECRET_KEY")

    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    for path, name in [(ETCDCTL_PATH, "etcdctl binary"), (CACERT, "CA Cert"), (CERT, "Client Cert"), (KEY, "Client Key")]:
        if not os.path.isfile(path):
            logger.error(f"Required path '{path}' ({name}) not found.")
            sys.exit(1)


def run_command(cmd: list) -> str:
    """Run shell command with timeout and strict error handling."""
    env = os.environ.copy()
    env["ETCDCTL_API"] = "3"  # Explicitly force API version 3

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            env=env,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {COMMAND_TIMEOUT}s: {' '.join(cmd)}")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exit code {e.returncode}: {' '.join(cmd)}")
        logger.error(f"Stderr: {e.stderr.strip()}")
        raise


def take_snapshot(output_file: str):
    logger.info("Taking etcd snapshot...")
    cmd = [
        ETCDCTL_PATH,
        f"--endpoints={ENDPOINTS}",
        f"--cacert={CACERT}",
        f"--cert={CERT}",
        f"--key={KEY}",
        "snapshot",
        "save",
        output_file,
    ]
    run_command(cmd)
    logger.info(f"Raw snapshot saved ({os.path.getsize(output_file) / (1024 * 1024):.2f} MB)")


def verify_snapshot(snapshot_file: str):
    logger.info("Verifying snapshot integrity...")
    cmd = [
        ETCDCTL_PATH,
        "snapshot",
        "status",
        snapshot_file,
        "--write-out=table",
    ]
    output = run_command(cmd)
    for line in output.splitlines():
        logger.info(line)


def compress_file(src_file: str) -> str:
    dst_file = f"{src_file}.gz"
    logger.info("Compressing snapshot with gzip...")
    with open(src_file, "rb") as f_in:
        with gzip.open(dst_file, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    orig_size = os.path.getsize(src_file) / (1024 * 1024)
    comp_size = os.path.getsize(dst_file) / (1024 * 1024)
    savings = (1 - (comp_size / orig_size)) * 100
    logger.info(f"Compressed from {orig_size:.2f} MB to {comp_size:.2f} MB ({savings:.1f}% reduction)")
    return dst_file


def get_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def upload_to_minio(client: Minio, local_file: str, object_name: str):
    logger.info(f"Target object: '{object_name}' in bucket '{MINIO_BUCKET}'")
    if not client.bucket_exists(MINIO_BUCKET):
        logger.info(f"Bucket '{MINIO_BUCKET}' does not exist. Creating it...")
        client.make_bucket(MINIO_BUCKET)

    client.fput_object(
        bucket_name=MINIO_BUCKET,
        object_name=object_name,
        file_path=local_file,
        content_type="application/gzip" if local_file.endswith(".gz") else "application/octet-stream",
    )
    logger.info("Upload successful.")


def prune_old_snapshots(client: Minio):
    """Delete backups older than RETENTION_DAYS."""
    if RETENTION_DAYS <= 0:
        logger.info("Snapshot pruning disabled (RETENTION_DAYS <= 0).")
        return

    logger.info(f"Checking for snapshots older than {RETENTION_DAYS} days...")
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    
    objects = client.list_objects(MINIO_BUCKET, prefix=f"{MINIO_PREFIX}/", recursive=True)
    for obj in objects:
        if obj.last_modified and obj.last_modified < cutoff:
            logger.info(f"Pruning expired snapshot: {obj.object_name} (Created: {obj.last_modified})")
            client.remove_object(MINIO_BUCKET, obj.object_name)


def main():
    validate_config()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = "db.gz" if ENABLE_COMPRESSION else "db"
    object_name = f"{MINIO_PREFIX}/etcd-snapshot-{timestamp}.{ext}"

    # Use an isolated temp directory that guarantees cleanup
    with tempfile.TemporaryDirectory(prefix="etcd-backup-") as temp_dir:
        raw_snapshot = os.path.join(temp_dir, f"snapshot-{timestamp}.db")

        try:
            take_snapshot(raw_snapshot)
            verify_snapshot(raw_snapshot)

            upload_file = compress_file(raw_snapshot) if ENABLE_COMPRESSION else raw_snapshot
            
            client = get_minio_client()
            upload_to_minio(client, upload_file, object_name)
            prune_old_snapshots(client)

            logger.info("Etcd backup workflow completed successfully.")
        except Exception as e:
            logger.exception(f"Backup failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
