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
    if type_ == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }]

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        filename = os.path.basename(tmp_file.name)

        # Stream the file back with proper headers
        def generate():
            with open(tmp_file.name, 'rb') as f:
                chunk = f.read(8192)
                while chunk:
                    yield chunk
                    chunk = f.read(8192)
            os.unlink(tmp_file.name)  # Clean up after sending

        mime = 'audio/mpeg' if type_ == 'mp3' else 'video/mp4'

        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': mime,
        }

        return Response(generate(), headers=headers)

    except Exception as e:
        if os.path.exists(tmp_file.name):
            os.unlink(tmp_file.name)
        return jsonify({'error': 'Download failed', 'details': str(e)}), 500


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

