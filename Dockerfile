FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-real.txt pyproject.toml ./
COPY src ./src

# Dependências de núcleo primeiro; o driver do Go2 (unitree_webrtc_connect) é
# instalado com --no-deps para não puxar áudio/microfone que o ARES não usa,
# igual ao go2_wifi_quickstart. Câmera usa opencv headless (sem X11 no container).
RUN pip install -r requirements.txt \
 && pip install --no-deps unitree_webrtc_connect \
 && pip install \
        "aiortc>=1.9.0" pycryptodome requests curl_cffi wasmtime lz4 packaging \
        opencv-python-headless \
 && pip install -e .

COPY . .

EXPOSE 8000
CMD ["python", "-m", "ares"]
