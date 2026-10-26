FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY sheetmusic ./sheetmusic
RUN pip install --no-cache-dir ".[bot]"
CMD ["python", "-m", "sheetmusic", "bot"]
