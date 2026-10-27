# The CustomClassic Chat bot. Built from the repository's root (it uses the app's guild_relay.py):
#   docker compose -f bot/docker-compose.yml up -d --build
FROM python:3.12-slim
WORKDIR /app
COPY bot/requirements.txt bot/requirements.txt
RUN pip install --no-cache-dir -r bot/requirements.txt
COPY guild_relay.py ./
COPY bot/ccchat_bot.py bot/
RUN useradd --create-home bot && mkdir -p /data && chown bot /data
USER bot
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
CMD ["python", "bot/ccchat_bot.py"]
