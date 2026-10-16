FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY public ./public
COPY app.config.ts ./

ENV PORT=3000 \
    APP_ENV=production
EXPOSE 3000
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-3000} --workers 2 --threads 4 --timeout 60 app:app"]
