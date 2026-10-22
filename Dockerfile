FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY split_contrast.py split_parts.py app.py ./
ENV PORT=8000
CMD gunicorn -b 0.0.0.0:$PORT -w 1 --timeout 600 app:app
