# Before running this script, set the following configuration variables:
albumDataXml="/Users/YOURUSERNAME/Pictures/iPhoto Library/AlbumData.xml"
targetDir="/Users/YOURUSERNAME/Downloads/iPhoto Export"
copyImg=True #set to false to run with out copying files or creating directories
useEvents=True #set to False to use Albums instead of Events

import datetime
import os
import re
import shutil
import stat
import sys
import time

from xml.dom.minidom import parse, parseString, Node


def main():
    print "Parsing AlbumData.xml"
    albumDataDom = parse(albumDataXml)
    topMostDict = albumDataDom.documentElement.getElementsByTagName('dict')[0]
    masterImageListDict = getValue(topMostDict, "Master Image List")

    if useEvents:
        targetLists = getValue(topMostDict, "List of Rolls")
        useDate = True
    else:
        targetLists = getValue(topMostDict, "List of Albums")
        useDate = False

    # walk through all the rolls (events) / albums
    for folderDict in findChildren(targetLists, 'dict'):
        if useEvents:
            folderName = getElementText(getValue(folderDict, "RollName"))
            print "\n\nProcessing Roll: %s" % (folderName)
        else:
            folderName = getElementText(getValue(folderDict, "AlbumName"))
            if folderName == 'Photos':
                continue
            print "\n\nProcessing Album: %s" % (folderName)

        if useDate:
            appleTime = getElementText(
                getValue(folderDict, "RollDateAsTimerInterval")
            )
            rollTime = getAppleTime(appleTime)
            date = '%(year)d-%(month)02d-%(day)02d' % {
                'year': rollTime.year,
                'month': rollTime.month,
                'day': rollTime.day
            }
        else:
            date = ''

        #walk through all the images in this roll/event/album
        imageIdArray = getValue(folderDict, "KeyList")
        for imageIdElement in findChildren(imageIdArray, 'string'):
            imageId = getElementText(imageIdElement)
            imageDict = getValue(masterImageListDict, imageId)
            mFilePath = getElementText(getValue(imageDict, "ImagePath"))
            oFilePath = getElementText(getValue(imageDict, "OriginalPath"))

            mStat = os.stat(mFilePath)
            basename = os.path.basename(mFilePath)
            if useDate and re.match(
                "[A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4}", folderName
            ):
                outputPath = date
            elif useDate:
                outputPath = date + " " + folderName
            else:
                outputPath = folderName
                
            targetFileDir = targetDir + "/" + outputPath        
            if not os.path.exists(targetFileDir):
                print "Directory did not exist - Creating: %s" % targetFileDir
                if copyImg:
                    os.makedirs(targetFileDir)

            tFilePath = targetFileDir + "/" + basename

            # skip unchanged files
            if os.path.exists(tFilePath):
                tStat = os.stat(tFilePath)
                if abs(tStat[stat.ST_MTIME] - mStat[stat.ST_MTIME]) <= 10 or \
                  tStat[stat.ST_SIZE] == mStat[stat.ST_SIZE]:
                    sys.stdout.write(".")
                    continue

            msg = "copy from:%s to:%s" % (mFilePath, tFilePath)
            if copyImg:
                print msg
                shutil.copy2(mFilePath, tFilePath)
            else:
                print "test - %s" % (msg)

    albumDataDom.unlink()


def findChildren(parent, name):
    result = []
    for child in parent.childNodes:
        if child.nodeName == name:
            result.append(child)
    return result

def getElementText(element):
    if element is None: return None
    if len(element.childNodes) == 0: return None
    else: return element.childNodes[0].nodeValue

def getValue(parent, keyName):
    for key in findChildren(parent, "key"):
        if getElementText(key) == keyName:
            sib = key.nextSibling
            while(sib is not None and sib.nodeType != Node.ELEMENT_NODE):
                sib = sib.nextSibling
            return sib

APPLE_BASE = 978307200 # 2001/1/1
def getAppleTime(value):
  '''Converts a numeric Apple time stamp into a date and time'''
  return datetime.datetime.fromtimestamp(APPLE_BASE + float(value))


if __name__ == '__main__':
    main()
    