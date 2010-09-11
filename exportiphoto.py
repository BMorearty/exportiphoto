#!/usr/bin/env python


__version__ = "0.6"

import datetime
import os
import re
import shutil
import stat
import sys

from optparse import OptionParser
from xml.dom.minidom import parse, Node

try:
    import pyexiv2
except ImportError:
    pyexiv2 = None

# FIXME: use SAX so we don't have to load XML all into memory

class iPhotoLibrary(object):
    def __init__(self, albumDir):
        print "Parsing..."
        albumDataXml = os.path.join(albumDir, "AlbumData.xml")
        try:
            self._albumDataDom = parse(albumDataXml)
        except IOError, why:
            return error("Can't parse Album Data: %s" % why[1])
        topDict = \
            self._albumDataDom.documentElement.getElementsByTagName('dict')[0]
        if not topDict:
            return error("Album Data doesn't appear to be in the right format.")
        self.RollList = self.getValue(topDict, "List of Rolls")
        self.AlbumList = self.getValue(topDict, "List of Albums")
        self.keywordDict = self.getValue(topDict, "List of Keywords")
        self.ImageDict = self.getValue(topDict, "Master Image List")
        self._keyword_cache = {}

    def __del__(self):
        self._albumDataDom.unlink()

    APPLE_BASE = 978307200 # 2001/1/1
    def walk(self, funcs, albums=False):
        """
        Walk through the events or albums (depending on the value of albums)
        in this library and apply each function in the list funcs to each 
        image, calling it as:
           func(folderName, folderDate, imageId)
        where:
         - folderName is the name the folder, 
         - folderDate is the date of the folder, and
         - imageId is the string identifier for the image.
        """
        if albums:
            targetList = self.AlbumList
            targetName = "AlbumName"
        else:
            targetList = self.RollList
            targetName = "RollName"
        for folderDict in self.findChildren(targetList, 'dict'):
            folderName = self.getText(self.getValue(folderDict, targetName))
            folderDate = datetime.datetime.fromtimestamp(
                       self.APPLE_BASE 
                       + float(self.getText(
                          self.getValue(folderDict, "RollDateAsTimerInterval")
                         ))
            )
            print "\n\nProcessing: %s" % (folderName)
            imageIds = self.getValue(folderDict, "KeyList")
            for image in self.findChildren(imageIds, 'string'):
                imageId = self.getText(image)
                for func in funcs:
                    func(imageId, folderName, folderDate)

    def copyImage(self, imageId, folderName, folderDate, 
                  targetDir, writeMD=False):
        """
        Copy an image from the library to a folder in the targetDir. The
        name of the folder is based on folderName and folderDate; if
        folderDate is None, it's only based upon the folderName.
        
        If writeMD is True, also write the image metadata from the library
        to the copy.
        """
        imageDict = self.getValue(self.ImageDict, imageId)

        if folderDate:
            date = '%(year)d-%(month)02d-%(day)02d' % {
                'year': folderDate.year,
                'month': folderDate.month,
                'day': folderDate.day
            }
            if re.match("[A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4}", folderName):
                outputPath = date
            else:
                outputPath = date + " " + folderName
        else:
            outputPath = folderName
        targetFileDir = targetDir + "/" + outputPath        

        if not os.path.exists(targetFileDir):
            print "Creating directory: %s" % targetFileDir
            try:
                os.makedirs(targetFileDir)
            except OSError, why:
                error("Can't create directory: %s" % why[1])

        mFilePath = self.getText(self.getValue(imageDict, "ImagePath"))
        basename = os.path.basename(mFilePath)
        tFilePath = targetFileDir + "/" + basename

        # Skip unchanged files, unless we're writing metadata.
        mStat = os.stat(mFilePath)
        if not writeMD and os.path.exists(tFilePath):
            tStat = os.stat(tFilePath)
            if abs(tStat[stat.ST_MTIME] - mStat[stat.ST_MTIME]) <= 10 or \
              tStat[stat.ST_SIZE] == mStat[stat.ST_SIZE]:
                sys.stdout.write(".")
                return

        print "copying from:%s to:%s" % (mFilePath, tFilePath)
        # TODO: try findertools.copy and macostools.copy
        shutil.copy2(mFilePath, tFilePath)
        if writeMD:
            self.writePhotoMD(imageId, tFilePath)

    def writePhotoMD(self, imageId, filePath=None):
        """
        Write the metadata from the library for imageId to filePath.
        If filePath is None, write it to the photo in the library.
        """
        imageDict = self.getValue(self.ImageDict, imageId)
        if not filePath:
            filePath = self.getText(getValue(imageDict, "ImagePath"))
        
        caption = self.getText(self.getValue(imageDict, "Caption"), "")
        rating = int(self.getText(
            self.getValue(imageDict, "Rating"), "0")
        )
        comment = self.getText(self.getValue(imageDict, "Comment"), "")
        kwids = self.getTextList(self.getValue(imageDict, "Keywords"))
        keywords = [self.lookupKeyword(i) for i in kwids]

        if caption or comment or rating:
            print "writing metadata..."
            md = pyexiv2.ImageMetadata(filePath)
            md.read()
            md["Iptc.Application2.Headline"] = [caption]
            md["Xmp.xmp.Rating"] = rating
            md["Iptc.Application2.Caption"] = [comment]
            md["Iptc.Application2.Keywords"] = keywords
            md.write(preserve_timestamps=True)

    ### Support methods.

    @staticmethod
    def findChildren(parent, name):
        result = []
        for child in parent.childNodes:
            if child.nodeName == name:
                result.append(child)
        return result

    @staticmethod
    def getText(element, default=None):
        if element is None: return default
        if len(element.childNodes) == 0: 
            return None
        else: 
            return element.childNodes[0].nodeValue

    def getTextList(self, element):
        if element.nodeName != "array":
            error("Expected 'array', got %s" % element.nodeName)
        return [self.getText(c) for c in element.childNodes 
                if c.nodeType == Node.ELEMENT_NODE]

    def getValue(self, parent, keyName, default=None):
        for key in self.findChildren(parent, "key"):
            if self.getText(key) == keyName:
                sib = key.nextSibling
                while(sib is not None and sib.nodeType != Node.ELEMENT_NODE):
                    sib = sib.nextSibling
                return sib
        return default

    def lookupKeyword(self, keywordId):
        if self._keyword_cache.has_key(keywordId):
            return _keyword_cache[keywordId]
        keyword = self.getText(
            self.getValue(self.keywordDict, keywordId), "-"
        )
        self._keyword_cache[keywordId] = keyword
        return keyword

            
def error(msg):
    sys.stderr.write("ERROR: " + msg + "\n")
    sys.exit(1)


if __name__ == '__main__':
    usage   = "Usage: %prog [options] <iPhoto Library dir> <destination dir>"
    version = "exportiphoto version %s" % __version__
    option_parser = OptionParser(usage=usage, version=version)
    option_parser.set_defaults(test=False, albums=False, metadata=False)

    option_parser.add_option("-a", "--albums",
                             action="store_true", dest="albums",
                             help="use albums instead of events"
    )

    if pyexiv2:
        option_parser.add_option("-m", "--metadata",
                                 action="store_true", dest="metadata",
                                 help="write metadata to images"
        )

    (options, args) = option_parser.parse_args()
    
    if len(args) != 2:
        option_parser.error(
            "Please specify an iPhoto library and a destination."
        )

    try:
        library = iPhotoLibrary(args[0])
        def copyImage(imageId, folderName, folderDate):
            library.copyImage(imageId, folderName, folderDate, 
                  sys.argv[2], options.metadata)
        library.walk([copyImage], options.albums)
    except KeyboardInterrupt:
        error("Interrupted by user. Copy may be incomplete.")