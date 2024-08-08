FROM python:3.11-slim-buster

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH "${PYTHONPATH}:/app"

CMD ["python", "demo/discord_bot.py"]