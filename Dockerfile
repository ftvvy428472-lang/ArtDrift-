FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект (включая index.html, папки models, maps, images)
COPY . .

# Render передаёт порт через переменную окружения PORT
CMD uvicorn main:socket_app --host 0.0.0.0 --port ${PORT:-10000}
