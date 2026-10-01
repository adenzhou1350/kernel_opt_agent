FROM ghcr.io/astral-sh/uv@sha256:a041b350d5d9483b538d5af07e9553ee8cbc7fc7fa90c2f7d20d93f18ce9bbd1
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never PIP_DISABLE_PIP_VERSION_CHECK=1
COPY source.tar /tmp/source.tar
RUN mkdir /opt/httpx && tar -xf /tmp/source.tar -C /opt/httpx && rm /tmp/source.tar
WORKDIR /opt/httpx
RUN uv pip install --system --python /usr/local/bin/python -r requirements.txt
RUN uv pip freeze --system --python /usr/local/bin/python > /opt/dependencies.freeze.txt
ENV GITHUB_ACTIONS=true PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
USER 65534:65534
