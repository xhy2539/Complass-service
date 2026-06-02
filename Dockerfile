FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Use aliyun mirror for faster apt downloads in China
RUN sed -i "s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# curl is used by the container healthcheck in docker-compose.yml.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    && pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

COPY reverse_rule_workflow/requirements.txt /tmp/rw_req.txt
RUN pip install --no-cache-dir -r /tmp/rw_req.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com 2>/dev/null || true

COPY app ./app
COPY reverse_rule_workflow /reverse_rule_workflow
COPY reverse_rule_workflow/data /app/data
COPY reverse_rule_workflow/storage /app/storage

ENV PYTHONPATH="/:${PYTHONPATH}"

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
