FROM python:3.11-slim-buster

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY requirements.txt requirements.txt

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set PYTHONPATH environment variable
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Run the application
CMD ["python", "demo/discord_bot.py"]