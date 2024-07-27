
FROM python:3

COPY ./ /usr/src/app

WORKDIR /usr/src/app

RUN pip install --no-cache-dir -r /usr/src/app/requirements.txt

CMD [ "python", "./bot.py" ]