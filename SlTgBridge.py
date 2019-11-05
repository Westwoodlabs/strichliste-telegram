#!/usr/bin/python3 -u

from enum import Enum
from urllib.parse import urlencode
from datetime import datetime
import logging
import threading
import os.path
import time
import json
import requests
import config
import traceback
import re
import random
import string
import html


# Refernces
# https://github.com/strichliste/strichliste-backend/blob/master/docs/API.md
# https://www.python-kurs.eu/threads.php
# https://mcuoneclipse.com/2019/04/01/log2ram-extending-sd-card-lifetime-for-raspberry-pi-lorawan-gateway/
# https://github.com/fabianonline/OctoPrint-Telegram/blob/stable/octoprint_telegram/__init__.py
# https://www.thomaschristlieb.de/ein-python-script-mit-systemd-als-daemon-systemd-tut-garnicht-weh/

scriptdir = os.path.dirname(os.path.realpath(__file__))


class ExitThisLoopException(Exception):
    pass


class TransactionType(Enum):
    BUY_ARTICLE = 1
    SEND_MONEY = 2
    RECEIVE_MONEY = 3
    RECHARGE = 4


class TelegramListener(threading.Thread):
    def __init__(self, main):
        threading.Thread.__init__(self)
        self.update_offset = 0
        self.first_contact = True
        self.main = main
        self.do_stop = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self):
        self.logger.debug("Try first connect.")
        self.tryFirstContact()
        # repeat fetching and processing messages unitil thread stopped
        self.logger.debug("Listener is running.")
        try:
            while not self.do_stop:
                try:
                    self.loop()
                except ExitThisLoopException:
                    # do nothing, just go to the next loop
                    pass
        except Exception as ex:
            self.logger.error("An Exception crashed the Listener: " +
                              str(ex) + " Traceback: " + traceback.format_exc())

        self.logger.debug("Listener exits NOW.")

    # Try to get first contact. Repeat every config.telegram['retry']sek if no success
    # or stop if task stopped
    def tryFirstContact(self):
        gotContact = False
        while not self.do_stop and not gotContact:
            try:
                self.username = self.test_token()
                gotContact = True
                # self.set_status(gettext("Connected as %(username)s.", username=self.username), ok=True)
                self.logger.info("Connected as %s.", self.username)
            except Exception as ex:
                self.logger.warning(
                    "Got an exception while initially trying to connect to telegram (Listener not running: %(ex)s.  Waiting before trying again.)", ex=ex)
                time.sleep(config.telegram['retry'])

    def loop(self):
        chat_id = ""
        json = self.getUpdates()
        try:
            # seems like we got a message, so lets process it.
            for message in json['result']:
                self.processMessage(message)
        except ExitThisLoopException as exit:
            raise exit
        # wooooops. can't handle the message
        except Exception as ex:
            self.logger.error("Exception caught in loop! " +
                              str(ex) + " Traceback: " + traceback.format_exc())
            # self.set_status(gettext("Connected as %(username)s.", username=self.username), ok = True)
            self.logger.info("Connected as %s.", self.username)
        # we had first contact after octoprint startup
        # so lets send startup message
        if self.first_contact:
            self.first_contact = False

    def set_update_offset(self, new_value):
        if new_value >= self.update_offset:
            self.logger.debug("Updating update_offset from {} to {}".format(
                self.update_offset, 1 + new_value))
            self.update_offset = 1 + new_value
        else:
            self.logger.debug(
                "Not changing update_offset - otherwise would reduce it from {} to {}".format(self.update_offset, 1 + new_value))

    def processMessage(self, message):
        self.logger.info("MESSAGE: " + str(message))
        # Get the update_id to only request newer Messages the next time
        self.set_update_offset(message['update_id'])
        # no message no cookies
        if 'message' in message and message['message']['chat']:

            chat_id, from_id = self.parseUserData(message)

            if "text" in message['message']:
                self.handleTextMessage(message, chat_id, from_id)
            else:
                self.logger.warning(
                    "Got an unknown message. Doing nothing. Data: " + str(message))
        else:
            self.logger.warning(
                "Response is missing .message or .message.chat or callback_query. Skipping it.")
            raise ExitThisLoopException()

    def handleTextMessage(self, message, chat_id, from_id):
        # We got a chat message.
        # handle special messages from groups (/commad@BotName)
        command = str(message['message']['text'].split('@')[0])

        sl_id = self.main.isAuthorizedUser(telegram_chat_id=chat_id)

        self.logger.info("Got a command: '%s' in chat %s",
                         command, message['message']['chat']['id'])

        if command == "/start" or command == "/help":
            self.main.send_msg(
                "Welcome to the <b>Strichliste Telegram Bridge</b>!\nEnter / in the chat or click on the [/] to see all available commands.", chatID=chat_id, markup="HTML")

        elif command == "/map":

            while True:
                token = self.main.randomStringDigits(
                    config.strichliste['activation_token_len'])
                if self.main.pendingActivations.get(token) == None:
                    break

            self.main.send_msg(
                "Send money to someone user within the next <b>two</b> minutes (can be undo immediately) with the following token in the note:\n\n<code>%s</code>" % token, markup="HTML", chatID=chat_id)
            self.main.pendingActivations[token] = dict(
                time=time.time(), chatid=chat_id)
        else:

            if not sl_id:  # unauthorized user

                if command == "/unmap" or command == "/me" or command == "/balance":

                    self.main.send_msg(
                        "You are not allowed to do this!\nYou must first /map your Telegram to your Strichliste account!", chatID=chat_id)
                else:
                    self.main.send_msg(
                        "Unkown command. Enter / in the chat or click on the [/] to see all available commands.", chatID=chat_id)
            else:

                if command == "/unmap":

                    self.main.send_msg(
                        "You won't get any more notifications from now on.", markup="HTML", chatID=chat_id)
                    self.main.deleteAuthorizedUsers(sl_id)

                elif command == "/me":

                    userinfo = self.main.getUserInfo(sl_id)['user']

                    message = str("User-ID: <b>%d</b>\n"
                                  "Username: <b>%s</b>\n"
                                  "eMail: <b>%s</b>\n"
                                  "Balance: <b>%.2lf€</b>\n"
                                  "Active: <b>%s</b>\n"
                                  "Disabled: <b>%s</b>\n"
                                  "User created: <b>%s</b>\n"
                                  "Last activity: <b>%s</b>\n" %
                                  (
                                      userinfo['id'],
                                      html.escape(userinfo['name']),
                                      ("---" if userinfo['email'] ==
                                       None or userinfo['email'] == "" else html.escape(userinfo['email'])),
                                      (userinfo['balance']/100),
                                      ("Yes" if userinfo['isActive']
                                       else "No"),
                                      ("Yes" if userinfo['isDisabled']
                                       else "No"),
                                      userinfo['created'],
                                      userinfo['updated']))

                    self.main.send_msg(
                        message, chatID=chat_id, markup="HTML")

                elif command == "/balance":

                    userinfo = self.main.getUserInfo(sl_id)['user']

                    message = str("Your current balance is <b>%.2lf€</b>" %
                                  ((userinfo['balance']/100)))

                    self.main.send_msg(message, chatID=chat_id, markup="HTML")

                else:
                    self.main.send_msg(
                        "Unkown command. Enter / in the chat or click on the [/] to see all available commands.", chatID=chat_id)

    def parseUserData(self, message):
        chat = message['message']['chat']
        chat_id = str(chat['id'])
        from_id = chat_id
        return (chat_id, from_id)

    def getUpdates(self):
        self.logger.info("listener: sending request with offset " +
                         str(self.update_offset) + "...")
        req = None

        # try to check for incoming messages. wait config.telegram['retry']sek and repeat on failure
        try:
            if self.update_offset == 0 and self.first_contact:
                res = ["0", "0"]
                while len(res) > 0:
                    req = requests.get(self.main.bot_url + "/getUpdates", params={
                                       'offset': self.update_offset, 'timeout': 0}, allow_redirects=False, timeout=10)
                    json = req.json()
                    if not json['ok']:
                        # self.set_status(gettext("Response didn't include 'ok:true'. Waiting before trying again. Response was: %(response)s", json))
                        self.logger.debug(
                            "Response didn't include 'ok:true'. Waiting before trying again. Response was: %(response)s", json)
                        time.sleep(config.telegram['retry'])
                        raise ExitThisLoopException()
                    if len(json['result']) > 0 and 'update_id' in json['result'][0]:
                        self.set_update_offset(json['result'][0]['update_id'])
                    res = json['result']
                    if len(res) < 1:
                        self.logger.debug(
                            "Ignoring message because first_contact is True.")
                if self.update_offset == 0:
                    self.set_update_offset(0)
            else:
                req = requests.get(self.main.bot_url + "/getUpdates", params={
                                   'offset': self.update_offset, 'timeout': 30}, allow_redirects=False, timeout=40)
        except requests.exceptions.Timeout:
            # Just start the next loop.
            raise ExitThisLoopException()
        except Exception as ex:
            # self.set_status(gettext("Got an exception while trying to connect to telegram API: %(exception)s. Waiting before trying again.", exception=ex))
            self.logger.debug(
                "Got an exception while trying to connect to telegram API: %(exception)s. Waiting  before trying again.", exception=ex)
            time.sleep(config.telegram['retry'])
            raise ExitThisLoopException()
        if req.status_code != 200:
            # self.set_status(gettext("Telegram API responded with code %(status_code)s. Waiting before trying again.", status_code=req.status_code))
            self.logger.debug(
                "Telegram API responded with code %(status_code)s. Waiting before trying again.", status_code=req.status_code)
            time.sleep(config.telegram['retry'])
            raise ExitThisLoopException()
        if req.headers['content-type'] != 'application/json':
            # self.set_status(gettext("Unexpected Content-Type. Expected: application/json. Was: %(type)s. Waiting before trying again.", type=req.headers['content-type']))
            self.logger.debug(
                "Unexpected Content-Type. Expected: application/json. Was: %(type)s. Waiting before trying again.", type=req.headers['content-type'])
            time.sleep(config.telegram['retry'])
            raise ExitThisLoopException()
        json = req.json()
        if not json['ok']:
            # self.set_status(gettext("Response didn't include 'ok:true'. Waiting before trying again. Response was: %(response)s", json))
            self.logger.debug(
                "Response didn't include 'ok:true'. Waiting before trying again. Response was: %(response)s", json)
            time.sleep(config.telegram['retry'])
            raise ExitThisLoopException()
        if "result" in json and len(json['result']) > 0:
            for entry in json['result']:
                self.set_update_offset(entry['update_id'])
        return json

    def stop(self):
        self.do_stop = True

    def test_token(self):
        response = requests.get(self.main.bot_url+"/getMe")
        self.logger.info("getMe returned: " + str(response.json()))
        self.logger.info("getMe status code: " + str(response.status_code))
        json = response.json()
        if not 'ok' in json or not json['ok']:
            if json['description']:
                raise(Exception(str("Telegram returned error code %(error)s: %(message)s",
                                    error=json['error_code'], message=json['description'])))
            else:
                raise(Exception(str("Telegram returned an unspecified error.")))
        else:
            return "@" + json['result']['username']


class StrichlisteWatcher(threading.Thread):
    def __init__(self, main):
        threading.Thread.__init__(self)
        self.main = main
        self.logger = logging.getLogger(self.__class__.__name__)
        self.do_stop = False
        self.latestUserList = None
        self.cachedUserList = None

    def run(self):
        self.logger.info("StrichlisteWatcher is running")
        try:
            while not self.do_stop:
                try:
                    self.loop()
                except ExitThisLoopException:
                    # do nothing, just go to the next loop
                    pass
        except Exception as ex:
            self.logger.exception(
                "An Exception crashed the Transaction checker : " + str(ex))

        self.logger.info("StrichlisteWatcher exits NOW.")

    def loop(self):
        try:
            req = requests.get(config.strichliste['apiurl'] + "/user")
            self.latestUserList = req.json()
            # Check for changes
            if not self.cachedUserList == None:
                self.logger.debug("Check UserList for changes...")
                ids = self.getUserIdsWithChanges()

                for id in ids:
                    since = self.cachedUserList.get(id)
                    self.processLastTransactions(id, since)

            # No LastUserList or invalid List = no changes. Save list.
            else:
                self.logger.info(
                    "First run. Cache only UserList.")

            self.updateCachedUserList()

        except Exception as ex:
            self.logger.exception("Exception caught in loop! " + str(ex) +
                                  " Traceback: " + traceback.format_exc())

        time.sleep(config.strichliste['interval'])

    def stop(self):
        self.do_stop = True

    def updateCachedUserList(self):
        if not self.latestUserList['users']:
            self.logger.error("Some problem with latestUserList")
        else:
            self.cachedUserList = {}
            for user in self.latestUserList["users"]:
                self.cachedUserList[user["id"]] = user["updated"]

    def processLastTransactions(self, userid, since):
        self.logger.info("Process Transactions for user %d since %s" %
                         (userid, since))

        req = requests.get(config.strichliste['apiurl'] +
                           "/user/%d/transaction" % userid)
        jsonUserTransactions = req.json()

        if jsonUserTransactions["transactions"]:
            for transaction in jsonUserTransactions["transactions"]:
                try:
                    dtcreated = self.parseTime(transaction["created"])
                    dtupdated = self.parseTime(since)
                except Exception as ex:
                    self.logger.exception("Error parsing time. Ignoring transaction! " + str(ex) +
                                          " Traceback: " + traceback.format_exc())
                    break

                if dtcreated > dtupdated:

                    if not transaction['recipient'] and not transaction['sender'] and not transaction['article']:
                        transactType = TransactionType.RECHARGE
                    elif not transaction['recipient'] and not transaction['sender'] and transaction['article']:
                        transactType = TransactionType.BUY_ARTICLE
                    elif not transaction['recipient'] and transaction['sender'] and not transaction['article']:
                        transactType = TransactionType.RECEIVE_MONEY
                    elif transaction['recipient'] and not transaction['sender'] and not transaction['article']:
                        transactType = TransactionType.SEND_MONEY

                    self.logger.info(
                        "Process Transaction %s (%s) from %s", str(transactType), str(transaction['id']), str(transaction['created']))

                    chatid = self.main.isAuthorizedUser(
                        strichliste_user_id=transaction['user']['id'])
                    if chatid:

                        if transactType == TransactionType.RECHARGE:

                            message = str("<b>"+u'\U0001f4b5'+" You recharge your account!</b>\n\n"
                                          "Ammount: <b>%.2lf€</b>\n"
                                          "New balance: <b>%.2lf€</b>" % (transaction['amount']/100,
                                                                          transaction['user']['balance'] / 100
                                                                          ))
                            self.main.send_msg(
                                message, markup="HTML", chatID=chatid)

                        elif transactType == TransactionType.BUY_ARTICLE:
                            message = str("<b>"+u'\U0001f4b5'+" You have purchased an item!</b>\n\n"
                                          "Ammount: <b>%.2lf€</b>\n"
                                          "Item: <b>%s</b>\n"
                                          "New balance: <b>%.2lf€</b>" % (
                                                transaction['article']['amount']/100,
                                                html.escape(
                                                    transaction['article']['name']),
                                                transaction['user']['balance']/100
                                          )
                                          )
                            self.main.send_msg(
                                message, markup="HTML", chatID=chatid)
                        elif transactType == TransactionType.SEND_MONEY:
                            message = str(
                                "<b>"+u'\U0001f4b5'+" You sent money!</b>\n\n"
                                "Recipient: <b>%s</b>\n"
                                "Ammount: <b>%.2lf€</b>\n"
                                "Note: <b>%s</b>\n"
                                "New balance: <b>%.2lf€</b>\n" % (html.escape(transaction['recipient']['name']),
                                                                  transaction['amount'] / 100,
                                                                  ("---" if transaction['comment'] == None or transaction['comment'] == "" else html.escape(
                                                                      transaction['comment'])),
                                                                  transaction['user']['balance']/100
                                                                  ))
                            self.main.send_msg(
                                message, markup="HTML", chatID=chatid)

                        if transactType == TransactionType.RECEIVE_MONEY:

                            message = str("<b>"+u'\U0001f4b5'+" You recived money!</b>\n\n"
                                          "Sender: <b>%s</b>\n"
                                          "Ammount: <b>%.2lf€</b>\n"
                                          "Note: <b>%s</b>\n"
                                          "New balance: <b>%.2lf€</b>\n" % (html.escape(transaction['sender']['name']),
                                                                            transaction['amount'] / 100,
                                                                            ("---" if transaction['comment'] == None or transaction['comment'] == "" else html.escape(
                                                                                transaction['comment'])),
                                                                            transaction['user']['balance']/100
                                                                            ))
                            self.main.send_msg(
                                message, markup="HTML", chatID=chatid)
                    elif not chatid and transactType == TransactionType.SEND_MONEY:
                        comment = transaction['comment'].strip()

                        match = re.search(
                            r"^([a-zA-Z0-9]{%d})$" % config.strichliste['activation_token_len'], comment)
                        if match:
                            token = match.group(1)
                            self.logger.info(
                                "Transaction has valid token '%s'", token)
                            if self.main.pendingActivations != None:
                                request = self.main.pendingActivations.get(
                                    token)
                                if request:
                                    # remove from pending requests
                                    del self.main.pendingActivations[token]
                                    if time.time() - request['time'] <= 120:
                                        self.main.addAuthorizedUsers(
                                            transaction['user']['id'], request['chatid'])
                                        self.main.send_msg(
                                            "Hello %s, you are now getting here transaction notifications for your Strichliste account." % html.escape(
                                                transaction['user']['name']), chatID=request['chatid'], markup="HTML")
                                    else:
                                        self.logger.error(
                                            "Pending request timed out")
                                else:
                                    self.logger.error(
                                        "No pending request with this token")
                            else:
                                self.logger.error(
                                    "No pending request with this token")
                    else:
                        self.logger.info(
                            "User %s not registerd for telegram messages", str(transaction['user']['id']))

    def getUserIdsWithChanges(self):
        userIdsWithChanges = []
        if not self.latestUserList['users']:
            self.logger.error("Some problem with latestUserList")
        else:
            for user in self.latestUserList["users"]:
                self.logger.debug("Check User %d" % user["id"])
                if not self.cachedUserList.get(user["id"]) == None:
                    if user['updated'] != self.cachedUserList.get(user["id"]):
                        self.logger.info(
                            "yes, user %d has changes! (UserList=%s, cachedUserList=%s)", user['id'], user['updated'], self.cachedUserList.get(user["id"]))
                        userIdsWithChanges.append(user["id"])
                        # userIdsWithChanges.append([user["id"], lastuserobj["updated"]])
                    else:
                        self.logger.debug("no, user %d has no changes!" %
                                          user['id'])
                else:
                    self.logger.debug(
                        "New User or User without transactions. Ignoring.")

        return userIdsWithChanges

    def parseTime(self, strtime):
        return datetime.strptime(
            strtime, '%Y-%m-%d %H:%M:%S')  # 2019-07-20 19:24:41


class StrichlisteTelegramBridge():

    def __init__(self):
        print("StrichlisteTelegramBride started.")
        self.threadStrichlisteWatcher = None
        self.threadTelegramListener = None
        self.sl_json_user = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.pendingActivations = {}
        self.authorizedUsers = {}
        self.authorizedUsersFile = scriptdir + "/" + config.authorizedUsersFile

        # load Authorized user list
        self.loadAuthorizedUsers()

    # start StrichlisteWatcher
    def start_StrichlisteWatcher(self):
        if self.threadStrichlisteWatcher is None:
            self.logger.info("Starting StrichlisteWatcher.")
            self.threadStrichlisteWatcher = StrichlisteWatcher(self)
            self.threadStrichlisteWatcher.start()

    def stop_StrichlisteWatcher(self):
        if self.threadStrichlisteWatcher is not None:
            self.logger.info("Stopping StrichlisteWatcher.")
            self.threadStrichlisteWatcher.stop()
            self.threadStrichlisteWatcher = None

    # starts the telegram listener thread
    def start_TelegramListener(self):
        if config.telegram['bottoken'] != "" and config.telegram['apiurl'] != "":
            if self.threadTelegramListener is None:
                self.logger.info("Starting TelegramListener.")
                self.bot_url = config.telegram['apiurl'] + \
                    config.telegram['bottoken']
                self.threadTelegramListener = TelegramListener(self)
                self.threadTelegramListener.start()
        else:
            self.logger.error("Telegram API-Url or Bottoken not set.")

    # stops the telegram listener thread
    def stop_listening(self):
        if self.threadTelegramListener is not None:
            self.logger.info("Stopping TelegramListener.")
            self.threadTelegramListener.stop()
            self.threadTelegramListener = None

    def send_msg(self, message="", responses=None, inline=True, chatID="", markup=None, showWeb=False, **kwargs):
        if chatID == "":
            self.logger.exception("Can't send message chatID is empty!")
        try:

            self.logger.info(
                "Sending a message: " + message.replace("\n", "\\n") + " chatID=" + str(chatID))
            data = {}
            # Do we want to show web link previews?
            data['disable_web_page_preview'] = not showWeb
            # Do we want the message to be parsed in any markup?
            if markup is not None:
                if "HTML" in markup or "Markdown" in markup:
                    data["parse_mode"] = markup
            if responses:
                myArr = []
                for k in responses:
                    myArr.append(
                        map(lambda x: {"text": x[0], "callback_data": x[1]}, k))
                keyboard = {'inline_keyboard': myArr}
                data['reply_markup'] = json.dumps(keyboard)

            self.logger.debug("data so far: " + str(data))

            r = None
            data['chat_id'] = chatID

            data['text'] = message
            r = requests.post(self.bot_url + "/sendMessage", data=data)
            if r.status_code != 200:
                self.logger.warning(
                    "Sending finished, but with status code %s.", str(r.status_code))
            else:
                self.logger.debug("Sending finished. " + str(r.status_code))

        except Exception as ex:
            self.logger.exception(
                "Caught an exception in send_msg(): " + str(ex))

    def randomStringDigits(self, stringLength=8):
        lettersAndDigits = string.ascii_letters + string.digits
        return ''.join(random.choice(lettersAndDigits) for i in range(stringLength))

    def saveAuthorizedUsers(self):
        if config.authorizedUsersFile == "":
            self.logger.error("authorizedUsersFile is not set!")
            return

        try:
            with open(self.authorizedUsersFile, 'w') as f:
                json.dump(self.authorizedUsers, f)

            self.logger.info("authorizedUsersFile successful saved")

        except Exception as ex:
            self.logger.exception(
                "Caught an exception in saveAuthorizedUsers(): %s", ex)

    def loadAuthorizedUsers(self):
        if config.authorizedUsersFile == "":
            self.logger.error("authorizedUsersFile is not set!")
            return

        try:
            with open(self.authorizedUsersFile, 'r') as f:
                self.authorizedUsers = json.load(f)

            self.logger.info("authorizedUsersFile successful loaded")

        except Exception as ex:
            self.logger.exception(
                "Caught an exception in loadAuthorizedUsers(): %s", ex)

    def addAuthorizedUsers(self, sl_id, telegram_chat_id):
        self.logger.info(
            "Adding Strichliste UserID '%s' with Telegram ChatID '%s' to authorized user list.", str(sl_id), str(telegram_chat_id))
        old_sl_id = self.isAuthorizedUser(telegram_chat_id=telegram_chat_id)
        if old_sl_id:
            self.deleteAuthorizedUsers(old_sl_id)
        self.authorizedUsers[str(sl_id)] = dict(
            chatid=telegram_chat_id, updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.saveAuthorizedUsers()

    def deleteAuthorizedUsers(self, sl_id):
        self.logger.info(
            "Deleting Strichliste UserID '%s' from uthorized user list.", str(sl_id))
        del self.authorizedUsers[str(sl_id)]
        self.saveAuthorizedUsers()

    def isAuthorizedUser(self, strichliste_user_id=None, telegram_chat_id=None, **kwargs):
        if strichliste_user_id != None:
            if self.authorizedUsers.get(str(strichliste_user_id)):
                return self.authorizedUsers.get(str(strichliste_user_id))['chatid']
            else:
                return False
        elif telegram_chat_id != None:
            for sl_id, authorizedUser in self.authorizedUsers.items():
                if authorizedUser['chatid'] == telegram_chat_id:
                    return sl_id
            return False
        else:
            raise(Exception(
                str("You must set the attributes strichliste_user_id or telegram_chat_id")))

    def getUserInfo(self, userid):
        req = requests.get(config.strichliste['apiurl'] +
                           "/user/%s" % str(userid))
        return req.json()


def main():
    # Setup Logger
    logging.basicConfig(level=config.logginglevel,
                        format='%(asctime)s %(funcName)s@%(name)s (%(threadName)s): %(message)s')

    strichliste = StrichlisteTelegramBridge()
    strichliste.start_StrichlisteWatcher()
    strichliste.start_TelegramListener()


if __name__ == '__main__':
    main()
