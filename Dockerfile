FROM python:3.12-slim

# Unbuffered stdout/stderr: without this, Python buffers output and a
# process killed abruptly (e.g. OOM) can lose all logs — exactly the
# "container restarts with empty logs" symptom this fixes visibility into.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]