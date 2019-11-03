import logging

logginglevel = logging.INFO
telegram = dict(
    apiurl='https://api.telegram.org/bot',
    bottoken='952263958:AAHjVikhQazm41ofrx_mBuvXsSzBZl_BRc8',
    retry=30
)
strichliste = dict(
    apiurl='https://demo.strichliste.org/api',  # http://strichliste.fritz.box/api
    interval=5,
    activation_token_len=10
)
authorizedUsersFile = "authorizedUsers.json"
# truck = dict(
#     color='blue',
#     brand='ford',
# )
# city = 'new york'
# cabriolet = dict(
#     color='black',
#     engine=dict(
#         cylinders=8,
#         placement='mid',
#     ),
#     doors=2,
# )
