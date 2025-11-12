import logging
import os
import tempfile
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from yt_dlp import YoutubeDL, DownloadError

# --- Flask Setup ---
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# --- Base yt-dlp options (used for public requests) ---
BASE_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "retries": 3,
    "socket_timeout": 20,
    "format": "bestvideo+bestaudio/best",
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.1 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.youtube.com/",
        "Origin": "https://www.youtube.com",
    },
}

def handle_ydl_error(e: Exception) -> str:
    msg = str(e).split("\n")[0]
    app.logger.error(f"yt-dlp error: {msg}")
    if any(x in msg for x in ["Sign in", "confirm you’re not a bot", "Login required", "This video is age restricted"]):
        return "This video is restricted and requires a cookies.txt (user-provided) to access."
    if "Unsupported URL" in msg:
        return "Unsupported URL. Please check the link."
    return f"Failed to process video: {msg}"

def _use_temp_cookies_file(file_storage):
    """
    Save incoming FileStorage to a temp file and return path.
    Caller responsible for deleting the file.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        file_storage.stream.seek(0)
        tmp.write(file_storage.stream.read())
        tmp.flush()
        tmp.close()
        return tmp.name
    except Exception:
        try:
            tmp.close()
        except Exception:
            pass
        raise

# --- Routes ---
@app.route("/favicon.ico")
def favicon():
    return "", 204

# --- GET /get-info for public usage (no cookies) ---
@app.route("/get-info", methods=["GET"])
def get_info_get():
    """
    GET usage (public videos only): /get-info?url=<youtube_url>
    """
    url = request.args.get("url")
    if not url:
        return jsonify({"detail": "Missing 'url' parameter."}), 400

    try:
        ydl_opts = BASE_YDL_OPTS.copy()
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise Exception("No video information could be extracted.")

        simplified_formats = []
        for f in info.get("formats", []):
            if f.get("url") and (f.get("vcodec") != "none" or f.get("acodec") != "none"):
                quality_label = f.get("format_note") or (f.get("height") and f"{f['height']}p") or "N/A"
                simplified_formats.append({
                    "itag": f.get("format_id"),
                    "container": f.get("ext"),
                    "qualityLabel": quality_label,
                    "hasVideo": f.get("vcodec") != "none",
                    "hasAudio": f.get("acodec") != "none",
                    "mimeType": f.get("mime_type", ""),
                    "bitrate": f.get("abr", None),
                })

        response_data = {
            "title": info.get("title"),
            "author": info.get("uploader"),
            "thumbnail": info.get("thumbnail') or (info.get('thumbnails', [{}])[-1].get('url', '')) if info.get("thumbnail") is None else info.get("thumbnail"),
            "lengthSeconds": info.get("duration"),
            "formats": simplified_formats
        }
        return jsonify(response_data)

    except DownloadError as e:
        return jsonify({"detail": handle_ydl_error(e)}), 400
    except Exception as e:
        app.logger.error("Error in /get-info (GET)", exc_info=True)
        return jsonify({"detail": f"Server error: {type(e).__name__}"}), 500

# --- POST /get-info for optional cookies upload ---
@app.route("/get-info", methods=["POST"])
def get_info_post():
    """
    POST usage (for restricted videos): multipart/form-data
      - url: string
      - cookies: optional file upload (cookies.txt) provided by the user
    The cookies file is used only for this request and deleted immediately afterward.
    """
    url = request.form.get("url")
    if not url:
        return jsonify({"detail": "Missing 'url' parameter in form data."}), 400

    cookies_path = None
    try:
        ydl_opts = BASE_YDL_OPTS.copy()

        # If user uploaded a cookies file, save to temp path and attach
        if "cookies" in request.files:
            cookies_file = request.files["cookies"]
            cookies_path = _use_temp_cookies_file(cookies_file)
            app.logger.info("Temporary cookies file saved for this request.")
            ydl_opts["cookiefile"] = cookies_path

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise Exception("No video information could be extracted.")

        simplified_formats = []
        for f in info.get("formats", []):
            if f.get("url") and (f.get("vcodec") != "none" or f.get("acodec") != "none"):
                quality_label = f.get("format_note") or (f.get("height") and f"{f['height']}p") or "N/A"
                simplified_formats.append({
                    "itag": f.get("format_id"),
                    "container": f.get("ext"),
                    "qualityLabel": quality_label,
                    "hasVideo": f.get("vcodec") != "none",
                    "hasAudio": f.get("acodec") != "none",
                    "mimeType": f.get("mime_type", ""),
                    "bitrate": f.get("abr", None),
                })

        response_data = {
            "title": info.get("title"),
            "author": info.get("uploader"),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url", "")),
            "lengthSeconds": info.get("duration"),
            "formats": simplified_formats
        }
        return jsonify(response_data)

    except DownloadError as e:
        return jsonify({"detail": handle_ydl_error(e)}), 400
    except Exception as e:
        app.logger.error("Error in /get-info (POST)", exc_info=True)
        return jsonify({"detail": f"Server error: {type(e).__name__}"}), 500
    finally:
        if cookies_path and os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
                app.logger.info("Temporary cookies file deleted.")
            except Exception:
                app.logger.warning("Failed to delete temporary cookies file; will be removed by OS eventually.")

# --- POST /download supporting cookies upload ---
@app.route("/download", methods=["POST"])
def download_post():
    """
    POST usage to get redirect URL for streaming:
      - url: youtube url (form)
      - itag: format id (form)
      - type: optional (mp3)
      - cookies: optional file upload
    Returns 302 redirect to the stream URL (the client will follow it).
    """
    url = request.form.get("url")
    itag = request.form.get("itag")
    file_type = request.form.get("type")

    if not url or not itag:
        return jsonify({"detail": "Missing required parameters (url, itag)."}), 400

    cookies_path = None
    try:
        ydl_opts = BASE_YDL_OPTS.copy()
        ydl_opts["format"] = itag

        if "cookies" in request.files:
            cookies_file = request.files["cookies"]
            cookies_path = _use_temp_cookies_file(cookies_file)
            app.logger.info("Temporary cookies file saved for download request.")
            ydl_opts["cookiefile"] = cookies_path

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        chosen = next((f for f in info.get("formats", []) if f.get("format_id") == itag), None)
        if not chosen or not chosen.get("url"):
            return jsonify({"detail": "Stream URL not found for the selected format."}), 404

        title = info.get("title", "video")
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        extension = chosen.get("ext", "mp4") if file_type != "mp3" else "mp3"
        filename = f"{safe_title}.{extension}"

        response = Response(status=302)
        response.headers["Location"] = chosen.get("url")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if chosen.get("filesize") or chosen.get("filesize_approx"):
            response.headers["Content-Length"] = str(chosen.get("filesize") or chosen.get("filesize_approx"))

        return response

    except DownloadError as e:
        return jsonify({"detail": handle_ydl_error(e)}), 400
    except Exception as e:
        app.logger.error("Error in /download (POST)", exc_info=True)
        return jsonify({"detail": f"Server error: {type(e).__name__}"}), 500
    finally:
        if cookies_path and os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
                app.logger.info("Temporary cookies file deleted.")
            except Exception:
                app.logger.warning("Failed to delete temporary cookies file; will be removed by OS eventually.")
