import urllib.request
import json
import os.path
from datetime import datetime
from urllib.parse import urlencode

#Settings
config_tempdir = "tmp/"
config_lastjson = "lastjson.json"
config_userlist = "users.json"
config_baseurl = "http://strichliste.fritz.box/api"
config_verbose = False
config_bottoken = "952263958:AAEPUnAnGNZQcQnKJt0qAjX3dy82grYHQhU"
config_tg_apiurl = "https://api.telegram.org/bot"

scriptpath = os.path.dirname(os.path.realpath(__file__))
lastjsonfile = scriptpath+"/"+config_tempdir+config_lastjson
userjsonfile = scriptpath+"/"+config_userlist
telegramapi = config_tg_apiurl+config_bottoken

def getUserIdsWithChanges(newjson):
    userIdsWithChanges = []
    if(os.path.isfile(lastjsonfile)):
        with open(lastjsonfile, 'r') as f:
            lastjson = json.load(f)

        for user in newjson["users"]:
            if config_verbose: print("Check User " + str(user["id"]))
            lastuserobj = getUserObjectFromJson(lastjson, user["id"])
            if(lastuserobj != -1):
                if user["updated"] != lastuserobj["updated"]:
                    if config_verbose: print("yes changes!")
                    userIdsWithChanges.append([user["id"], lastuserobj["updated"]])
                else:
                    if config_verbose: print("no changes")
            else:
                if config_verbose: print("New user or user not found")
            
    else:
        # config_tempfile not exists
        #print("file not exisits")
        with open(lastjsonfile, 'w') as f:  # writing JSON object
            json.dump(newjson, f)
    
    return userIdsWithChanges

def getUserObjectFromJson(json, id):
    for user in json["users"]:
        if user["id"] == id:
            return user
    return -1

def getChatId(id):
    with open(userjsonfile, 'r') as f:
        users = json.load(f)

    for user in users["users"]:
        if user["id"] == id:
            return user["chat_id"]
    return ""

def getLastTransactions(userid, updated):
    print("Get Transaction for userid " + str(userid) + " since " + updated)
    urlData = config_baseurl + "/user/" + str(userid) + "/transaction"
    jsonData = getResponse(urlData)
    for transaction in jsonData["transactions"]:
        #transaction["created"]
        dtcreated = datetime.strptime(transaction["created"], '%Y-%m-%d %H:%M:%S') #2019-07-20 19:24:41
        dtupdated = datetime.strptime(updated, '%Y-%m-%d %H:%M:%S') #2019-07-20 19:24:41
        if dtcreated >= dtupdated:
            #print(transaction)
            if transaction['article']:
                chatid = getChatId(userid)
                if chatid != "":
                    print("Found valid chatid:" + str(chatid))
                    message = str("<b>New Transaction!</b>\n"
                        "Ammount: %.2lf€\n"
                        "Product: %s\n"
                        "New balance: %.2lf€"  % (
                            transaction['article']['amount']/100, 
                            transaction['article']['name'],
                            transaction['user']['balance']/100
                        )
                    )
                    sendMessage(chatid, message)
            else:
                print("No article")
    
def sendMessage(chatid, message):
    data = { 'chat_id' : chatid, 'text' : message, 'parse_mode' : 'HTML'}
    url = telegramapi+"/sendMessage?"+urlencode(data)
    print(url)
    operUrl = urllib.request.urlopen(url)
    if(operUrl.getcode()==200):
        print("Message send")
    else:
        print("Error send message", operUrl.getcode())


def getResponse(url):
    operUrl = urllib.request.urlopen(url)
    if(operUrl.getcode()==200):
        data = operUrl.read()
        jsonData = json.loads(data)
    else:
        print("Error receiving data", operUrl.getcode())
    return jsonData

def main():

    urlData = config_baseurl + "/user"
    jsonData = getResponse(urlData)
    userIdsWithChanges = getUserIdsWithChanges(jsonData)
    print(userIdsWithChanges)
    for id in userIdsWithChanges:
        getLastTransactions(id[0], id[1])

    #save last state
    #with open(lastjsonfile, 'w') as f:
    #    json.dump(jsonData, f)


if __name__ == '__main__':
    main()