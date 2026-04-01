FROM mcr.microsoft.com/playwright:v1.50.0-noble

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --break-system-packages claude-agent-sdk imapclient

COPY . .

ENV BROWSER_HEADLESS=true
RUN CHROME_PATH=$(find /ms-playwright -name "chrome" -path "*/chrome-linux/*" | head -1) \
    && echo "CHROME_PATH=${CHROME_PATH}" \
    && printf '%s' "$CHROME_PATH" > /tmp/chrome_path
ENV BROWSER_EXECUTABLE=""

RUN useradd -m agent && chown -R agent:agent /app
RUN mkdir -p /app/logs && chown agent:agent /app/logs

RUN printf '#!/bin/sh\nexport BROWSER_EXECUTABLE=$(cat /tmp/chrome_path)\nexec "$@"\n' > /entrypoint.sh \
    && chmod +x /entrypoint.sh

USER agent

VOLUME /app/logs

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "main.py"]
