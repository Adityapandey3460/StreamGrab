# youtube_downloader.py
import os
import subprocess
import yt_dlp
import imageio_ffmpeg
from pathlib import Path
import logging
import re
import json

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    def __init__(self, download_folder="downloads"):
        self.download_folder = Path(download_folder)
        self.download_folder.mkdir(exist_ok=True)
        self.check_ffmpeg()

    def check_ffmpeg(self):
        """Check if FFmpeg is available via imageio-ffmpeg."""
        try:
            import imageio_ffmpeg
            logger.info("✅ imageio-ffmpeg is available.")
            return True
        except ImportError:
            logger.error("❌ imageio-ffmpeg is not installed.")
            return False

    def is_youtube_url(self, url):
        """Check if the URL is a valid YouTube URL."""
        youtube_regex = r'(https?://)?(www\.)?(youtube|youtu)\.(com|be)/.+'
        return re.match(youtube_regex, url) is not None

    def sanitize_filename(self, filename):
        """Sanitize the filename to remove invalid characters."""
        return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

    # In youtube_downloader.py
    def get_video_info(self, video_url):
        """Get video information and available formats."""
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'ignoreerrors': True}) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                if not info:
                    print("[YouTube Downloader] Failed to extract video info")
                    return None, None, None
                    
                # Extract basic video info
                video_info = {
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'platform': 'youtube'
                }
                
                # Extract available formats
                formats = info.get('formats', [])
                available_qualities = {}
                
                for f in formats:
                    resolution = f.get('format_note', '')
                    format_id = f['format_id']
                    height = f.get('height', 0)

                    # Set resolution for specific heights
                    if height == 2160:
                        resolution = '2160p'
                    elif height == 1440:
                        resolution = '1440p'
                    elif height == 1080:
                        resolution = '1080p'
                    elif height == 720:
                        resolution = '720p'
                    elif height == 480:
                        resolution = '480p'
                    elif height == 360:
                        resolution = '360p'

                    if resolution:
                        if "audio" in f.get('acodec', 'none'):
                            available_qualities[resolution] = {'id': format_id, 'type': 'progressive'}
                        else:
                            available_qualities[resolution] = {'id': format_id, 'type': 'video'}

                return video_info, available_qualities, info
                    
        except Exception as e:
            print(f"[YouTube Downloader Error] {e}")
            return None, None, None

    def download_video(self, video_url, quality):
        """Download YouTube video with specified quality."""
        if not self.is_youtube_url(video_url):
            return {"status": "error", "message": "Invalid YouTube URL!"}

        video_info, available_formats, full_info = self.get_video_info(video_url)
        if not available_formats:
            return {"status": "error", "message": "No available formats found!"}

        # Find the best matching quality
        selected_quality = self._find_best_quality_match(quality, available_formats)
        if not selected_quality:
            return {"status": "error", "message": f"Quality '{quality}' not available!"}

        format_info = available_formats[selected_quality]
        video_title = self.sanitize_filename(video_info['title'])
        
        if format_info['type'] == 'progressive':
            # Direct download for progressive formats
            return self._download_progressive(video_url, format_info, video_title)
        else:
            # Separate download and merge for video-only formats
            return self._download_and_merge(video_url, format_info, video_title, full_info)

    def _find_best_quality_match(self, requested_quality, available_formats):
        """Find the best matching quality from available formats."""
        quality_preference = ['2160p', '1440p', '1080p', '720p', '480p', '360p', '240p', '144p']
        
        # If specific quality requested
        if requested_quality in available_formats:
            return requested_quality
        
        # Find the closest available quality
        for quality in quality_preference:
            if quality in available_formats:
                if requested_quality == 'best':
                    return quality
                elif requested_quality == 'worst':
                    continue
        
        # Return the worst available quality for 'worst'
        if requested_quality == 'worst':
            for quality in reversed(quality_preference):
                if quality in available_formats:
                    return quality
        
        return None

    def _download_progressive(self, video_url, format_info, video_title):
        """Download progressive video (video + audio combined)."""
        output_file = self.download_folder / f"{video_title}.mp4"
        
        ydl_opts = {
            'format': format_info['id'],
            'outtmpl': str(output_file),
            'quiet': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            return {
                "status": "success", 
                "file_path": str(output_file),
                "filename": f"{video_title}.mp4"
            }
        except Exception as e:
            logger.error(f"Error downloading progressive video: {e}")
            return {"status": "error", "message": str(e)}

    def _download_and_merge(self, video_url, format_info, video_title, full_info):
        """Download and merge separate video and audio streams."""
        video_file = self.download_folder / f"{video_title}_video.mp4"
        audio_file = self.download_folder / f"{video_title}_audio.mp4"
        output_file = self.download_folder / f"{video_title}.mp4"

        # Find best audio format
        best_audio = max(
            [f for f in full_info['formats'] if f.get('acodec') != 'none' and f.get('abr') is not None],
            key=lambda f: f['abr'],
            default=None
        )

        if not best_audio:
            return {"status": "error", "message": "No valid audio formats found!"}

        audio_id = best_audio['format_id']
        
        try:
            # Download video
            ydl_opts_video = {
                'format': format_info['id'], 
                'outtmpl': str(video_file),
                'quiet': True
            }
            with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                ydl.download([video_url])

            # Download audio
            ydl_opts_audio = {
                'format': audio_id, 
                'outtmpl': str(audio_file),
                'quiet': True
            }
            with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
                ydl.download([video_url])

            # Merge using FFmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            merge_command = [
                ffmpeg_path, '-i', str(video_file), '-i', str(audio_file),
                '-c:v', 'copy', '-c:a', 'aac', str(output_file), '-y'
            ]
            subprocess.run(merge_command, check=True, capture_output=True)

            # Clean up temporary files
            files_to_delete = [video_file, audio_file]
            
            return {
                "status": "success", 
                "file_path": str(output_file),
                "filename": f"{video_title}.mp4",
                "temp_files": [str(f) for f in files_to_delete]
            }
            
        except Exception as e:
            logger.error(f"Error during video/audio download or merge: {e}")
            return {"status": "error", "message": str(e)}