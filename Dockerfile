FROM python:3.7

WORKDIR /usr/src/app

VOLUME [ "/data" ]
VOLUME [ "/config" ]

ENV DATABASE_FILE /data/db.pickle
ENV SERVER_PORT 80
ENV GITHUB_PRIVATE_KEY_PATH /config/key.pem


COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "-m", "bot" ]