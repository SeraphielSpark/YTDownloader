from flask import Flask, request, jsonify, send_file, Response, abort
from yt_dlp import YoutubeDL
import tempfile
import os

app = Flask(__name__)

# Common yt-dlp options for info extraction
YDL_OPTS_INFO = {
    'quiet': True,
    'skip_download': True,
    'nocheckcertificate': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'format': 'best',
}

@app.route('/get-info')
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing URL parameter'}), 400

    with YoutubeDL(YDL_OPTS_INFO) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                formats.append({
                    'itag': f.get('format_id'),
                    'container': f.get('ext'),
                    'qualityLabel': f.get('format_note') or f.get('resolution') or 'Unknown',
                    'hasVideo': f.get('vcodec') != 'none',
                    'hasAudio': f.get('acodec') != 'none',
                    'mimeType': f.get('mime_type', ''),
                })

            response = {
                'title': info.get('title'),
                'author': info.get('uploader'),
                'thumbnail': info.get('thumbnail'),
                'lengthSeconds': info.get('duration'),
                'formats': formats
            }
            return jsonify(response)

        except Exception as e:
            return jsonify({'error': 'Failed to fetch video info', 'details': str(e)}), 500


@app.route('/download')
def download():
    url = request.args.get('url')
    itag = request.args.get('itag')
    type_ = request.args.get('type', 'mp4')

    if not url or not itag:
        return jsonify({'error': 'Missing URL or itag parameter'}), 400

    # Create a temp file to download to
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{type_}')
    tmp_file.close()  # Will write via yt-dlp

    ydl_opts = {
        'format': itag,
        'outtmpl': tmp_file.name,
        'quiet': True,
        'nocheckcertificate': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }

    # If requesting mp3, convert on the fly
from flask import Flask, request, jsonify, Response, stream_with_context
import yt_dlp
import requests

app = Flask(__name__)

# Common yt-dlp options with headers to mimic a browser
YDL_OPTS_INFO = {
    'quiet': True,
    'skip_download': True,
    'forcejson': True,
    'no_warnings': True,
    'http_headers': {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'),
        'Accept-Language': 'en-US,en;q=0.9',
    },
}

@app.route('/get-info')
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing URL parameter'}), 400

    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)

        data = {
            'title': info.get('title'),
            'author': info.get('uploader'),
            'thumbnail': info.get('thumbnail'),
            'lengthSeconds': info.get('duration'),
            'formats': [
                {
                    'itag': f.get('format_id'),
                    'container': f.get('ext'),
                    'qualityLabel': f.get('format_note'),
                    'hasVideo': f.get('vcodec') != 'none',
                    'hasAudio': f.get('acodec') != 'none',
                    'mimeType': f.get('acodec') + '/' + f.get('ext'),
                }
                for f in info.get('formats', [])
                if (f.get('acodec') != 'none' or f.get('vcodec') != 'none')
            ]
        }
        return jsonify(data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Unable to fetch video info', 'details': str(e)}), 500


@app.route('/download')
def download():
    url = request.args.get('url')
    itag = request.args.get('itag')

    if not url or not itag:
        return jsonify({'error': 'Missing url or itag parameter'}), 400

    try:
        # Extract info again to get direct URL for requested format
        with yt_dlp.YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)

        format_info = None
        for f in info.get('formats', []):
            if f.get('format_id') == itag:
                format_info = f
                break

        if not format_info:
            return jsonify({'error': 'Format not found'}), 404

        # Stream the actual video/audio from the direct URL yt-dlp provides
        download_url = format_info.get('url')
        if not download_url:
            return jsonify({'error': 'No download URL found for selected format'}), 500

        filename = f"{info.get('title', 'video').replace('/', '_')}.{format_info.get('ext', 'mp4')}"

        headers = {
            'User-Agent': YDL_OPTS_INFO['http_headers']['User-Agent'],
            'Accept-Language': YDL_OPTS_INFO['http_headers']['Accept-Language'],
        }

        def generate():
            with requests.get(download_url, headers=headers, stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk

        response = Response(stream_with_context(generate()), mimetype=format_info.get('acodec', 'video/mp4'))
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Download failed', 'details': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
