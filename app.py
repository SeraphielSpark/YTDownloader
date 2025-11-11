import os
import requests
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
    # 🌟 NEW: Set a consistent, standard User-Agent to appear more like a browser.
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    },
    # 🌟 NEW: Prefer formats that are less likely to trigger bot checks (e.g., not pure DASH streams)
    # This format string prioritizes best quality non-DASH streams (with audio/video combined)
    # If a combined format is not available, it defaults to the best available format.
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best', 
    'extractor_args': {'youtube': {'skip_dash_manifest': True, 'player_client': 'web'}},
    'retries': 3, # Add a few retries for transient network issues
    'socket_timeout': 15, # Set a timeout for network operations
}

@app.get("/get-info")
async def get_info(url: str = Query(..., description="YouTube video URL")):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    try:
        # Use a fresh instance of YoutubeDL for each request
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)
            
        if info is None:
            raise Exception("No video information could be extracted. It might be private, deleted, or age-gated.")

        # The format extraction logic remains correct, ensuring we get streamable formats
        formats = []
        for f in info.get('formats', []):
            if f.get('url') and (f.get('vcodec') != 'none' or f.get('acodec') != 'none'):
                quality_label = f.get('format_note') or f.get('quality')
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
        # 🌟 IMPROVED ERROR: Use explicit check for the Sign-in error
        error_msg = str(e).split('\n')[0]
        if "Sign in to confirm" in error_msg:
             # Provide a more specific and helpful error to the user
            detail = "Video requires sign-in (e.g., age-gated). Your server cannot access it without a cookie session."
        else:
            detail = f"Failed to fetch video info: {error_msg}"
            
        raise HTTPException(status_code=500, detail=detail)


@app.get("/download")
async def download(url: str = Query(...), itag: str = Query(...), type: str = Query(default='video')):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
        
    try:
        # Re-run extract_info to get the latest working stream URL (they expire quickly)
        # Using a copy of YDL_OPTS_INFO to add the specific format request
        ydl_opts_download = YDL_OPTS_INFO.copy()
        ydl_opts_download['format'] = itag # Target the specific format ID (itag)

        with YoutubeDL(ydl_opts_download) as ydl_specific:
            # We only extract info, the download happens via proxy streaming
            info = ydl_specific.extract_info(url, download=False)

        if not info:
            raise Exception("Could not extract video information for the specified format.")
            
        # When 'format' is set, yt-dlp returns the chosen format as the first/only item in 'formats' list
        chosen_format = info.get('formats', [{}])[0]
        stream_url = chosen_format.get('url')
        
        if not stream_url:
            raise HTTPException(status_code=404, detail="Stream URL not found for the selected format.")

        title = info.get('title', 'video').replace('/', '_').replace('\\', '_').replace('"', '_').replace("'", "_")
        
        # Determine filename and headers
        if type == 'mp3':
            extension = 'mp3'
            content_type = "audio/mpeg"
        else:
            extension = chosen_format.get('ext', 'mp4')
            content_type = chosen_format.get('mime_type') or "video/mp4" 
            
        filename = f"{title}.{extension}"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
            "Content-Length": str(chosen_format.get('filesize') or chosen_format.get('filesize_approx', ''))
        }

        # IMPORTANT: When streaming the downloaded URL, pass the User-Agent again
        def iterfile():
            CHUNK_SIZE = 16384
            # Pass the User-Agent header to the stream request to mimic yt-dlp's behavior
            req_headers = {'User-Agent': YDL_OPTS_INFO['http_headers']['User-Agent']}
            
            with requests.get(stream_url, stream=True, timeout=30, headers=req_headers) as r:
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
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info", reload=True)
