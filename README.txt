# TGSpyder 

TGSpyder is an open-source Telegram OSINT CLI tool by **Darksight Analytics**.

## Features
- Scrape **members** list to CSV
- Scrape **chat messages** to CSV
- Extract **t.me invite links** from chat history
- Look up a **Telegram user** by username or (limited) numeric ID
- Identify **sticker pack creator ID** (inferred via sticker set ID)
- Proxy support:
  - Save proxy (`--set-proxy`)
  - Remove proxy (`--remove-proxy`)
  - One-off proxy override (`--proxy`)

## Requirements
- Python 3.10+

## Install
```bash
git clone https://github.com/Darksight-Analytics/tgspyder.git
cd tgspyder
pip install -r requirements.txt
pip install -e .


