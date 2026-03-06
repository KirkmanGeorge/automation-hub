FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxss1 \
    fonts-liberation \
    wget \
    poppler-utils \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    echo ">>> CHROMIUM:" && which chromium || which chromium-browser || true && \
    echo ">>> CHROMEDRIVER:" && which chromedriver || true && \
    ls -la /usr/bin/chrom* 2>/dev/null || true && \
    ls -la /usr/lib/chromium* 2>/dev/null || true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
