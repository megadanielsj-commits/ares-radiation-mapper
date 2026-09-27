# syntax=docker/dockerfile:1

FROM python:3.10-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY config ./config

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)" || exit 1

ENTRYPOINT ["ares-map", "start"]
CMD ["--mode", "simulation", "--host", "0.0.0.0", "--no-open-browser"]


FROM base AS unitree-sdk-builder

ARG UNITREE_SDK2_COMMIT=65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && python -m pip wheel --no-cache-dir --no-deps \
        --wheel-dir /wheels \
        "git+https://github.com/unitreerobotics/unitree_sdk2_python.git@${UNITREE_SDK2_COMMIT}" \
    && rm -rf /var/lib/apt/lists/*


FROM base AS hardware

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=unitree-sdk-builder /wheels /wheels
RUN python -m pip install --no-cache-dir \
        "pyserial>=3.5,<4" \
        /wheels/unitree_sdk2py-*.whl \
    && rm -rf /wheels

CMD ["--mode", "hardware", "--host", "0.0.0.0", "--no-open-browser"]


FROM base AS simulation


# USB access stays in its own image: the legacy FS-5000/Go2 profile is unchanged.
FROM base AS radiacode

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir '.[radiacode-usb]'
COPY tools/radiacode_usb ./tools/radiacode_usb

ENTRYPOINT ["bash", "/app/tools/radiacode_usb/docker-entrypoint.sh"]
CMD ["record", "--seconds", "60"]
