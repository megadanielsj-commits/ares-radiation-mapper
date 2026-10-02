FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/vendor/go2_runtime/src
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY vendor/go2_runtime/requirements-go2-wifi.txt /app/go2-requirements.txt
RUN apt-get update && apt-get install --yes --no-install-recommends libusb-1.0-0 \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip install -r go2-requirements.txt \
 && python -m pip install --no-deps unitree_webrtc_connect==2.2.0 \
 && python -m pip install '.[radiacode-usb]'
COPY config ./config
COPY vendor/go2_runtime ./vendor/go2_runtime
COPY tools/operator_console ./tools/operator_console
COPY tools/radiacode_usb ./tools/radiacode_usb
RUN python -m tools.operator_console.check_map_lock \
 && python -c 'from tools.operator_console.server import create_app; from ares.robo import _compat; import unitree_webrtc_connect, radiacode; create_app("/tmp/check", manage_usb=False)'
CMD ["python", "-m", "tools.operator_console.server"]
