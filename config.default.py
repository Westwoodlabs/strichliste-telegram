import logging

logginglevel = logging.INFO
telegram = dict(
    apiurl='https://api.telegram.org/bot',
    bottoken='<enter telegram bottoken here>',
    retry=30
)
strichliste = dict(
    apiurl='https://demo.strichliste.org/api',
    interval=5,
    activation_token_len=10
)
authorizedUsersFile = "authorizedUsers.json"