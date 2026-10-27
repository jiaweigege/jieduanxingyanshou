FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /instance/uploads

EXPOSE 5000

CMD ["sh", "-c", "flask --app wsgi init-db && flask --app wsgi backfill-knowledge-index && flask --app wsgi run --host=0.0.0.0 --port=5000"]
