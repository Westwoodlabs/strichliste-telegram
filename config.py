import logging

logginglevel = logging.INFO
telegram = dict(
    apiurl='https://api.telegram.org/bot',
    bottoken='952263958:AAHjVikhQazm41ofrx_mBuvXsSzBZl_BRc8',
    retry=30
)
strichliste = dict(
    apiurl='http://strichliste.fritz.box/api',
    interval=5,
    activation_token_len=10
)
authorizedUsersFile = "authorizedUsers.json"