import os
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from yt_dlp import YoutubeDL
from starlette.responses import StreamingResponse
# Note: Renamed from app.py to main.py to align with user's open file context.

app = FastAPI()

# Allow CORS for all origins (adjust in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌟 CRITICAL: Define the path to your YouTube cookie file.
COOKIES_FILE = 'youtube_cookies.txt' 

# yt-dlp options to extract video info without downloading
YDL_OPTS_INFO = {
    'quiet': True,
    'skip_download': True,
    'no_warnings': True,
    # FIX 1: Add a standard User-Agent to mimic a browser
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    },
    # FIX 2: Prioritize non-DASH formats (combined video/audio)
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best', 
    'retries': 3, 
    'socket_timeout': 15,
    # 🌟 CRITICAL 3: Load the cookie file for authentication
    'cookiefile': COOKIES_FILE,
    # 🚨 CRITICAL FIX: The previously problematic 'force_ipv4': True is NOT included here.
}

@app.get("/get-info")
async def get_info(url: str = Query(..., description="Video URL")):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    try:
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            # FIX APPLIED: The fix is confirmed in YDL_OPTS_INFO and the extract_info call is clean.
            info = ydl.extract_info(url, download=False)
            
        if info is None:
            raise Exception("No video information could be extracted. It might be private, deleted, or regional restricted.")

        formats = []
        for f in info.get('formats', []):
            if f.get('url') and (f.get('vcodec') != 'none' or f.get('acodec') != 'none'):
                quality_label = f.get('format_note') or f.get('quality') or f.get('resolution')
                if quality_label and 'DASH' in quality_label:
                    quality_label = quality_label.replace('-DASH', '').strip()
                    
                formats.append({
                    'itag': f.get('format_id'),
                    'container': f.get('ext'),
                    'qualityLabel': quality_label or 'Unknown',
                    'hasVideo': f.get('vcodec') != 'none',
                    'hasAudio': f.get('acodec') != 'none',
                    'mimeType': f.get('mime_type', ''),
                    'bitrate': f.get('abr', None),
                })

        return {
            'title': info.get('title'),
            'author': info.get('uploader'),
            'thumbnail': info.get('thumbnail') or info.get('thumbnails', [{}])[-1].get('url', ''),
            'lengthSeconds': info.get('duration'),
            'formats': formats
        }
    except Exception as e:
        error_msg = str(e).split('\n')[0]
        # IMPROVED ERROR HANDLING: Specifically look for sign-in/cookie errors
        if "Sign in to confirm" in error_msg or "confirm you’re not a bot" in error_msg:
            detail = "Video requires sign-in/cookies (likely age-gated or bot-challenged). Ensure 'youtube_cookies.txt' is valid."
        else:
            detail = f"Failed to fetch video info: {error_msg}"
            
        raise HTTPException(status_code=500, detail=detail)


@app.get("/download")
async def download(url: str = Query(...), itag: str = Query(...), type: str = Query(default='video')):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
        
    try:
        # Use YDL_OPTS_INFO (which includes the cookie file) for download request
        ydl_opts_download = YDL_OPTS_INFO.copy()
        ydl_opts_download['format'] = itag 

        with YoutubeDL(ydl_opts_download) as ydl_specific:
            # FIX APPLIED: The fix is confirmed in YDL_OPTS_INFO and the extract_info call is clean.
            info = ydl_specific.extract_info(url, download=False)

        if not info:
            raise Exception("Could not extract video information for the specified format.")
            
        chosen_format = info.get('formats', [{}])[0]
        stream_url = chosen_format.get('url')
        
        if not stream_url:
            raise HTTPException(status_code=404, detail="Stream URL not found for the selected format.")

        # Sanitize title for filename
        title = info.get('title', 'video')
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        
        # Determine filename and headers
        extension = chosen_format.get('ext', 'mp4')
        content_type = chosen_format.get('mime_type') or "video/mp4" 

        filename = f"{safe_title}.{extension}"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
            "Content-Length": str(chosen_format.get('filesize') or chosen_format.get('filesize_approx', ''))
        }

        # Function to stream the file content
        def iterfile():
            CHUNK_SIZE = 16384
            # Pass the User-Agent header to the stream request
            req_headers = {'User-Agent': YDL_OPTS_INFO['http_headers']['User-Agent']}
            
            with requests.get(stream_url, stream=True, timeout=60, headers=req_headers) as r:
                r.raise_for_status() 
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        yield chunk

        return StreamingResponse(iterfile(), headers=headers, media_type=content_type)

    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to stream from source: HTTP Error {e.response.status_code}")
    except Exception as e:
        error_msg = str(e).split('\n')[0]
        raise HTTPException(status_code=500, detail=f"Download failed: {error_msg}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info", reload=True)
