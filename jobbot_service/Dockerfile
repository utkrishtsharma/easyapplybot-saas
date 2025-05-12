FROM ghcr.io/your-username/base-jobbot:latest

COPY worker.py /app/worker.py
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

CMD ["python", "worker.py"]