# WeatherAI — Open-Meteo First, Variable-Agnostic Chatbot

This repo houses a deterministic **MCP server** (TypeScript), a **Streamlit UI** (Python),
and an optional **LLM writer** layer. The agent can answer any question grounded in
Open-Meteo data: current, forecast, or historical/climatology — at a point or across a region.

## Running locally
1) Start MCP:
```bash
cd mcp_server
npm i
npm run dev
```
2)	Start Streamlit:
```bash
cd ../apps/streamlit_app
pip install -r requirements.txt
streamlit run app.py
```
Now open http://localhost:8501. LLM is optional and not required.
### `.gitignore`
```gitignore
# Node
node_modules/
dist/
npm-debug.log*

# Python
__pycache__/
.venv/
.env
.ipynb_checkpoints/
*.pyc

# Data/Cache
data/cache/
mcp_server/cache/
*.png
*.csv
*.jsonl

# OS
.DS_Store

# LICENSE

MIT License (placeholder)
Copyright (c) 2025
Permission is hereby granted, free of charge, to any person obtaining a copy...