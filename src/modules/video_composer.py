"""
Video composer using FFmpeg.

Creates Instagram Stories videos from:
- Static photo (scaled/cropped to 9:16)
- Music track (trimmed to duration)

Supports:
- Ken Burns effect (slow zoom/pan)
- Text overlays with semi-transparent background
"""

import logging
import subprocess
import shutil
import textwrap
import tempfile
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)


# Default fonts path (will be set during initialization)
DEFAULT_FONTS_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"


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
class TextOverlayConfig:
    """Text overlay settings for Stories."""
    font_path: Optional[Path] = None  # Path to .ttf font file
    font_size: int = 48  # Base font size in pixels
    font_color: str = "white"
    background_color: str = "black"
    background_opacity: float = 0.6  # 0.0 - 1.0
    padding: int = 20  # Padding around text
    shadow_offset: int = 2  # Shadow offset in pixels
    shadow_color: str = "black"
    max_width_chars: int = 25  # Max characters per line before wrap
    position_y: int = 800  # Y position from top (in safe zone)
    line_spacing: int = 10  # Space between lines


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
    text_overlay: TextOverlayConfig = field(default_factory=TextOverlayConfig)


class VideoComposer:
    """
    Creates video files from photos and music using FFmpeg.

    Supports:
    - Basic static photo + music
    - Ken Burns effect (slow zoom)
    - Text overlays with semi-transparent background
    - Custom duration matching music length
    """

    def __init__(
        self,
        output_dir: Path,
        config: Optional[VideoConfig] = None,
        fonts_dir: Optional[Path] = None,
    ):
        """
        Initialize video composer.

        Args:
            output_dir: Directory for output video files
            config: Video settings (uses defaults if not provided)
            fonts_dir: Directory containing font files
        """
        self.output_dir = Path(output_dir)
        self.config = config or VideoConfig()
        self.ffmpeg_path = _get_ffmpeg_path()
        self.fonts_dir = Path(fonts_dir) if fonts_dir else DEFAULT_FONTS_DIR

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Find default font
        self._default_font = self._find_default_font()

        logger.info(f"Using FFmpeg: {self.ffmpeg_path}")
        if self._default_font:
            logger.info(f"Default font: {self._default_font.name}")

    def _find_default_font(self) -> Optional[Path]:
        """Find a suitable default font for text overlays."""
        if not self.fonts_dir.exists():
            logger.warning(f"Fonts directory not found: {self.fonts_dir}")
            return None

        # Priority order for fonts
        preferred_fonts = [
            "Montserrat-Bold.ttf",
            "Montserrat-SemiBold.ttf",
            "Roboto-Bold.ttf",
            "OpenSans-Bold.ttf",
            "NotoSans-Bold.ttf",
        ]

        # Try preferred fonts first
        for font_name in preferred_fonts:
            font_path = self.fonts_dir / font_name
            if font_path.exists():
                return font_path

        # Fall back to any .ttf file
        ttf_files = list(self.fonts_dir.glob("*.ttf"))
        if ttf_files:
            return ttf_files[0]

        return None

    def _wrap_text(self, text: str, max_chars: int = 25) -> list[str]:
        """
        Wrap text into lines that fit within max characters.

        Args:
            text: Text to wrap
            max_chars: Maximum characters per line

        Returns:
            List of text lines
        """
        # Use textwrap for proper word wrapping
        return textwrap.wrap(text, width=max_chars)

    def _escape_text_for_ffmpeg(self, text: str) -> str:
        """
        Escape special characters for FFmpeg drawtext filter.

        FFmpeg drawtext requires escaping: ' : \ and some others
        """
        # Escape backslashes first
        text = text.replace("\\", "\\\\")
        # Escape single quotes
        text = text.replace("'", "\\'")
        # Escape colons (used as parameter separator)
        text = text.replace(":", "\\:")
        return text

    def _add_text_overlay_pillow(
        self,
        image_path: Path,
        text: str,
        output_path: Path,
        text_config: "TextOverlayConfig",
    ) -> Path:
        """
        Add text overlay to image using PIL/Pillow.

        This is more reliable than FFmpeg drawtext as it doesn't depend
        on FFmpeg compile options.

        Args:
            image_path: Path to source image
            text: Text to overlay
            output_path: Path for output image
            text_config: Text styling configuration

        Returns:
            Path to image with overlay
        """
        cfg = text_config

        # Load image and apply EXIF orientation
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)  # Fix rotation from EXIF metadata

        # Resize/crop to Instagram Story dimensions (1080x1920)
        target_w, target_h = self.config.width, self.config.height
        img_w, img_h = img.size

        # Calculate scale to cover the target area
        scale = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)

        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Center crop to target dimensions
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))

        # Convert to RGBA for transparency support
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Create drawing context
        draw = ImageDraw.Draw(img)

        # Load font
        font_path = cfg.font_path or self._default_font
        try:
            font = ImageFont.truetype(str(font_path), cfg.font_size)
        except Exception as e:
            logger.warning(f"Failed to load font {font_path}: {e}")
            font = ImageFont.load_default()

        # Wrap text into lines
        lines = self._wrap_text(text, cfg.max_width_chars)

        # Calculate text block dimensions
        line_heights = []
        line_widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        line_height = max(line_heights) if line_heights else cfg.font_size
        total_height = len(lines) * (line_height + cfg.line_spacing)
        max_width = max(line_widths) if line_widths else 0

        # Position: bottom of safe zone (above Instagram UI)
        # Safe zone: 250px from top, 340px from bottom
        # Text positioned at bottom of safe zone with margin
        safe_zone_bottom = target_h - 340  # 1580px
        bottom_margin = 40  # Extra margin from safe zone edge
        start_y = safe_zone_bottom - total_height - bottom_margin

        # Draw background rectangle
        padding = cfg.padding
        bg_left = (target_w - max_width) // 2 - padding
        bg_top = start_y - padding
        bg_right = (target_w + max_width) // 2 + padding
        bg_bottom = start_y + total_height + padding

        # Create semi-transparent overlay
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Parse background color and opacity
        bg_opacity = int(cfg.background_opacity * 255)
        overlay_draw.rounded_rectangle(
            [bg_left, bg_top, bg_right, bg_bottom],
            radius=10,
            fill=(0, 0, 0, bg_opacity),
        )

        # Composite overlay onto image
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        # Draw text lines
        y = start_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (target_w - text_width) // 2

            # Draw shadow
            if cfg.shadow_offset > 0:
                draw.text(
                    (x + cfg.shadow_offset, y + cfg.shadow_offset),
                    line,
                    font=font,
                    fill=cfg.shadow_color,
                )

            # Draw text
            draw.text((x, y), line, font=font, fill=cfg.font_color)
            y += line_height + cfg.line_spacing

        # Save as RGB (JPEG doesn't support alpha)
        img_rgb = img.convert("RGB")
        img_rgb.save(output_path, "JPEG", quality=95)

        logger.debug(f"Created image with text overlay: {output_path}")
        return output_path

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

    def compose_story_with_overlay(
        self,
        photo_path: Path,
        music_path: Path,
        text: str,
        output_path: Optional[Path] = None,
        duration: Optional[int] = None,
        ken_burns: bool = True,
        text_config: Optional[TextOverlayConfig] = None,
    ) -> Path:
        """
        Create a story video with text overlay.

        Uses PIL/Pillow for text rendering (more reliable than FFmpeg drawtext).

        Args:
            photo_path: Path to input photo
            music_path: Path to input music file
            text: Text to overlay on the video
            output_path: Custom output path (auto-generated if None)
            duration: Video duration in seconds
            ken_burns: Enable Ken Burns effect
            text_config: Text overlay settings (uses defaults if None)

        Returns:
            Path to created video file
        """
        photo_path = Path(photo_path)
        music_path = Path(music_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")
        if not music_path.exists():
            raise FileNotFoundError(f"Music not found: {music_path}")

        # Use provided config or default
        txt_cfg = text_config or self.config.text_overlay

        # Check if font is available
        font_path = txt_cfg.font_path or self._default_font
        if not font_path or not font_path.exists():
            logger.warning("No font found, falling back to compose_story without overlay")
            return self.compose_story(
                photo_path=photo_path,
                music_path=music_path,
                output_path=output_path,
                duration=duration,
                ken_burns=ken_burns,
            )

        # Update config with actual font path
        txt_cfg.font_path = font_path

        logger.info(f"Composing video with overlay: {photo_path.name}")
        logger.debug(f"Overlay text: {text[:50]}...")

        # Step 1: Create image with text overlay using PIL
        # Use temp file for intermediate image
        temp_image = self.output_dir / f"_temp_overlay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

        try:
            self._add_text_overlay_pillow(
                image_path=photo_path,
                text=text,
                output_path=temp_image,
                text_config=txt_cfg,
            )
            logger.debug(f"Created temp image with overlay: {temp_image}")

            # Step 2: Create video from the processed image
            video_path = self.compose_story(
                photo_path=temp_image,
                music_path=music_path,
                output_path=output_path,
                duration=duration,
                ken_burns=ken_burns,
            )

            return video_path

        finally:
            # Clean up temp image
            if temp_image.exists():
                temp_image.unlink()
                logger.debug(f"Cleaned up temp image: {temp_image}")

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
