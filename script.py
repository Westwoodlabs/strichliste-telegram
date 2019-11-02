from urllib.parse import urlencode
from datetime import datetime
import logging
import threading
import os.path
import time
import json
import urllib.request
import config
import traceback


# Docu
# https: // github.com/strichliste/strichliste-backend/blob/master/docs/API.md
# https: // www.python-kurs.eu/threads.php
# https: // mcuoneclipse.com/2019/04/01/log2ram-extending-sd-card-lifetime-for-raspberry-pi-lorawan-gateway/
# https: // github.com/fabianonline/OctoPrint-Telegram/blob/stable/octoprint_telegram/__init__.py
# https: // www.thomaschristlieb.de/ein-python-script-mit-systemd-als-daemon-systemd-tut-garnicht-weh/


class ExitThisLoopException(Exception):
    pass


class TransactionChecker(threading.Thread):
    def __init__(self, main):
        threading.Thread.__init__(self)
        self.main = main
        self.logger = logging.getLogger(self.__class__.__name__)
        self.do_stop = False
        self.latestUserList = None
        self.cachedUserList = None

    def run(self):
        self.logger.info("TransactionChecker is running")
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

        self.logger.info("TransactionChecker exits NOW.")

    def loop(self):
        try:
            urlData = config.strichliste['apiurl'] + "/user"
            self.latestUserList = self.main.getResponse(urlData)

            # Check for changes
            if not self.cachedUserList == None:
                self.logger.info("Check UserList for changes...")
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

        time.sleep(1)

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
        self.logger.info("Process Transaction for user %d since %s" %
                         (userid, since))

        urlData = config.strichliste['apiurl'] + \
            "/user/%d/transaction" % userid
        jsonUserTransactions = self.main.getResponse(urlData)

        if jsonUserTransactions["transactions"]:
            for transaction in jsonUserTransactions["transactions"]:
                try:
                    dtcreated = self.main.parseTime(transaction["created"])
                    dtupdated = self.main.parseTime(since)
                except Exception as ex:
                    self.logger.exception("Error parsing time. Ignoring transaction! " + str(ex) +
                                          " Traceback: " + traceback.format_exc())
                    break

                if dtcreated >= dtupdated:
                    if transaction['article']:
                        # chatid = getChatId(userid)
                        # if chatid != "":
                        # print("Found valid chatid:" + str(chatid))
                        message = str("<b>New Transaction!</b>\n"
                                      "Ammount: %.2lf€\n"
                                      "Product: %s\n"
                                      "New balance: %.2lf€" % (
                                          transaction['article']['amount']/100,
                                          transaction['article']['name'],
                                          transaction['user']['balance']/100
                                      )
                                      )
                        print(message)
                        # sendMessage(chatid, message)
                    else:
                        self.logger.error("No article")

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
                            "yes, user %d has changes!" % user['id'])
                        userIdsWithChanges.append(user["id"])
                        # userIdsWithChanges.append([user["id"], lastuserobj["updated"]])
                    else:
                        self.logger.debug("no, user %d has no changes!" %
                                          user['id'])
                else:
                    self.logger.debug(
                        "New User or User without transactions. Ignoring.")

        return userIdsWithChanges

# def getChatId(id):
#     with open(userjsonfile, 'r') as f:
#         users = json.load(f)

#     for user in users["users"]:
#         if user["id"] == id:
#             return user["chat_id"]
#     return ""

# def sendMessage(chatid, message):
#     data = {'chat_id': chatid, 'text': message, 'parse_mode': 'HTML'}
#     url = telegramapi+"/sendMessage?"+urlencode(data)
#     print(url)
#     operUrl = urllib.request.urlopen(url)
#     if(operUrl.getcode() == 200):
#         print("Message send")
#     else:
#         print("Error send message", operUrl.getcode())


class StrichlisteTelegramBridge():

    def __init__(self):
        print("StrichlisteTelegramBride started.")
        self.thread = None
        self.sl_json_user = None
        self.logger = logging.getLogger(self.__class__.__name__)
        # self.scriptpath = os.path.dirname(os.path.realpath(__file__))
        # self.userjsonfile = scriptpath+"/"+config_userlist
        # self.telegramapi = config_tg_apiurl + config_bottoken

    def start_TransactionChecker(self):
        if self.thread is None:
            self.logger.info("Starting listener.")
            self.thread = TransactionChecker(self)
            # self.thread.daemon = True
            self.thread.start()

    def stop_TransactionChecker(self):
        if self.thread is not None:

            self.logger.info("Stopping listener.")
            self.thread.stop()
            self.thread = None

    def getResponse(self, url):
        operUrl = urllib.request.urlopen(url)
        if (operUrl.getcode() == 200):
            self.logger.debug("getResponse HTTP Code: %d " % operUrl.getcode())
            data = operUrl.read()
            jsonData = json.loads(data)
        else:
            self.logger.error("Error receiving data:  %d " % operUrl.getcode())
        return jsonData

    def parseTime(self, strtime):
        return datetime.strptime(
            strtime, '%Y-%m-%d %H:%M:%S')  # 2019-07-20 19:24:41


def main():
    # Setup Logger
    logging.basicConfig(level=config.logginglevel,
                        format='%(asctime)s %(funcName)s@%(name)s (%(threadName)s): %(message)s')

    strichliste = StrichlisteTelegramBridge()
    strichliste.start_TransactionChecker()

    # userIdsWithChanges = getUserIdsWithChanges(jsonData)
    # print(userIdsWithChanges)
    # for id in userIdsWithChanges:
    #    getLastTransactions(id[0], id[1])
    # save last state
    # with open(lastjsonfile, 'w') as f:
    #    json.dump(jsonData, f)


if __name__ == '__main__':
    main()
