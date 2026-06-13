FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# postgresql-client: pg_isready for entrypoint. libgl1/libglib2: OpenCV (via MegaDetector).
RUN apt-get update && apt-get install -y --no-install-recommends \
      postgresql-client libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only torch from the PyTorch CPU index (avoids pulling ~2 GB of CUDA libraries).
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 \
      --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]
