"""
Video composer using FFmpeg.

Creates Instagram Stories videos from:
- Static photo (scaled/cropped to 9:16)
- Music track (trimmed to duration)

Supports optional Ken Burns effect (slow zoom/pan).
"""

import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_ffmpeg_path() -> str:
    """
    Get path to FFmpeg executable.

    Tries imageio-ffmpeg first (bundled with full codecs),
    falls back to system FFmpeg.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        raise RuntimeError(
            "FFmpeg not found. Install via:\n"
            "  pip install imageio-ffmpeg\n"
            "  or: sudo apt install ffmpeg"
        )


@dataclass
class VideoConfig:
    """Video composition settings."""
    width: int = 1080
    height: int = 1920
    duration: int = 15  # seconds
    bitrate: str = "4000k"
    audio_bitrate: str = "192k"
    fps: int = 30
    codec: str = "libx264"
    preset: str = "medium"  # ultrafast, fast, medium, slow
    crf: int = 23  # Quality: 18-28, lower = better


class VideoComposer:
    """
    Creates video files from photos and music using FFmpeg.

    Supports:
    - Basic static photo + music
    - Ken Burns effect (slow zoom)
    - Custom duration matching music length
    """

    def __init__(
        self,
        output_dir: Path,
        config: Optional[VideoConfig] = None,
    ):
        """
        Initialize video composer.

        Args:
            output_dir: Directory for output video files
            config: Video settings (uses defaults if not provided)
        """
        self.output_dir = Path(output_dir)
        self.config = config or VideoConfig()
        self.ffmpeg_path = _get_ffmpeg_path()

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Using FFmpeg: {self.ffmpeg_path}")

    def _get_media_duration(self, media_path: Path) -> Optional[float]:
        """
        Get duration of audio/video file using ffprobe.

        Returns:
            Duration in seconds, or None if unable to determine
        """
        # ffprobe should be in the same directory as ffmpeg
        ffprobe_path = str(Path(self.ffmpeg_path).parent / "ffprobe")
        if not Path(ffprobe_path).exists():
            ffprobe_path = "ffprobe"  # Fall back to system ffprobe

        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(media_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
            logger.warning(f"Could not get duration for {media_path}: {e}")

        return None

    def _generate_output_filename(self, prefix: str = "story") -> Path:
        """Generate unique output filename with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.mp4"
        return self.output_dir / filename

    def compose_story(
        self,
        photo_path: Path,
        music_path: Path,
        output_path: Optional[Path] = None,
        duration: Optional[int] = None,
        ken_burns: bool = False,
    ) -> Path:
        """
        Create a story video from photo and music.

        Args:
            photo_path: Path to input photo
            music_path: Path to input music file
            output_path: Custom output path (auto-generated if None)
            duration: Video duration in seconds (uses config default or music length)
            ken_burns: Enable Ken Burns effect (slow zoom)

        Returns:
            Path to created video file

        Raises:
            FileNotFoundError: If input files don't exist
            RuntimeError: If FFmpeg fails
        """
        photo_path = Path(photo_path)
        music_path = Path(music_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")
        if not music_path.exists():
            raise FileNotFoundError(f"Music not found: {music_path}")

        if output_path is None:
            output_path = self._generate_output_filename()
        else:
            output_path = Path(output_path)

        # Determine duration
        if duration is None:
            music_duration = self._get_media_duration(music_path)
            if music_duration and music_duration <= 60:
                duration = int(music_duration)
            else:
                duration = self.config.duration

        logger.info(f"Composing video: {photo_path.name} + {music_path.name} ({duration}s)")

        # Build FFmpeg command
        if ken_burns:
            cmd = self._build_ken_burns_command(
                photo_path, music_path, output_path, duration
            )
        else:
            cmd = self._build_static_command(
                photo_path, music_path, output_path, duration
            )

        # Execute FFmpeg
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes max
            )

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")

        except subprocess.TimeoutExpired:
            raise RuntimeError("FFmpeg timed out after 5 minutes")

        if not output_path.exists():
            raise RuntimeError(f"Output file was not created: {output_path}")

        file_size = output_path.stat().st_size / (1024 * 1024)  # MB
        logger.info(f"Video created: {output_path.name} ({file_size:.1f} MB)")

        return output_path

    def _build_static_command(
        self,
        photo_path: Path,
        music_path: Path,
        output_path: Path,
        duration: int,
    ) -> list[str]:
        """
        Build FFmpeg command for static photo video.

        Scales and pads photo to 9:16 aspect ratio.
        """
        w = self.config.width
        h = self.config.height

        # Video filter: scale to fit, pad to exact dimensions, center
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )

        return [
            self.ffmpeg_path,
            "-y",  # Overwrite output
            "-loop", "1",  # Loop image
            "-i", str(photo_path),
            "-i", str(music_path),
            "-vf", vf,
            "-c:v", self.config.codec,
            "-preset", self.config.preset,
            "-crf", str(self.config.crf),
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",  # Web optimization
            "-shortest",  # End when shortest input ends
            str(output_path),
        ]

    def _build_ken_burns_command(
        self,
        photo_path: Path,
        music_path: Path,
        output_path: Path,
        duration: int,
    ) -> list[str]:
        """
        Build FFmpeg command with Ken Burns effect (slow zoom in).

        Creates a gentle zoom from 1.0x to 1.2x over the duration.
        """
        w = self.config.width
        h = self.config.height
        fps = self.config.fps
        total_frames = duration * fps

        # Zoom from 1.0 to 1.2 over duration
        # zoompan: z = zoom level, d = duration in frames
        # Expression: zoom starts at 1.0, increases by 0.2/total_frames per frame
        zoom_speed = 0.2 / total_frames

        vf = (
            f"scale=8000:-1,"  # Scale up for quality during zoom
            f"zoompan="
            f"z='min(zoom+{zoom_speed:.6f},1.2)':"  # Zoom factor
            f"x='iw/2-(iw/zoom/2)':"  # Center X
            f"y='ih/2-(ih/zoom/2)':"  # Center Y
            f"d={total_frames}:"  # Duration in frames
            f"s={w}x{h}:"  # Output size
            f"fps={fps},"
            f"setsar=1"
        )

        return [
            self.ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(photo_path),
            "-i", str(music_path),
            "-vf", vf,
            "-c:v", self.config.codec,
            "-preset", self.config.preset,
            "-crf", str(self.config.crf),
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            str(output_path),
        ]

    def compose_post_image(
        self,
        photo_path: Path,
        output_path: Optional[Path] = None,
        aspect_ratio: str = "4:5",
    ) -> Path:
        """
        Prepare image for Instagram feed post.

        Args:
            photo_path: Path to input photo
            output_path: Custom output path
            aspect_ratio: Target aspect ratio ("4:5", "1:1", "1.91:1")

        Returns:
            Path to processed image
        """
        photo_path = Path(photo_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.output_dir / f"post_{timestamp}.jpg"

        # Calculate dimensions based on aspect ratio
        if aspect_ratio == "4:5":
            w, h = 1080, 1350
        elif aspect_ratio == "1:1":
            w, h = 1080, 1080
        else:  # 1.91:1 landscape
            w, h = 1080, 566

        # FFmpeg command to crop and scale
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", str(photo_path),
            "-vf", vf,
            "-q:v", "2",  # High quality JPEG
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")

        logger.info(f"Post image created: {output_path.name}")
        return output_path

    def cleanup_old_files(self, keep_days: int = 7) -> int:
        """
        Remove output files older than specified days.

        Returns:
            Number of files deleted
        """
        import time

        deleted = 0
        cutoff = time.time() - (keep_days * 24 * 60 * 60)

        for file in self.output_dir.iterdir():
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
                deleted += 1
                logger.debug(f"Deleted old file: {file.name}")

        if deleted:
            logger.info(f"Cleaned up {deleted} old files from output directory")

        return deleted
