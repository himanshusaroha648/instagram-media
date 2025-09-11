# Instagram Auto-Responder - Replit Setup

## 🚀 Quick Start for Replit

### 1. Setup Steps:
1. **Upload all files** to your Replit project
2. **Install dependencies**: Run `pip install -r requirements.txt`
3. **Set up your accounts**: Put your Instagram account JSON files in `accounts/` folder
4. **Create thread.txt**: Add Instagram thread IDs (one per line)
5. **Run the bot**: Execute `python replit_runner.py`

### 2. Files Structure:
```
├── replit_runner.py      # Main runner for Replit
├── keep_alive.py         # Keep-alive server (port 8080)
├── main.py              # Your main Instagram bot
├── src/
│   ├── direct.py        # Instagram DM functions
│   ├── linkfetch.py     # xHamster link fetcher
│   ├── downloder.py     # Video downloader
│   └── split.py         # Video splitter
├── xhamster/
│   └── download.py      # Alternative downloader
├── requirements.txt     # Python dependencies
└── replit.nix          # Replit system packages
```

### 3. Environment Variables (Optional):
- `INSTAGRAM_USERNAME`: Your Instagram username
- `INSTAGRAM_PASSWORD`: Your Instagram password

### 4. How it Works:
- **Keep-alive server** runs on port 8080 to prevent Replit from sleeping
- **Main bot** runs continuously with your schedule:
  - Pipeline runs every 5 minutes (8:00-22:00)
  - Account rotation every 90 minutes
  - Sleeps 22:00-08:00
- **Auto-restart** if the bot crashes

### 5. Monitoring:
- Visit your Replit URL to see "Instagram Auto-Responder is running! 🚀"
- Check console logs for detailed activity
- Bot will automatically restart if it encounters errors

### 6. Troubleshooting:
- If videos don't download: Check if `ffmpeg` is installed
- If Instagram login fails: Verify account credentials in JSON files
- If bot stops: Check console for error messages

## 🔧 Commands:
```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python replit_runner.py

# Test individual components
python src/linkfetch.py
python src/downloder.py "https://example.com"
python src/split.py
```

## 📝 Notes:
- The bot will run 24/7 on Replit
- Keep-alive server prevents Replit from sleeping
- All videos are processed and sent automatically
- Account rotation happens every 90 minutes
- Pipeline (fetch → download → split) runs every 5 minutes
