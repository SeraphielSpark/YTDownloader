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
# Added 'extractor_args' to potentially help with certain age-gated/protected videos
YDL_OPTS_INFO = {
    'quiet': True,
    'skip_download': True,
    'no_warnings': True,
    'format': 'best',
    'extractor_args': {'youtube': {'skip_dash_manifest': True}}, # Faster info extraction
}

@app.get("/get-info")
async def get_info(url: str = Query(..., description="YouTube video URL")):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    try:
        # Pass a list of URLs for better error handling in case of a single bad URL
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            info = ydl.extract_info(url, download=False)
            
        if info is None:
            raise Exception("No video information could be extracted. It might be private, deleted, or age-gated.")

        formats = []
        for f in info.get('formats', []):
            # Only include formats that have a direct URL for streaming and are not too obscure
            if f.get('url') and (f.get('vcodec') != 'none' or f.get('acodec') != 'none'):
                # Clean up format_note for better frontend display
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
            # Prioritize the largest thumbnail for better preview quality
            'thumbnail': info.get('thumbnail') or info.get('thumbnails', [{}])[-1].get('url', ''),
            'lengthSeconds': info.get('duration'),
            'formats': formats
        }
    except Exception as e:
        # Catch yt-dlp specific errors like private videos
        error_msg = str(e).split('\n')[0] # Get the first line of the error
        raise HTTPException(status_code=500, detail=f"Failed to fetch video info: {error_msg}")


@app.get("/download")
async def download(url: str = Query(...), itag: str = Query(...), type: str = Query(default='video')):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")
        
    try:
        # Re-run extract_info to get the latest working stream URL (they expire quickly)
        with YoutubeDL(YDL_OPTS_INFO) as ydl:
            # Setting 'format' option here to specifically get the itag for stream URL
            ydl_opts_download = YDL_OPTS_INFO.copy()
            ydl_opts_download['format'] = itag
            
            # Using a new YoutubeDL instance with the specific format option
            with YoutubeDL(ydl_opts_download) as ydl_specific:
                info = ydl_specific.extract_info(url, download=False)

        if not info:
            raise Exception("Could not extract video information for the specified format.")
            
        chosen_format = info.get('formats', [{}])[0] # When 'format' is set, ydl.extract_info returns one format
        stream_url = chosen_format.get('url')
        
        if not stream_url:
            raise HTTPException(status_code=404, detail="Stream URL not found for the selected format.")

        title = info.get('title', 'video').replace('/', '_').replace('\\', '_').replace('"', '_').replace("'", "_")
        
        # Determine filename and headers based on the requested type and chosen format
        if type == 'mp3':
            extension = 'mp3'
            content_type = "audio/mpeg"
        else:
            # Use the format's extension, default to mp4
            extension = chosen_format.get('ext', 'mp4')
            # Use format's MIME type, default to video/mp4
            content_type = chosen_format.get('mime_type') or "video/mp4" 
            
        filename = f"{title}.{extension}"

        headers = {
            # Use 'attachment' to force download dialog in browser
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
            # Pass content length if available for better progress reporting (optional)
            "Content-Length": str(chosen_format.get('filesize') or chosen_format.get('filesize_approx', ''))
        }

        def iterfile():
            # Use a slightly larger chunk size for better streaming performance
            CHUNK_SIZE = 16384 
            # Stream directly from the YouTube URL (proxied through FastAPI)
            with requests.get(stream_url, stream=True, timeout=30) as r:
                r.raise_for_status() # Raise exception for bad status codes (4xx or 5xx)
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        yield chunk

        # The StreamingResponse is the key to acting as a proxy and avoiding memory issues
        return StreamingResponse(iterfile(), headers=headers, media_type=content_type)

    except requests.exceptions.HTTPError as e:
        # Catch 4xx/5xx errors from the video stream itself
        raise HTTPException(status_code=502, detail=f"Failed to stream from source: {e}")
    except Exception as e:
        error_msg = str(e).split('\n')[0]
        raise HTTPException(status_code=500, detail=f"Download failed: {error_msg}")

if __name__ == "__main__":
    import uvicorn
    # Use environment variable for port, defaulting to 8000 for local dev
    port = int(os.environ.get("PORT", 8000))
    # 'app:app' refers to the variable 'app' inside the file 'app.py' (or current file)
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info", reload=True)
