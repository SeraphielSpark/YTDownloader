import logging
import os
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from yt_dlp import YoutubeDL, DownloadError

# --- Flask Setup ---
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# --- Cookies Setup ---
# Automatically use cookies.txt if it exists
COOKIES_FILE = "cookies.txt" if os.path.exists("cookies.txt") else None
if COOKIES_FILE:
    app.logger.info("✅ cookies.txt found — using authenticated YouTube access")
else:
    app.logger.warning("⚠️ No cookies.txt found — restricted videos may fail")

# --- yt-dlp Base Options ---
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

# Attach cookies if file exists
if COOKIES_FILE:
    BASE_YDL_OPTS["cookiefile"] = COOKIES_FILE

# --- Error Handling ---
def handle_ydl_error(e):
    msg = str(e).split("\n")[0]
    app.logger.error(f"yt-dlp error: {msg}")
    if any(x in msg for x in ["Sign in", "confirm you’re not a bot", "Login required"]):
        return "This video is restricted and requires cookies.txt for access."
    if "Unsupported URL" in msg:
        return "Unsupported link. Please check the URL."
    return f"Failed to process video: {msg}"

# --- Routes ---
@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/get-info")
def get_info():
    url = request.args.get("url")
    if not url:
        return jsonify({"detail": "Missing URL."}), 400

    try:
        ydl_opts = BASE_YDL_OPTS.copy()
        ydl_opts["skip_download"] = True

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise Exception("No video information could be extracted.")

        simplified_formats = []
        for f in info.get("formats", []):
            if f.get("url") and (f.get("vcodec") != "none" or f.get("acodec") != "none"):
                label = f.get("format_note") or (f.get("height") and f"{f['height']}p") or "N/A"
                simplified_formats.append({
                    "itag": f.get("format_id"),
                    "container": f.get("ext"),
                    "qualityLabel": label,
                    "hasVideo": f.get("vcodec") != "none",
                    "hasAudio": f.get("acodec") != "none",
                    "mimeType": f.get("mime_type", ""),
                    "bitrate": f.get("abr", None),
                })

        response_data = {
            "title": info.get("title"),
            "author": info.get("uploader"),
            "thumbnail": info.get("thumbnail") or (info.get('thumbnails', [{}])[-1].get('url', '')),
            "lengthSeconds": info.get("duration"),
            "formats": simplified_formats
        }

        return jsonify(response_data)

    except DownloadError as e:
        return jsonify({"detail": handle_ydl_error(e)}), 400
    except Exception as e:
        app.logger.error("Error in /get-info", exc_info=True)
        return jsonify({"detail": f"Server error: {type(e).__name__}"}), 500

@app.route("/download")
def download():
    url = request.args.get("url")
    itag = request.args.get("itag")
    file_type = request.args.get("type")

    if not url or not itag:
        return jsonify({"detail": "Missing parameters (url, itag)."}), 400

    try:
        ydl_opts = BASE_YDL_OPTS.copy()
        ydl_opts["format"] = itag
        ydl_opts["skip_download"] = True

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        fmt = next((f for f in info["formats"] if f["format_id"] == itag), None)
        if not fmt or not fmt.get("url"):
            return jsonify({"detail": "Stream not found."}), 404

        title = info.get("title", "video")
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        ext = fmt.get("ext", "mp4") if file_type != "mp3" else "mp3"
        filename = f"{safe_title}.{ext}"

        response = Response(status=302)
        response.headers["Location"] = fmt["url"]
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if fmt.get("filesize") or fmt.get("filesize_approx"):
            response.headers["Content-Length"] = str(fmt.get("filesize") or fmt.get("filesize_approx"))
        return response

    except DownloadError as e:
        return jsonify({"detail": handle_ydl_error(e)}), 400
    except Exception as e:
        app.logger.error("Error in /download", exc_info=True)
        return jsonify({"detail": f"Streaming error: {type(e).__name__}"}), 500

# --- Note ---
# Remove if __name__ == "__main__" block — use Gunicorn on Render
