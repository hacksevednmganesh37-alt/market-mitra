# Hugging Face Docker Space for Market Mitra.
# The Space only needs this Dockerfile + README.md; the code is pulled from GitHub at build time.
# Set these as Space secrets: GEMINI_API_KEY, MITRA_ANALYST_ID, MITRA_ANALYST_KEY, MITRA_TRADER_ID, MITRA_TRADER_KEY
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

RUN pip install --no-cache-dir --user "band-sdk[langgraph]==9.1.0" "google-genai>=1.0.0" "pyyaml>=6.0" \
    "fastapi>=0.110" "uvicorn>=0.29" "yfinance>=0.2.40" "pandas>=2.0"

# change this value (or use "Factory rebuild") to pull the latest code
ARG CODE_VERSION=1
RUN git clone --depth 1 https://github.com/hacksevednmganesh37-alt/market-mitra.git .

EXPOSE 7860
CMD ["bash", "scripts/run_space.sh"]
