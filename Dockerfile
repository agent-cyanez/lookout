FROM python:3.12-alpine
WORKDIR /app
COPY lookout.py .
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "lookout.py"]
