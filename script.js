import express from 'express';
import cors from 'cors';
import { exec } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const app = express();
app.use(cors());

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Path for temporary downloads
const TEMP_DIR = path.join(__dirname, 'temp');
if (!fs.existsSync(TEMP_DIR)) fs.mkdirSync(TEMP_DIR);

// Headers to mimic a real browser
const BROWSER_HEADERS = `
--add-header "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36" 
--add-header "Accept-Language: en-US,en;q=0.9"
`;

// Get video info endpoint
app.get('/get-info', (req, res) => {
  const url = req.query.url;
  if (!url) return res.status(400).json({ error: 'Invalid YouTube URL' });

  exec(`yt-dlp --dump-json ${BROWSER_HEADERS} "${url}"`, { maxBuffer: 1024 * 1024 * 10 }, (err, stdout, stderr) => {
    if (err) {
      console.error(stderr);
      return res.status(500).json({ error: 'Failed to fetch video info' });
    }
    try {
      const info = JSON.parse(stdout);
      const formats = info.formats.map(f => ({
        itag: f.format_id,
        container: f.ext,
        qualityLabel: f.resolution || f.quality || 'Unknown',
        hasVideo: !!f.vcodec && f.vcodec !== 'none',
        hasAudio: !!f.acodec && f.acodec !== 'none',
        mimeType: f.mime_type || ''
      }));

      res.json({
        title: info.title,
        author: info.uploader,
        thumbnail: info.thumbnail,
        lengthSeconds: info.duration,
        formats
      });
    } catch (parseErr) {
      console.error(parseErr);
      res.status(500).json({ error: 'Error parsing video info' });
    }
  });
});

// Download endpoint
app.get('/download', (req, res) => {
  const { url, itag, type } = req.query;
  if (!url || !itag) return res.status(400).json({ error: 'Missing URL or itag' });

  const safeTitle = `video_${Date.now()}`;
  const ext = type === 'mp3' ? 'mp3' : 'mp4';
  const filePath = path.join(TEMP_DIR, `${safeTitle}.${ext}`);

  let formatArg = `-f ${itag}`;
  if (type === 'mp3') {
    formatArg = `-x --audio-format mp3`;
  }

  const cmd = `yt-dlp ${BROWSER_HEADERS} ${formatArg} -o "${filePath}" "${url}"`;
  console.log('Running:', cmd);

  exec(cmd, { maxBuffer: 1024 * 1024 * 50 }, (err, stdout, stderr) => {
    if (err) {
      console.error(stderr);
      return res.status(500).json({ error: 'Download failed' });
    }

    res.download(filePath, `${safeTitle}.${ext}`, (downloadErr) => {
      if (downloadErr) console.error(downloadErr);
      fs.unlink(filePath, () => {}); // cleanup
    });
  });
});
const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`🚀 Server running on port ${PORT}`);
});
