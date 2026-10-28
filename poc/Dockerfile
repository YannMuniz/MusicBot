FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /poc
COPY requirements.in /poc/requirements.in
RUN pip install --no-cache-dir -r requirements.in && pip freeze > /poc/requirements.lock

COPY analyze.py /poc/analyze.py
ENTRYPOINT ["python", "-I", "/poc/analyze.py"]
