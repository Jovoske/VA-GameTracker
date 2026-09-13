FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 camera \
    && useradd --uid 10001 --gid camera --no-create-home camera \
    && mkdir -p /spool && chown camera:camera /spool
COPY receiver.py ./
USER 10001:10001
EXPOSE 2121 50000-50009
CMD ["python", "receiver.py"]
