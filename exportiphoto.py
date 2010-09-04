#!/usr/bin/env python


__version__ = "0.5"

import datetime
import os
import re
import shutil
import stat
import sys

from optparse import OptionParser
from xml.dom.minidom import parse, Node

# FIXME: use SAX so we don't have to load XML all into memory

def main(albumDataXml, targetDir, copyImg=True, useEvents=True):
    print "Parsing..."
    try:
        albumDataDom = parse(albumDataXml)
    except IOError, why:
        return error("Can't parse Album Data: %s" % why[1])
    topMostDict = albumDataDom.documentElement.getElementsByTagName('dict')[0]
    if not topMostDict:
        return error("Album Data doesn't appear to be in the right format.")
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

        # Walk through all the images in this roll/event/album
        imageIdArray = getValue(folderDict, "KeyList")
        for imageIdElement in findChildren(imageIdArray, 'string'):
            imageId = getElementText(imageIdElement)
            imageDict = getValue(masterImageListDict, imageId)
            mFilePath = getElementText(getValue(imageDict, "ImagePath"))
#            oFilePath = getElementText(getValue(imageDict, "OriginalPath"))

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
                print "Creating directory: %s" % targetFileDir
                if copyImg:
                    try:
                        os.makedirs(targetFileDir)
                    except OSError, why:
                        error("Can't create directory: %s" % why[1])

            tFilePath = targetFileDir + "/" + basename

            # Skip unchanged files
            if os.path.exists(tFilePath):
                tStat = os.stat(tFilePath)
                if abs(tStat[stat.ST_MTIME] - mStat[stat.ST_MTIME]) <= 10 or \
                  tStat[stat.ST_SIZE] == mStat[stat.ST_SIZE]:
                    sys.stdout.write(".")
                    continue

            msg = "copying from:%s to:%s" % (mFilePath, tFilePath)
            if copyImg:
                print msg
                # TODO: try findertools.copy and macostools.copy
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
    if len(element.childNodes) == 0: 
        return None
    else: 
        return element.childNodes[0].nodeValue

def getValue(parent, keyName):
    for key in findChildren(parent, "key"):
        if getElementText(key) == keyName:
            sib = key.nextSibling
            while(sib is not None and sib.nodeType != Node.ELEMENT_NODE):
                sib = sib.nextSibling
            return sib
    error("Can't find %s in Album Data." % keyName)

APPLE_BASE = 978307200 # 2001/1/1
def getAppleTime(value):
    "Converts a numeric Apple time stamp into a date and time"
    return datetime.datetime.fromtimestamp(APPLE_BASE + float(value))

def error(msg):
    sys.stderr.write("ERROR: " + msg + "\n")
    sys.exit(1)


if __name__ == '__main__':
    usage   = """Usage: %prog [options] <AlbumData.xml> <destination dir>"""
    version = """exportiphoto version %s""" % __version__
    option_parser = OptionParser(usage=usage, version=version)
    option_parser.set_defaults(test=False, albums=False)

    option_parser.add_option("-t", "--test",
                             action="store_true", dest="test",
                             help="don't copy images; dry run"
    )

    option_parser.add_option("-a", "--albums",
                             action="store_true", dest="albums",
                             help="use albums instead of events"
    )

    (options, args) = option_parser.parse_args()
    
    if len(args) != 2:
        option_parser.error(
            "Please specify an iPhoto library and a destination."
        )

    main(args[0], args[1], not options.test, not options.albums)
    