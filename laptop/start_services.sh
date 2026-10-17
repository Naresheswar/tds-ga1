#!/usr/bin/env bash
# Starts Ollama (CORS open), the Redis+API compose stack, and two public tunnels.
cd ~/tds/compose
# restart Ollama with CORS allowed for the exam page
(sudo systemctl stop ollama 2>/dev/null || true); pkill -f "ollama serve" 2>/dev/null || true; sleep 1
(OLLAMA_ORIGINS='*' nohup ollama serve >/tmp/ollama.log 2>&1 &)
docker compose up -d --build
sleep 3
(nohup cloudflared tunnel --url http://localhost:8000 >/tmp/tunnel-api.log 2>&1 &)
(nohup cloudflared tunnel --url http://localhost:11434 --http-host-header localhost:11434 >/tmp/tunnel-llm.log 2>&1 &)
sleep 12
echo "API (GA2 Q6) tunnel:    $(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/tunnel-api.log | head -1)"
echo "Ollama (GA2 Q9) tunnel: $(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/tunnel-llm.log | head -1)"
curl -s localhost:8000/healthz; echo
