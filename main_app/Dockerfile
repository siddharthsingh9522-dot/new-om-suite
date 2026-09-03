# Plain Render "python" web services don't have a Chrome/Chromium binary,
# which is why the GST Query screen (Selenium-driven captcha solving)
# always showed "not available" — webdriver-manager can download a
# matching *driver*, but not the browser itself. This Dockerfile adds
# Chromium so that screen works. Every other tool in the suite (CN,
# Party, Master, Branch, Customer, TBB/Bill Mail) doesn't need this and
# would run fine on the plain "python" runtime too — this image is only
# required for GST Query.

FROM python:3.11-slim

# Chromium + matching driver, straight from Debian's own repo so the
# browser and chromedriver versions always match each other (avoids the
# classic "this version of ChromeDriver only supports Chrome version X"
# failure you get when downloading them from two different places).
# Note: libgconf-2-4 was removed from Debian's repos years ago (it was
# only ever needed by very old Chrome versions) — including it here
# breaks the whole install with "unable to locate package", so it's
# deliberately left out.
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tell Selenium exactly where the browser lives instead of relying on
# webdriver-manager to guess/download one — see gst_search.py's
# open_browser(), which reads these two env vars when present.
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime; gunicorn must bind to it.
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
