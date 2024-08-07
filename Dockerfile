FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 80

ENV PYTHONPATH=/app

RUN useradd -m myuser
USER myuser

HEALTHCHECK CMD curl -f http://localhost:80/health || exit 1

CMD ["python", "bot/discord_bot.py"]
