import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from yt_dlp import YoutubeDL
from starlette.responses import StreamingResponse

app = FastAPI()

# Allow CORS for all origins (adjust in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# yt-dlp options to extract video info without downloading
YDL_OPTS_INFO = {
    'quiet': True,
    'skip_download': True,
    'no_warnings': True,
    'format': 'best',
}

@app.get("/get-info")
async def get_info(url: str = Query(..., description="YouTube video URL")):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    try:
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' or f.get('acodec') != 'none':
                formats.append({
                    'itag': f.get('format_id'),
                    'container': f.get('ext'),
                    'qualityLabel': f.get('format_note') or f.get('quality') or 'Unknown',
                    'hasVideo': f.get('vcodec') != 'none',
                    'hasAudio': f.get('acodec') != 'none',
                    'mimeType': f.get('mime_type', ''),
                    'bitrate': f.get('abr', None),
                })

        return {
            'title': info.get('title'),
            'author': info.get('uploader'),
            'thumbnail': info.get('thumbnail'),
            'lengthSeconds': info.get('duration'),
            'formats': formats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch video info: {str(e)}")

@app.get("/download")
async def download(url: str = Query(...), itag: str = Query(...), type: str = Query(default='mp4')):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    try:
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)

        chosen_format = None
        for f in info.get('formats', []):
            if f.get('format_id') == itag:
                chosen_format = f
                break

        if not chosen_format:
            raise HTTPException(status_code=404, detail="Format not found")

        stream_url = chosen_format.get('url')
        if not stream_url:
            raise HTTPException(status_code=404, detail="Stream URL not found")

        title = info.get('title', 'video').replace('/', '_').replace('\\', '_').replace('"', '_')
        extension = 'mp3' if type == 'mp3' else chosen_format.get('ext', 'mp4')
        filename = f"{title}.{extension}"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "audio/mpeg" if type == 'mp3' else "video/mp4"
        }

        def iterfile():
            import requests
            with requests.get(stream_url, stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk

        return StreamingResponse(iterfile(), headers=headers)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
                    
