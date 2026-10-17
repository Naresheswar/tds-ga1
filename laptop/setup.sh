#!/usr/bin/env bash
# One-time setup inside WSL Ubuntu for the TDS laptop questions.
set -e
sudo apt-get update -y
sudo apt-get install -y curl xxd ca-certificates tar
# termlog (prebuilt Linux binary)
curl -fsSL -o /tmp/termlog https://github.com/mynkpdr/termlog/releases/download/v0.2.0/termlog-x86_64-unknown-linux-musl
chmod +x /tmp/termlog && sudo mv /tmp/termlog /usr/local/bin/termlog
# cloudflared (quick tunnels)
curl -fsSL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
# Ollama
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
# make sure an Ollama server is running, then pull a small model
if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null; then
  (OLLAMA_ORIGINS='*' nohup ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 5
fi
ollama pull qwen2.5:1.5b
# compose project files
mkdir -p ~/tds/compose && cd ~/tds/compose
for f in docker-compose.yml Dockerfile main.py requirements.txt; do
  curl -fsSL -o "$f" "https://raw.githubusercontent.com/Naresheswar/tds-ga1/main/laptop/compose/$f"
done
echo
echo "SETUP DONE. Versions:"; termlog --version || true; cloudflared --version; ollama --version
command -v docker >/dev/null && docker --version || echo "!! docker not found in WSL: turn on Docker Desktop > Settings > Resources > WSL integration"
