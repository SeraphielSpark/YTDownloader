import express from 'express';
import cors from 'cors';
import ytdl from '@distube/ytdl-core';
import ffmpegPath from 'ffmpeg-static';
import ffmpeg from 'fluent-ffmpeg';

// ✅ Disable ytdl-core update check to avoid 403 error
process.env.YTDL_NO_UPDATE = '1';

const app = express();
app.use(cors());

ffmpeg.setFfmpegPath(ffmpegPath);

// Helper: handle YouTube "are you human?" error
function handleYTError(err, res) {
  if (err && err.message && err.message.includes("Sign in to confirm you’re not a bot")) {
    return res.status(429).json({
      error: 'YouTube requires human verification (CAPTCHA).',
      message: 'Please try again later or use a different video link.'
    });
  }
  console.error(err);
  res.status(500).json({ error: 'Failed to process request', details: err.message });
}

// Get video info endpoint
app.get('/get-info', async (req, res) => {
  try {
    const url = req.query.url;
    if (!url || !ytdl.validateURL(url)) {
      return res.status(400).json({ error: 'Invalid YouTube URL' });
    }

    const info = await ytdl.getInfo(url);
    const formats = ytdl.filterFormats(info.formats, (format) => {
      return format.hasVideo || format.hasAudio;
    });

    res.json({
      title: info.videoDetails.title,
      author: info.videoDetails.author?.name,
      thumbnail: info.videoDetails.thumbnails?.pop()?.url,
      lengthSeconds: info.videoDetails.lengthSeconds,
      formats: formats.map(f => ({
        itag: f.itag,
        container: f.container,
        qualityLabel: f.qualityLabel || (f.hasAudio ? 'Audio' : 'Unknown'),
        hasVideo: f.hasVideo,
        hasAudio: f.hasAudio,
        mimeType: f.mimeType
      }))
    });
  } catch (err) {
    handleYTError(err, res);
  }
});

// Download endpoint
app.get('/download', async (req, res) => {
  try {
    const { url, itag, type } = req.query;
    if (!url || !itag) return res.status(400).json({ error: 'Missing URL or itag' });

    const info = await ytdl.getInfo(url);
    const format = info.formats.find(f => f.itag.toString() === itag.toString());
    if (!format) return res.status(404).json({ error: 'Format not found' });

    const title = info.videoDetails.title.replace(/[^\w\s.-]/g, '_');
    const extension = type === 'mp3' ? 'mp3' : format.container || 'mp4';
    const filename = `${title}.${extension}`;

    res.header({
      'Content-Disposition': `attachment; filename="${filename}"`,
      'Content-Type': type === 'mp3' ? 'audio/mpeg' : 'video/mp4'
    });

    if (type === 'mp3') {
      const audioStream = ytdl(url, { format, quality: 'highestaudio' });

      ffmpeg(audioStream)
        .audioBitrate(128)
        .toFormat('mp3')
        .on('error', (err) => {
          handleYTError(err, res);
        })
        .pipe(res);
    } else {
      ytdl(url, { format })
        .on('error', (err) => {
          handleYTError(err, res);
        })
        .pipe(res);
    }
  } catch (err) {
    handleYTError(err, res);
  }
});

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`🚀 Server running on http://localhost:${PORT}`);
});
