#!/usr/bin/env python


__version__ = "0.6"

import base64
import codecs
import locale
import os
import re
import shutil
import stat
import sys

from datetime import datetime
from optparse import OptionParser
from xml.dom.pulldom import START_ELEMENT, END_ELEMENT, parse
from xml.dom.minidom import Node

try:
    import pyexiv2
except ImportError:
    pyexiv2 = None

# To allow Unicode characters to be displayed
# (see http://wiki.python.org/moin/PrintFails)
sys.stdout = codecs.getwriter(locale.getpreferredencoding())(sys.stdout)
sys.stderr = codecs.getwriter(locale.getpreferredencoding())(sys.stderr)

class iPhotoLibraryError(Exception):
    pass

class iPhotoLibrary(object):
    def __init__(self, albumDir, destDir, use_album=False, use_date=False,
                 use_faces=False, use_metadata=False, deconflict=False, quiet=False):
        self.use_album = use_album
        self.use_date =  use_date
        self.use_faces = use_faces
        self.use_metadata = use_metadata
        self.deconflict = deconflict
        self.dest_dir = destDir
        self.output_dirs = set()
        self.output_files = set()
        self.quiet = quiet
        self.albums = []
        self.keywords = {}
        self.faces = {}
        self.images = {}
        albumDataXml = os.path.join(albumDir, "AlbumData.xml")
        self.status("* Parsing iPhoto Library data... ")
        self.parseAlbumData(albumDataXml)
        self.status("Done.\n")

    major_version = 2
    minor_version = 0
    interesting_image_keys = [
        'ImagePath', 'Rating', 'Keywords', 'Caption', 'Comment', 'Faces',
        'face key'
    ]
    apple_epoch = 978307200

    def parseAlbumData(self, filename):
        """
        Parse an iPhoto AlbumData.xml file, keeping the interesting
        bits.
        """
        doc = parse(filename)
        stack = []
        last_top_key = None
        if self.use_album:
            album_list_key = "List of Albums"
        else:
            album_list_key = "List of Rolls"
        for event, node in doc:
            if event == START_ELEMENT:
                stack.append(node)
                level = len(stack)
                if level == 3:
                    if node.nodeName == 'key':
                        doc.expandNode(node)
                        last_top_key = self.getText(node)
                        stack.pop()
                    elif last_top_key == 'List of Keywords':
                        doc.expandNode(node)
                        self.keywords = self.dePlist(node)
                        stack.pop()
                    elif last_top_key == 'List of Faces':
                        doc.expandNode(node)
                        self.faces = dict([
                            (k, v['name']) for k,v in
                             self.dePlist(node, ['name']).items()
                        ])
                        stack.pop()
                    elif last_top_key == 'Major Version':
                        doc.expandNode(node)
                        major_version = self.dePlist(node)
                        stack.pop()
                        if major_version != self.major_version:
                            raise iPhotoLibraryError, \
                            "Sorry, I can't understand version %i iPhoto Libraries." % major_version
                    elif last_top_key == 'Minor Version':
                        doc.expandNode(node)
                        minor_version = self.dePlist(node)
                        stack.pop()
                        if minor_version > self.minor_version:
                            self.status(
                                "\nI don't recognise iPhoto libraries when the minor version is %i, but let's try anyway.\n" % minor_version,
                                force=True
                            )

                elif level == 4:
                    # process large items individually so we don't
                    # load them all into memory.
                    if last_top_key == album_list_key:
                        doc.expandNode(node)
                        self.albums.append(self.dePlist(node))
                        stack.pop()
                    elif last_top_key == 'Master Image List':
                        doc.expandNode(node)
                        if node.nodeName == 'key':
                            last_image_key = self.getText(node)
                        else:
                            self.images[last_image_key] = self.dePlist(
                                node, self.interesting_image_keys
                            )
                        stack.pop()
            elif event == END_ELEMENT:
                stack.pop()

    def dePlist(self, node, interesting_keys=None):
        """
        Given a DOM node, convert the plist (fragment) it refers to and
        return the corresponding Python data structure.

        If interesting_keys is a list, "dict" keys will be filtered so that
        only those nominated are returned (for ALL descendant dicts). Numeric
        keys aren't filtered.
        """
        ik = interesting_keys
        dtype = node.nodeName
        if dtype == 'string':
            return self.getText(node)
        elif dtype == 'integer':
            try:
                return int(self.getText(node))
            except ValueError:
                raise iPhotoLibraryError, \
                "Corrupted Library; unexpected value '%s' for integer" % \
                    self.getText(node)
        elif dtype == 'real':
            try:
                return float(self.getText(node))
            except ValueError:
                raise iPhotoLibraryError, \
                "Corrupted Library; unexpected value '%s' for real" % \
                    self.getText(node)
        elif dtype == 'array':
            return [self.dePlist(c, ik) for c in node.childNodes \
                    if c.nodeType == Node.ELEMENT_NODE]
        elif dtype == 'dict':
            d = {}
            last_key = None
            for c in node.childNodes:
                if c.nodeType != Node.ELEMENT_NODE:
                    continue
                # TODO: catch out-of-order keys/values
                if c.nodeName == 'key':
                    last_key = self.getText(c)
                else: # value
                    if interesting_keys: # check to see if we're interested
                        if last_key not in interesting_keys \
                          and not last_key.isdigit():
                            continue # nope.
                    d[intern(str(last_key))] = self.dePlist(c, ik)
            return d
        elif dtype == 'true':
            return True
        elif dtype == 'false':
            return False
        elif dtype == 'data':
            return base64.decodestring(self.getText(c))
        elif dtype == 'date':
            return self.appleDate(self.getText(c))
        else:
            raise Exception, "Don't know what a %s is." % dtype

    @staticmethod
    def getText(element, default=None):
        if element is None:
            return default
        if len(element.childNodes) == 0:
            return None
        else:
            return "".join([n.nodeValue for n in element.childNodes])

    def walk(self, funcs):
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
        if self.use_album:
            targetName = "AlbumName"
            albums = [a for a in self.albums if
                      a.get("Album Type", None) == "Regular"]
        else:
            targetName = "RollName"
            albums = self.albums
        i = 0
        for folder in albums:
            i += 1
            if self.use_album:
                folderDate = None
            else:
                folderDate = self.appleDate(folder["RollDateAsTimerInterval"])
            images = folder["KeyList"]

            folderName = folder[targetName]
            if folderDate and self.use_date:
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

            # Deconflict output directories
            targetFileDir = os.path.join(self.dest_dir, outputPath)
            if self.deconflict:
                j = 1
                while targetFileDir in self.output_dirs:
                    targetFileDir = os.path.join(self.dest_dir, outputPath + " %02d"%j)
                    j += 1
                self.output_dirs.add(targetFileDir)

            self.status("* Processing %i of %i: %s (%i images)...\n" % (
                i,
                len(albums),
                folderName,
                len(images)
            ))
            for imageId in images:
                for func in funcs:
                    func(imageId, targetFileDir, folderDate)
            self.status("\n")

    def copyImage(self, imageId, folderName, folderDate):
        """
        Copy an image from the library to a folder in the dest_dir. The
        name of the folder is based on folderName and folderDate; if
        folderDate is None, it's only based upon the folderName.

        If use_metadata is True, also write the image metadata from the library
        to the copy. If use_faces is True, faces will be saved as keywords.
        """
        try:
            image = self.images[imageId]
        except KeyError:
            raise iPhotoLibraryError, "Can't find image #%s" % imageId

        if not os.path.exists(folderName):
            try:
                os.makedirs(folderName)
            except OSError, why:
                raise iPhotoLibraryError, \
                    "Can't create %s: %s" % (folderName, why[1])
            self.status("  Created %s\n" % folderName)

        mFilePath = image["ImagePath"]
        basename = os.path.basename(mFilePath)

        # Deconflict ouput filenames
        tFilePath = os.path.join(folderName, basename)
        if self.deconflict:
            j = 1
            while tFilePath in self.output_files:
                tFilePath = os.path.join(folderName, "%02d_"%j + basename)
                j += 1
            self.output_files.add(tFilePath)

        # Skip unchanged files, unless we're writing metadata.
        if not self.use_metadata and os.path.exists(tFilePath):
            mStat = os.stat(mFilePath)
            tStat = os.stat(tFilePath)
            if abs(tStat[stat.ST_MTIME] - mStat[stat.ST_MTIME]) <= 10 or \
              tStat[stat.ST_SIZE] == mStat[stat.ST_SIZE]:
                self.status("-")
                return

        shutil.copy2(mFilePath, tFilePath)
        md_written = False
        if self.use_metadata:
            md_written = self.writePhotoMD(imageId, tFilePath)
        if md_written:
            self.status("+")
        else:
            self.status(".")

    def writePhotoMD(self, imageId, filePath=None):
        """
        Write the metadata from the library for imageId to filePath.
        If filePath is None, write it to the photo in the library.
        If use_faces is True, iPhoto face names will be written to
        keywords.
        """
        try:
            image = self.images[imageId]
        except KeyError:
            raise iPhotoLibraryError, "Can't find image #%s" % imageId
        if not filePath:
            filePath = image['ImagePath']

        caption = image.get("Caption", None)
        rating = image.get("Rating", None)
        comment = image.get("Comment", None)
        keywords = set([self.keywords[k] for k in image.get("Keywords", [])])
        if self.use_faces:
            keywords.update([self.faces[f['face key']]
                             for f in image.get("Faces", [])
                             if self.faces.has_key(f['face key'])]
            )

        if caption or comment or rating or keywords:
            try:
                md = pyexiv2.ImageMetadata(filePath)
                md.read()
                if caption:
                    md["Iptc.Application2.Headline"] = [caption]
                if rating:
                    md["Xmp.xmp.Rating"] = rating
                if comment:
                    md["Iptc.Application2.Caption"] = [comment]
                if keywords:
                    md["Iptc.Application2.Keywords"] = list(keywords)
                md.write(preserve_timestamps=True)
                return True
            except IOError, why:
                self.status("\nProblem setting metadata (%s) on %s\n" % (
                    why, filePath
                ))
        return False

    def appleDate(self, text):
        try:
            return datetime.utcfromtimestamp(self.apple_epoch + float(text))
        except (ValueError, TypeError):
            raise iPhotoLibraryError, \
            "Corrupted Library; unexpected value '%s' for date" % text

    def status(self, msg, force=False):
        if force or not self.quiet:
            sys.stdout.write(msg)
            sys.stdout.flush()

def error(msg):
    sys.stderr.write("\n%s\n" % msg)
    sys.exit(1)


if __name__ == '__main__':
    usage   = "Usage: %prog [options] <iPhoto Library dir> <destination dir>"
    version = "exportiphoto version %s" % __version__
    option_parser = OptionParser(usage=usage, version=version)
    option_parser.set_defaults(
        test=False,
        albums=False,
        metadata=False,
        faces=False,
        quiet=False,
        date=True
    )

    option_parser.add_option("-a", "--albums",
                             action="store_true", dest="albums",
                             help="use albums instead of events"
    )

    option_parser.add_option("-q", "--quiet",
                             action="store_true", dest="quiet",
                             help="use quiet mode"
    )

    option_parser.add_option("-d", "--date",
                             action="store_false", dest="date",
                             help="stop use date prefix in folder name"
    )

    option_parser.add_option("-x", "--deconflict",
                             action="store_true", dest="deconflict",
                             help="deconflict export directories of same name"
    )

    if pyexiv2:
        option_parser.add_option("-m", "--metadata",
                                 action="store_true", dest="metadata",
                                 help="write metadata to images"
        )

        option_parser.add_option("-f", "--faces",
                                 action="store_true", dest="faces",
                                 help="store faces as keywords (requires -m)"
        )

    (options, args) = option_parser.parse_args()

    if len(args) != 2:
        option_parser.error(
            "Please specify an iPhoto library and a destination."
        )

    try:
        library = iPhotoLibrary(args[0], # src
                                args[1], # dest
                                use_album=options.albums,
                                use_date=options.date,
                                use_faces=options.faces,
                                use_metadata=options.metadata,
                                deconflict=options.deconflict,
                                quiet=options.quiet)
        def copyImage(imageId, folderName, folderDate):
            library.copyImage(imageId, folderName, folderDate)
    except iPhotoLibraryError, why:
        error(why[0])
    except KeyboardInterrupt:
        error("Interrupted.")
    try:
        library.walk([copyImage])
    except iPhotoLibraryError, why:
        error(why[0])
    except KeyboardInterrupt:
        error("Interrupted. Copy may be incomplete.")
