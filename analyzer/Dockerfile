FROM python:3.12-slim
ARG DEV=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 analyzer
WORKDIR /srv
COPY requirements.lock requirements-dev.lock ./
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN if [ "$DEV" = "1" ]; then pip install --no-cache-dir -r requirements-dev.lock --extra-index-url $TORCH_INDEX; \
    else pip install --no-cache-dir -r requirements.lock --extra-index-url $TORCH_INDEX; fi
RUN mkdir -p /opt/models && chmod 755 /opt/models
# Pesos pré-treinados do BTC (MIT): commit fixado e SHA-256 verificado pelo build
ADD --checksum=sha256:1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51 --chmod=644 \
    https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/2682317be668032e6e4b269ded36adaa2ad57df0/test/btc_model_large_voca.pt \
    /opt/models/btc_large_voca.pt
COPY app ./app
COPY tests ./tests
USER analyzer
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
