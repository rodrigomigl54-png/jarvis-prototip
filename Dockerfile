# Jarvis on a PC / server (phone features need Termux on Android and are off here).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY jarvis ./jarvis
ENV PHONE_MODE=off HUD_HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "-m", "jarvis"]
