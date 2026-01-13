"""
Media Uploader - uploads files to remote server for Instagram publishing.

Instagram Graph API requires public URLs for media. This module uploads
local files to a remote server and returns the public URL.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import uuid

logger = logging.getLogger(__name__)


@dataclass
class UploaderConfig:
    """Configuration for media uploader."""
    ssh_host: str
    ssh_user: str
    ssh_key_path: Path
    remote_path: str
    public_base_url: str
    ssh_port: int = 22


class MediaUploader:
    """
    Uploads media files to remote server via SCP.

    Files are uploaded with unique names to avoid collisions.
    Server should have a cleanup cron to delete old files.
    """

    def __init__(self, config: UploaderConfig):
        """
        Initialize uploader.

        Args:
            config: Upload configuration
        """
        self.config = config

    def upload_file(self, local_path: Path, preserve_name: bool = False) -> Optional[str]:
        """
        Upload file to remote server.

        Args:
            local_path: Path to local file
            preserve_name: If True, keep original filename; otherwise generate unique name

        Returns:
            Public URL of uploaded file, or None on failure
        """
        if not local_path.exists():
            logger.error(f"File not found: {local_path}")
            return None

        # Generate unique filename to avoid collisions
        if preserve_name:
            remote_filename = local_path.name
        else:
            ext = local_path.suffix
            remote_filename = f"{uuid.uuid4().hex[:12]}{ext}"

        remote_file = f"{self.config.remote_path}/{remote_filename}"

        try:
            # Build SCP command
            cmd = [
                "scp",
                "-i", str(self.config.ssh_key_path),
                "-P", str(self.config.ssh_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes",
                str(local_path),
                f"{self.config.ssh_user}@{self.config.ssh_host}:{remote_file}",
            ]

            logger.debug(f"Uploading {local_path.name} to {remote_file}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.error(f"SCP failed: {result.stderr}")
                return None

            # Set permissions for nginx to read
            chmod_cmd = [
                "ssh",
                "-i", str(self.config.ssh_key_path),
                "-p", str(self.config.ssh_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes",
                f"{self.config.ssh_user}@{self.config.ssh_host}",
                f"chmod 644 {remote_file}",
            ]
            subprocess.run(chmod_cmd, capture_output=True, timeout=10)

            # Return public URL
            public_url = f"{self.config.public_base_url}/{remote_filename}"
            logger.info(f"Uploaded {local_path.name} -> {public_url}")
            return public_url

        except subprocess.TimeoutExpired:
            logger.error("Upload timeout")
            return None
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return None

    def upload_video(self, video_path: Path) -> Optional[str]:
        """Upload video file and return public URL."""
        return self.upload_file(video_path)

    def upload_image(self, image_path: Path) -> Optional[str]:
        """Upload image file and return public URL."""
        return self.upload_file(image_path)

    def ensure_remote_dir(self) -> bool:
        """
        Ensure remote directory exists.

        Returns:
            True if directory exists or was created
        """
        try:
            cmd = [
                "ssh",
                "-i", str(self.config.ssh_key_path),
                "-p", str(self.config.ssh_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes",
                f"{self.config.ssh_user}@{self.config.ssh_host}",
                f"mkdir -p {self.config.remote_path} && chmod 755 {self.config.remote_path}",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                logger.info(f"Remote directory ready: {self.config.remote_path}")
                return True
            else:
                logger.error(f"Failed to create remote dir: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"SSH error: {e}")
            return False

    def test_connection(self) -> bool:
        """
        Test SSH connection to server.

        Returns:
            True if connection successful
        """
        try:
            cmd = [
                "ssh",
                "-i", str(self.config.ssh_key_path),
                "-p", str(self.config.ssh_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                f"{self.config.ssh_user}@{self.config.ssh_host}",
                "echo 'OK'",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if result.returncode == 0 and "OK" in result.stdout:
                logger.info("SSH connection test passed")
                return True
            else:
                logger.error(f"SSH connection failed: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"SSH test error: {e}")
            return False


def get_uploader_config() -> UploaderConfig:
    """
    Get uploader config from environment.

    Returns:
        UploaderConfig with values from .env
    """
    import os
    from pathlib import Path

    return UploaderConfig(
        ssh_host=os.getenv("MEDIA_SSH_HOST", "188.137.182.43"),
        ssh_user=os.getenv("MEDIA_SSH_USER", "root"),
        ssh_key_path=Path(os.getenv("MEDIA_SSH_KEY", "/home/alex/-=TRANSLATOR=-/.ssh/zomro.pem")),
        remote_path=os.getenv("MEDIA_REMOTE_PATH", "/opt/translator/tours-media"),
        public_base_url=os.getenv("MEDIA_PUBLIC_URL", "https://adatranslate.com/tours-media"),
        ssh_port=int(os.getenv("MEDIA_SSH_PORT", "22")),
    )


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    config = get_uploader_config()
    uploader = MediaUploader(config)

    print("Testing SSH connection...")
    if uploader.test_connection():
        print("Connection OK!")

        print("\nEnsuring remote directory...")
        if uploader.ensure_remote_dir():
            print("Directory ready!")
        else:
            print("Failed to create directory")
    else:
        print("Connection FAILED!")
