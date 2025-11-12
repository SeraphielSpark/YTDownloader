import logging
import os 
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from yt_dlp import YoutubeDL, DownloadError

# --- Flask Setup ---
app = Flask(__name__)
# Enable CORS for all origins
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# --- Configuration ---
# Removed COOKIES_FILE reference as the file does not exist on Render's ephemeral disk.

# yt-dlp options for extracting video metadata (info)
YDL_OPTS_INFO = {
    'quiet': True,
    'skip_download': True,
    'no_warnings': True,
    # CRITICAL: Strengthened headers to bypass YouTube detection on cloud IPs
    'http_headers': {
        # Updated User-Agent (less likely to be flagged as bot)
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        # Essential Referer header
        'referer': 'https://www.youtube.com/', 
    },
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best', 
    'retries': 3, 
    'socket_timeout': 15,
    # 'cookiefile': COOKIES_FILE, <-- REMOVED
}

# --- Utility Functions ---

def handle_ydl_error(e: Exception) -> str:
    """Parses yt-dlp errors for a friendly message."""
    error_msg = str(e).split('\n')[0]
    app.logger.error(f"yt-dlp Error: {error_msg}")
    
    if "Sign in to confirm" in error_msg or "confirm you’re not a bot" in error_msg:
        return "Video Access Denied: This content requires sign-in or cookies (likely age-gated/private)."
    if "Unsupported URL" in error_msg:
        return "Unsupported URL. Please check the link or source."
    
    return f"Failed to process video: {error_msg}"


# --- API Endpoints ---

@app.route("/favicon.ico")
def favicon():
    """Placeholder route to prevent 404 logging for the favicon."""
    return '', 204

@app.route("/get-info", methods=['GET'])
def get_video_info():
    """Fetches comprehensive metadata and format options."""
    url = request.args.get('url')
    if not url:
        return jsonify({"detail": "Missing 'url' parameter."}), 400
    
    try:
        # Use YoutubeDL as a context manager to extract metadata
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)
            
        if info is None:
            raise Exception("No video information could be extracted.")

        simplified_formats = []
        for f in info.get('formats', []):
            # Only include formats that are streamable and have video/audio content
            if f.get('url') and (f.get('vcodec') != 'none' or f.get('acodec') != 'none'):
                quality_label = f.get('format_note') or (f.get('height') and f"{f['height']}p") or 'N/A'
                
                simplified_formats.append({
                    "itag": f.get('format_id'),
                    "container": f.get('ext'),
                    "qualityLabel": quality_label,
                    "hasVideo": f.get('vcodec') != 'none',
                    "hasAudio": f.get('acodec') != 'none',
                    "mimeType": f.get('mime_type', ''),
                    "bitrate": f.get('abr', None) 
                })

        response_data = {
            "title": info.get('title'),
            "author": info.get('uploader'),
            "thumbnail": info.get('thumbnail') or info.get('thumbnails', [{}])[-1].get('url', ''),
            "lengthSeconds": info.get('duration'),
            "formats": simplified_formats
        }
        
        return jsonify(response_data)

    except DownloadError as e:
        error_message = handle_ydl_error(e)
        return jsonify({"detail": error_message}), 400
    except Exception as e:
        app.logger.error("Error in /get-info:", exc_info=True)
        return jsonify({"detail": f"An unexpected server error occurred: {type(e).__name__}"}), 500


@app.route("/download", methods=['GET'])
def download_video():
    """
    Retrieves the direct stream URL and returns an HTTP 302 Redirect.
    This bypasses server timeouts for reliable long downloads.
    """
    url = request.args.get('url')
    itag = request.args.get('itag')
    file_type = request.args.get('type') # Used for filename extension

    if not all([url, itag]):
        return jsonify({"detail": "Missing required parameters (url, itag)."}), 400

    try:
        # 1. Get the direct stream URL using yt-dlp
        ydl_opts_download = YDL_OPTS_INFO.copy()
        ydl_opts_download['format'] = itag 
        
        with YoutubeDL(ydl_opts_download) as ydl_specific:
            info = ydl_specific.extract_info(url, download=False)

        chosen_format = next((f for f in info.get('formats', []) if f.get('format_id') == itag), None)
        stream_url = chosen_format.get('url') if chosen_format else None

        if not stream_url:
            return jsonify({"detail": "Stream URL not found for the selected format."}), 404

        # 2. Sanitize title for filename
        title = info.get('title', 'video')
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        
        # 3. Determine filename and headers
        extension = chosen_format.get('ext', 'mp4') if file_type != 'mp3' else 'mp3'
        filename = f"{safe_title}.{extension}"
        
        # 4. Return the HTTP 302 Redirect response
        response = Response(
            status=302, 
            headers={
                "Location": stream_url,
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
        response.headers["Content-Length"] = str(chosen_format.get('filesize') or chosen_format.get('filesize_approx', ''))
        
        return response

    except DownloadError as e:
        error_message = handle_ydl_error(e)
        return jsonify({"detail": error_message}), 400
    except Exception as e:
        app.logger.error("Error in /download:", exc_info=True)
        return jsonify({"detail": f"An unexpected error occurred during streaming: {type(e).__name__}"}), 500

# The if __name__ == "__main__": block is removed for production deployment via Gunicorn.
