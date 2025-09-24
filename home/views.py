# views.py
import os
import json
import re
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import yt_dlp
import mimetypes
from urllib.parse import quote
from email.header import decode_header
import quopri

# Import the YouTube downloader
from .youtube_downloader import YouTubeDownloader

# Initialize YouTube downloader
youtube_downloader = YouTubeDownloader()

# ---------- Utility Functions ----------
def is_valid_url(url):
    try:
        from urllib.parse import urlparse
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def get_platform(url):
    """Detect platform including YouTube Shorts"""
    if 'youtube.com/shorts/' in url :
        return 'youtube_shorts'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'facebook.com' in url or 'fb.watch' in url:
        return 'facebook'
    elif 'instagram.com' in url:
        return 'instagram'
    elif 'tiktok.com' in url:
        return 'tiktok'
    else:
        return 'unknown'

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def extract_video_info(url):
    """Extract video info using yt-dlp (for non-YouTube platforms)"""
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
            }
    except Exception as e:
        return {'error': str(e)}

# ---------- Home Page ----------
def home(request):
    return render(request, 'index.html')

@csrf_exempt
@require_http_methods(["POST"])
def get_video_info(request):
    try:
        data = json.loads(request.body)
        url = data.get('url', '').strip()

        if not url:
            return JsonResponse({'error': 'URL is required'}, status=400)
        if not is_valid_url(url):
            return JsonResponse({'error': 'Invalid URL format'}, status=400)

        platform = get_platform(url)
        print(platform)
        
        # For YouTube Shorts, use simple quality options
        if platform == 'youtube_shorts':
            # Use yt-dlp with simple format selection
            info = extract_video_info(url)
            if 'error' in info:
                return JsonResponse({'error': info['error']}, status=400)
            info['platform'] = 'youtube'  # Still show as YouTube
            info['is_shorts'] = True
            info['available_qualities'] = []  # No detailed qualities for Shorts
            return JsonResponse(info)

        
        # Regular YouTube videos and other platforms
        elif platform == 'youtube':
            video_info, available_qualities, _ = youtube_downloader.get_video_info(url)
            if video_info:
                video_info['platform'] = 'youtube'
                video_info['is_shorts'] = False
                video_info['available_qualities'] = list(available_qualities.keys()) if available_qualities else []
                return JsonResponse(video_info)
            else:
                # Handle case where video_info is None
                return JsonResponse({'error': 'Failed to extract video information from YouTube'}, status=400)
        else:
            # Other platforms
            info = extract_video_info(url)
            if 'error' in info:
                return JsonResponse({'error': info['error']}, status=400)
            info['platform'] = platform
            info['is_shorts'] = False
            info['available_qualities'] = []  # Simple options for other platforms
            return JsonResponse(info)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def download_video(request):
    try:
        data = json.loads(request.body)
        url = data.get('url', '').strip()
        quality = data.get('quality', 'best')

        if not url:
            return JsonResponse({'error': 'URL is required'}, status=400)

        platform = get_platform(url)
        print(platform)
        
        # Use YouTube downloader for YouTube URLs
        if platform == 'youtube':
            result = youtube_downloader.download_video(url, quality)
            
            if result['status'] == 'success':
                return serve_file(result['file_path'], result['filename'], result.get('temp_files', []))
            else:
                return JsonResponse({'error': result['message']}, status=400)
        else:
            # Use existing yt-dlp approach for other platforms
            return download_other_platforms(url, quality)

    except Exception as e:
        return JsonResponse({'error': f'Download failed: {str(e)}'}, status=500)

def download_other_platforms(url, quality):
    """Download videos from non-YouTube platforms"""
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)

    # Simple format selection for non-YouTube platforms
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
        'format': 'best[height<=1080]/best',
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        original_filepath = ydl.prepare_filename(info)

    # Sanitize filename
    video_title = sanitize_filename(info.get('title', 'video'))
    ext = info.get('ext', 'mp4')
    final_filename = f"{video_title}.{ext}"
    final_filepath = os.path.join(download_dir, final_filename)

    # Rename if needed
    if original_filepath != final_filepath and os.path.exists(original_filepath):
        os.rename(original_filepath, final_filepath)

    return serve_file(final_filepath, final_filename)



# def clean_filename(filename: str) -> str:
#     """Clean and decode filenames, including Q-encoded ones from YouTube Shorts."""
#     # Detect Q-encoded (=utf-8_q_) filenames
#     if filename.lower().startswith("=_utf-8_q_"):
#         try:
#             decoded_parts = decode_header(filename)
#             decoded_filename = ""
#             for text, enc in decoded_parts:
#                 if isinstance(text, bytes):
#                     if enc:
#                         decoded_filename += text.decode(enc, errors="ignore")
#                     else:
#                         # Sometimes it's quoted-printable
#                         decoded_filename += quopri.decodestring(text).decode("utf-8", errors="ignore")
#                 else:
#                     decoded_filename += text

#             # Sanitize invalid characters
#             decoded_filename = re.sub(r'[\\/*?:"<>|]', "_", decoded_filename)
#             if not decoded_filename.lower().endswith(".mp4"):
#                 decoded_filename += ".mp4"
#             print(f"[Serve] Decoded Shorts filename → {decoded_filename}")
#             return decoded_filename
#         except Exception as e:
#             print(f"[Serve] Failed to decode Q-encoded filename, using fallback: {e}")
#             return "video.mp4"

#     # Normal cleanup
#     filename = re.sub(r'[\\/*?:"<>|]', "_", filename).strip()
#     if not filename.lower().endswith(".mp4"):
#         filename += ".mp4"
#     return filename


# def serve_file(file_path, filename, temp_files=None):
#     """Serve file for download with proper filename handling"""
#     print(f"[Serve] Raw filename: {filename}")

#     # Clean / decode filename
#     filename = clean_filename(filename)

#     def file_iterator(path, chunk_size=8192):
#         with open(path, 'rb') as f:
#             while chunk := f.read(chunk_size):
#                 yield chunk
#         # Cleanup after streaming
#         try:
#             os.remove(path)
#             if temp_files:
#                 for temp_file in temp_files:
#                     if os.path.exists(temp_file):
#                         os.remove(temp_file)
#         except OSError:
#             pass

#     file_size = os.path.getsize(file_path)
#     mime_type, _ = mimetypes.guess_type(file_path)

#     response = StreamingHttpResponse(
#         file_iterator(file_path),
#         content_type=mime_type or 'video/mp4'
#     )

#     # ✅ RFC 5987 safe filename
#     quoted_filename = quote(filename)
#     response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quoted_filename}"
#     response['Content-Length'] = file_size
#     response['X-Filename'] = filename  # for frontend display

#     print(f"[Serve] Final filename header: {filename}")
#     return response

from urllib.parse import quote
from email.header import decode_header
import quopri
import base64
import re
import mimetypes
import os
from django.http import StreamingHttpResponse

def clean_filename(filename: str, ascii_only=True) -> str:
    """Clean and decode filenames safely."""
    try:
        # Q-encoded (quoted-printable)
        if filename.lower().startswith("=_utf-8_q_"):
            decoded_parts = decode_header(filename)
            decoded_filename = ""
            for text, enc in decoded_parts:
                if isinstance(text, bytes):
                    if enc:
                        decoded_filename += text.decode(enc, errors="ignore")
                    else:
                        decoded_filename += quopri.decodestring(text).decode("utf-8", errors="ignore")
                else:
                    decoded_filename += text
            filename = decoded_filename

        # B-encoded (Base64)
        elif filename.lower().startswith("=_utf-8_b_"):
            b64_part = filename[len("=_utf-8_b_"):]
            if b64_part.endswith("=_"):
                b64_part = b64_part[:-2]
            decoded_bytes = base64.b64decode(b64_part)
            filename = decoded_bytes.decode("utf-8", errors="ignore")

    except Exception as e:
        print(f"[Filename Decode] Failed to decode '{filename}': {e}")
        filename = "video"

    # Remove invalid filesystem characters
    filename = re.sub(r'[\\/*?:"<>|]', "_", filename)

    # Optional: Keep only ASCII characters for browser-safe downloads
    if ascii_only:
        filename = filename.encode("ascii", errors="ignore").decode()

    filename = filename.strip()
    if not filename.lower().endswith(".mp4"):
        filename += ".mp4"

    return filename


def serve_file(file_path, filename, temp_files=None, ascii_safe=True):
    """Serve file for download robustly, handling all filename issues."""
    print(f"[Serve] Raw filename: {filename}")

    # Clean / decode filename
    filename = clean_filename(filename, ascii_only=ascii_safe)

    def file_iterator(path, chunk_size=8192):
        with open(path, 'rb') as f:
            while chunk := f.read(chunk_size):
                yield chunk
        # Cleanup after streaming
        try:
            os.remove(path)
            if temp_files:
                for temp_file in temp_files:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
        except OSError:
            pass

    file_size = os.path.getsize(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)

    response = StreamingHttpResponse(
        file_iterator(file_path),
        content_type=mime_type or 'video/mp4'
    )

    # RFC 5987 safe filename for all browsers
    quoted_filename = quote(filename)
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quoted_filename}"
    response['Content-Length'] = file_size
    response['X-Filename'] = filename  # frontend-safe display

    print(f"[Serve] Final filename header: {filename}")
    return response
