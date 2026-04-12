FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python -c "from backend.init_db import init_db; init_db()"

EXPOSE 10000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "10000"]
