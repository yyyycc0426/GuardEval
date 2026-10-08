import os
import json
import logging
from pathlib import Path

logger = logging.getLogger("llm_security_platform.gcs_store")

# Configuration from environment variables
GCS_BUCKET_NAME = os.environ.get("LLM_SECURITY_GCS_BUCKET", "")
LOCAL_FALLBACK_DIR = Path(os.environ.get("LLM_SECURITY_LOCAL_STORAGE_DIR", "reports/gcs_fallback"))

class GCSStore:
    def __init__(self):
        self.bucket_name = GCS_BUCKET_NAME
        self.client = None
        self.use_gcs = False

        if self.bucket_name:
            try:
                from google.cloud import storage
                # Initialize storage client using Application Default Credentials (ADC)
                self.client = storage.Client()
                self.use_gcs = True
                logger.info(f"Google Cloud Storage initialized successfully on bucket: {self.bucket_name}")
            except Exception as exc:
                logger.warning(f"Failed to initialize Google Cloud Storage client ({exc}). Falling back to local storage.")
        else:
            logger.info("LLM_SECURITY_GCS_BUCKET environment variable not set. Using local fallback storage.")

        if not self.use_gcs:
            LOCAL_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(LOCAL_FALLBACK_DIR, 0o700)
            except Exception:
                pass

    def _cleanup_old_local_files(self):
        """
        Scans LOCAL_FALLBACK_DIR and removes JSON files older than retention days (default 7).
        """
        try:
            import time
            retention_days = int(os.environ.get("LLM_SECURITY_LOCAL_RETENTION_DAYS", "7"))
            cutoff = time.time() - (retention_days * 86400)
            
            for root, dirs, files in os.walk(LOCAL_FALLBACK_DIR):
                for file in files:
                    if file.endswith(".json"):
                        file_path = Path(root) / file
                        if file_path.stat().st_mtime < cutoff:
                            try:
                                file_path.unlink()
                                logger.info(f"Cleaned up old local report: {file_path}")
                            except Exception as e:
                                logger.debug(f"Failed to delete old report {file_path}: {e}")
        except Exception as exc:
            logger.debug(f"Error during local files cleanup: {exc}")

    def upload_file(self, source_path: str | Path, destination_blob_name: str) -> str:
        """
        Uploads a file. If GCP GCS is active, uploads to bucket. Otherwise, saves to local fallback directory.
        Returns the storage URI or local file path.
        """
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        if self.use_gcs:
            try:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob(destination_blob_name)
                blob.upload_from_filename(str(source_path))
                gcs_uri = f"gs://{self.bucket_name}/{destination_blob_name}"
                logger.info(f"File uploaded successfully to GCS: {gcs_uri}")
                return gcs_uri
            except Exception as exc:
                logger.error(f"GCS upload failed: {exc}. Trying local fallback.")
                # fall through to local fallback

        # Local fallback execution
        dest_path = LOCAL_FALLBACK_DIR / destination_blob_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(dest_path.parent, 0o700)
        except Exception:
            pass
        import shutil
        shutil.copy2(source_path, dest_path)
        logger.info(f"File copied successfully to local fallback: {dest_path}")
        self._cleanup_old_local_files()
        return str(dest_path)

    def upload_json(self, data: dict, destination_blob_name: str) -> str:
        """
        Serializes and uploads a dictionary as JSON.
        """
        if self.use_gcs:
            try:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob(destination_blob_name)
                blob.upload_from_string(json.dumps(data, indent=2, ensure_ascii=False), content_type="application/json")
                gcs_uri = f"gs://{self.bucket_name}/{destination_blob_name}"
                logger.info(f"JSON uploaded successfully to GCS: {gcs_uri}")
                return gcs_uri
            except Exception as exc:
                logger.error(f"GCS JSON upload failed: {exc}. Trying local fallback.")
                # fall through to local fallback

        # Local fallback
        dest_path = LOCAL_FALLBACK_DIR / destination_blob_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(dest_path.parent, 0o700)
        except Exception:
            pass
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"JSON saved successfully to local fallback: {dest_path}")
        self._cleanup_old_local_files()
        return str(dest_path)

    def download_file(self, blob_name: str, destination_path: str | Path) -> bool:
        """
        Downloads a file/blob to the destination path.
        """
        destination_path = Path(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if self.use_gcs:
            try:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob(blob_name)
                blob.download_to_filename(str(destination_path))
                logger.info(f"Downloaded from GCS gs://{self.bucket_name}/{blob_name} to {destination_path}")
                return True
            except Exception as exc:
                logger.error(f"GCS download failed for {blob_name}: {exc}")
                # fall through to local fallback

        # Local fallback
        local_source = LOCAL_FALLBACK_DIR / blob_name
        if local_source.exists():
            import shutil
            shutil.copy2(local_source, destination_path)
            logger.info(f"Copied from local fallback {local_source} to {destination_path}")
            return True
        logger.warning(f"File not found in GCS or local fallback: {blob_name}")
        return False

# Global instance for easy import and reuse
gcs_store = GCSStore()
