FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core.py cloud.py config.example.json ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "cloud.py", "process"]
