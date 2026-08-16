FROM python:3.12-alpine
WORKDIR /app
COPY lookout.py .
USER nobody
ENTRYPOINT ["python3", "lookout.py"]
