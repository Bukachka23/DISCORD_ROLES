FROM python:3.11-slim-buster

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY src/data/pic.jpg src/data/pic.jpg

ENV PYTHONPATH "${PYTHONPATH}:/app"

CMD ["python", "src/main.py"]