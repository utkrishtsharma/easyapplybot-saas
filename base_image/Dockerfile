FROM python:3.9-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome 135.0.7049.116
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/135.0.7049.116/linux64/chrome-linux64.zip \
    && unzip chrome-linux64.zip -d /usr/local/ \
    && ln -s /usr/local/chrome-linux64/chrome /usr/local/bin/google-chrome \
    && rm chrome-linux64.zip

# Install matching ChromeDriver 135.0.7049.116
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/135.0.7049.116/linux64/chromedriver-linux64.zip \
    && unzip chromedriver-linux64.zip -d /usr/local/bin/ \
    && mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && rm -rf chromedriver-linux64.zip /usr/local/bin/chromedriver-linux64

# Install Python dependencies (e.g., Selenium)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Set working directory
WORKDIR /app

# Keep container running for testing
CMD ["tail", "-f", "/dev/null"]