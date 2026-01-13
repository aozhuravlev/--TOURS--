"""
Instagram Publisher using Graph API.

Publishes content to Instagram Business account:
- Stories (video)
- Feed posts (photo + caption)

Requires:
- Instagram Business Account
- Facebook Page connected to Instagram
- Access token with required permissions
"""

import logging
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


@dataclass
class PublishResult:
    """Result of publish operation."""
    success: bool
    media_id: Optional[str] = None
    error: Optional[str] = None


class InstagramPublisher:
    """
    Publishes content to Instagram via Graph API.

    Flow for publishing:
    1. Upload media to get container ID
    2. Publish container
    """

    def __init__(
        self,
        access_token: str,
        instagram_account_id: str,
        timeout: int = 120,
        max_retries: int = 3,
    ):
        """
        Initialize publisher.

        Args:
            access_token: Facebook/Instagram access token
            instagram_account_id: Instagram Business Account ID
            timeout: Request timeout in seconds
            max_retries: Number of retries on failure
        """
        self.access_token = access_token
        self.account_id = instagram_account_id
        self.timeout = timeout
        self.max_retries = max_retries

        self.client = httpx.Client(timeout=timeout)

    def publish_story(
        self,
        video_url: str,
        caption: Optional[str] = None,
    ) -> PublishResult:
        """
        Publish video story to Instagram.

        Note: Video must be accessible via public URL.
        For local files, you need to upload to a hosting service first.

        Args:
            video_url: Public URL of the video
            caption: Optional caption (shown briefly)

        Returns:
            PublishResult with media_id on success
        """
        logger.info(f"Publishing story from: {video_url}")

        # Step 1: Create media container
        container_id = self._create_video_container(
            video_url=video_url,
            media_type="STORIES",
            caption=caption,
        )

        if not container_id:
            return PublishResult(success=False, error="Failed to create media container")

        # Step 2: Wait for processing
        if not self._wait_for_processing(container_id):
            return PublishResult(success=False, error="Video processing timeout")

        # Step 3: Publish
        media_id = self._publish_container(container_id)

        if media_id:
            logger.info(f"Story published: {media_id}")
            return PublishResult(success=True, media_id=media_id)
        else:
            return PublishResult(success=False, error="Failed to publish container")

    def publish_post(
        self,
        image_url: str,
        caption: str,
    ) -> PublishResult:
        """
        Publish photo post to Instagram feed.

        Args:
            image_url: Public URL of the image
            caption: Post caption (including hashtags)

        Returns:
            PublishResult with media_id on success
        """
        logger.info(f"Publishing post from: {image_url}")

        # Step 1: Create media container
        container_id = self._create_image_container(
            image_url=image_url,
            caption=caption,
        )

        if not container_id:
            return PublishResult(success=False, error="Failed to create media container")

        # Step 2: Publish
        media_id = self._publish_container(container_id)

        if media_id:
            logger.info(f"Post published: {media_id}")
            return PublishResult(success=True, media_id=media_id)
        else:
            return PublishResult(success=False, error="Failed to publish container")

    def _create_video_container(
        self,
        video_url: str,
        media_type: str = "STORIES",
        caption: Optional[str] = None,
    ) -> Optional[str]:
        """Create video media container."""
        params = {
            "media_type": media_type,
            "video_url": video_url,
            "access_token": self.access_token,
        }
        if caption:
            params["caption"] = caption

        try:
            response = self.client.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media",
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            container_id = data.get("id")

            logger.debug(f"Created video container: {container_id}")
            return container_id

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create video container: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error creating video container: {e}")
            return None

    def _create_image_container(
        self,
        image_url: str,
        caption: str,
    ) -> Optional[str]:
        """Create image media container."""
        params = {
            "image_url": image_url,
            "caption": caption,
            "access_token": self.access_token,
        }

        try:
            response = self.client.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media",
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            container_id = data.get("id")

            logger.debug(f"Created image container: {container_id}")
            return container_id

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create image container: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error creating image container: {e}")
            return None

    def _wait_for_processing(
        self,
        container_id: str,
        max_wait: int = 60,
        poll_interval: int = 5,
    ) -> bool:
        """
        Wait for video to finish processing.

        Args:
            container_id: Media container ID
            max_wait: Maximum wait time in seconds
            poll_interval: Time between status checks

        Returns:
            True if processing completed successfully
        """
        elapsed = 0

        while elapsed < max_wait:
            status = self._get_container_status(container_id)

            if status == "FINISHED":
                logger.debug("Video processing finished")
                return True
            elif status == "ERROR":
                logger.error("Video processing failed")
                return False

            time.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning("Video processing timeout")
        return False

    def _get_container_status(self, container_id: str) -> str:
        """Get status of media container."""
        try:
            response = self.client.get(
                f"{GRAPH_API_BASE}/{container_id}",
                params={
                    "fields": "status_code",
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()

            data = response.json()
            return data.get("status_code", "UNKNOWN")

        except Exception as e:
            logger.error(f"Failed to get container status: {e}")
            return "ERROR"

    def _publish_container(self, container_id: str) -> Optional[str]:
        """Publish media container."""
        try:
            response = self.client.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media_publish",
                params={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()

            data = response.json()
            return data.get("id")

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to publish: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error publishing: {e}")
            return None

    def get_account_info(self) -> Optional[dict]:
        """Get Instagram account information."""
        try:
            response = self.client.get(
                f"{GRAPH_API_BASE}/{self.account_id}",
                params={
                    "fields": "username,name,profile_picture_url,followers_count,media_count",
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None

    def verify_token(self) -> bool:
        """Verify access token is valid."""
        info = self.get_account_info()
        if info:
            logger.info(f"Token verified for @{info.get('username', 'unknown')}")
            return True
        return False

    def close(self):
        """Close HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MediaUploader:
    """
    Helper for uploading local files to make them accessible via URL.

    For production, you would upload to:
    - Your own server
    - Cloud storage (S3, GCS, etc.)
    - CDN

    This is a placeholder showing the interface.
    """

    def __init__(self, base_url: str):
        """
        Initialize uploader.

        Args:
            base_url: Base URL where files will be accessible
        """
        self.base_url = base_url.rstrip("/")

    def upload_video(self, video_path: Path) -> Optional[str]:
        """
        Upload video and return public URL.

        Args:
            video_path: Path to video file

        Returns:
            Public URL of uploaded video
        """
        # TODO: Implement actual upload logic
        # For now, return placeholder
        logger.warning("MediaUploader.upload_video not implemented")
        return None

    def upload_image(self, image_path: Path) -> Optional[str]:
        """
        Upload image and return public URL.

        Args:
            image_path: Path to image file

        Returns:
            Public URL of uploaded image
        """
        # TODO: Implement actual upload logic
        logger.warning("MediaUploader.upload_image not implemented")
        return None
