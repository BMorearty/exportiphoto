#!/usr/bin/env python


__version__ = "0.6"

import base64
import codecs
import io
import locale
import os
import re
import shutil
import stat
import sys

import time
from datetime import datetime
from io import IOBase
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

# Some AlbumData.xml files contain null bytes.  Strip them so the SAX parser
# doesn't fail with an Invalid Token error.
class RemoveNullsStream(IOBase):
    def __init__(self, filename):
        self.file = open(filename, 'r')

    def read(self, bufsize=2**20):
        return self.file.read(bufsize).translate(None,"\0")

    def close(self):
        self.file.close()

class iPhotoLibrary(object):
    def __init__(self, albumDir, destDir, use_album=False, use_date=False,
                 use_faces=False, use_metadata=False, deconflict=False, quiet=False,
                 year_dir=False, import_missing=False, import_from_date=None, test=False,
                 date_delimiter="-", ignore_time_delta=False, originals=False):
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
        self.test = test
        self.year_dir = year_dir
        self.import_missing = import_missing
        self.ignore_time_delta = ignore_time_delta
        self.date_delimiter = date_delimiter
        self.originals=originals
        self.import_albums = []

        if import_from_date:
            self.import_from_date = datetime.strptime(import_from_date, "%Y-%m-%d")
        else:
            self.import_from_date = None

        if self.import_missing:
            self.build_import_list()

        albumDataXml = os.path.join(albumDir, "AlbumData.xml")
        albumDataStream = RemoveNullsStream(albumDataXml)
        self.status("* Parsing iPhoto Library data... ")
        self.parseAlbumData(albumDataStream)
        albumDataStream.close()
        self.status("Done.\n")

    major_version = 2
    minor_version = 0
    interesting_image_keys = [
        'OriginalPath', 'ImagePath', 'Rating', 'Keywords', 'Caption', 'Comment', 'Faces',
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

            #as we process albums/events in the iPhoto library, remove that album
            #from the list of import_albums we'll be importing at the end
            if self.import_albums:
                for ia in self.import_albums:
                    for album_name in ia['album_names']:
                        album_name = unicode(album_name, 'utf-8')
                        if folderName == album_name:
                            self.import_albums.remove(ia)

            if folderDate and self.use_date:
                date = '%(year)d%(delim)s%(month)02d%(delim)s%(day)02d' % {
                    'year': folderDate.year,
                    'month': folderDate.month,
                    'day': folderDate.day,
                    'delim': self.date_delimiter
                }
                if re.match("[A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4}", folderName):
                    outputPath = date
                elif re.match("[0-9]{4}.[0-9]{2}.[0-9]{2} ?.*", folderName):
                    outputPath = folderName
                else:
                    outputPath = date + " " + folderName
                if self.year_dir:
                    outputPath = os.path.join(str(folderDate.year), outputPath)
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

        if self.import_missing: 
            self.status("importing folders:\n")
            for ia in self.import_albums:
                self.status(ia["album_dir"] + "\n")

                #using the "Auto Import" dir in iPhoto was unpredictable with respect to the resulting event name.
                #Using AppleScript to import the event, seams to always result in the event being properly named
                if not self.test:
                    #There is probably a better way to do this. I noticed I had an album with an ' in it that errored...
                    escaped_dir = ia["album_dir"].replace("'", "\\'").replace('"', '\\"')
                    os.system('''osascript -e '
tell application "iPhoto"
    import from "%s"
end tell
' ''' % escaped_dir)

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
                if not self.test:
                    os.makedirs(folderName)
            except OSError, why:
                raise iPhotoLibraryError, \
                    "Can't create %s: %s" % (folderName, why[1])
            self.status("  Created %s\n" % folderName)

        #Unedited images only have ImagePath, edited images have both ImagePath and OriginalPath,
        #except for some corrupted iPhoto libraries, where some images only have OriginalPath.
        #Trying to satisfy both conditions with this nested logic.
        if self.originals:
            if "OriginalPath" in image:
                mFilePath = image["OriginalPath"]
            else:
                mFilePath = image["ImagePath"]
        else:
            if not "ImagePath" in image:
                mFilePath = image["OriginalPath"]
            else:
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

            if not self.ignore_time_delta and abs(tStat[stat.ST_MTIME] - mStat[stat.ST_MTIME]) <= 10:
                self.status("-")
                return

            if tStat[stat.ST_SIZE] == mStat[stat.ST_SIZE]:
                self.status("-")
                return

        if not self.test and os.path.exists(mFilePath):
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
            if self.originals:
                if "OriginalPath" in image:
                    mFilePath = image["OriginalPath"]
                else:
                    mFilePath = image["ImagePath"]
            else:
                if not "ImagePath" in image:
                    mFilePath = image["OriginalPath"]
                else:
                    mFilePath = image["ImagePath"]


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
                if not self.test:
                    md.write(preserve_timestamps=True)
                return True
            except IOError, why:
                self.status("\nProblem setting metadata (%s) on %s\n" % (
                    unicode(why.__str__(), errors='replace'), filePath
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

    def build_import_list(self):
        '''
        We are going to make some assumptions here.
        1. The dest_dir is a directory of albums containing images, optionally the albums can be in year dirs.
        2. Album dirs are assumed to follow one of these naming patterns:
           [0-9]{4}.[0-9]{2}.[0-9]{2} ?.*      -  Dated folder, unnamed, iPhoto album name could match or
                                                  could be iPhoto date format
           .*                                  -  Named folder, iPhoto album name

        Walk the dest dir and find all folders and files.  For each folder determine the possible iPhoto album names.
        When walking the xml eliminate any folder we find where one of the possible album names matches an
        existing album name.
        '''
        if self.year_dir:
            year_dir_list = os.listdir(self.dest_dir)
            for year_dir in year_dir_list:
                # if year_dir was specified, then only match on folders inside year folders
                if not re.match("^[0-9]{4}$", year_dir): continue

                # if import_from_date was specified, then skip folders where the year_dir is before the import_from_date.year
                if self.import_from_date and int(year_dir) < self.import_from_date.year: continue

                self.build_import_album_dirs(os.path.join(self.dest_dir, year_dir))
        else:
            self.build_import_album_dirs(self.dest_dir)

    def build_import_album_dirs(self, base_dir):
        delim = str(self.date_delimiter)
        for album_name in os.listdir(base_dir):
            album_names = [album_name]
            folder_date = None
            # Folder pattern: "2011_01_01 New Years Party"
            m = re.match(r"([0-9]{4}\%s[0-9]{2}\%s[0-9]{2}) ?(.*)" % (delim, delim), album_name)
            if m:
                folder_date = datetime.strptime(m.group(1), "%Y" + delim + "%m" + delim + "%d")
                album_names.append(m.group(2))

            # Folder pattern: "2011_01_01"
            m = re.match(r"^[0-9]{4}\%s[0-9]{2}\%s[0-9]{2}$" % (delim, delim), album_name)
            if m:
                folder_date = datetime.strptime(album_name, "%Y" + delim + "%m" + delim + "%d")
                month, day, year = folder_date.strftime("%b %d %Y").split(" ")
                album_names.append("%s %d, %s" %(month, int(day), year))

            # Don't import folders that are prior to the specified date
            if not folder_date: continue
            if self.import_from_date and folder_date < self.import_from_date: continue

            album_dir = os.path.abspath(os.path.join(base_dir, album_name))

            this_album = { "album_names": album_names, "album_dir":album_dir, }
            self.import_albums.append(this_album)

def error(msg):
    sys.stderr.write("\n%s\n" % msg)
    sys.exit(1)


if __name__ == '__main__':
    usage   = "Usage: %prog [options] <iPhoto Library dir> <destination dir>"
    version = "exportiphoto version %s" % __version__
    default_date_delimiter = "-"
    option_parser = OptionParser(usage=usage, version=version)
    option_parser.set_defaults(
        test=False,
        albums=False,
        metadata=False,
        faces=False,
        quiet=False,
        date=True,
        ignore_time_delta=False,
        originals=False
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
    
    option_parser.add_option("-o", "--originals",
                             action="store_true", dest="originals",
                             help="export original images instead of edited ones"
    )

    option_parser.add_option("-x", "--deconflict",
                             action="store_true", dest="deconflict",
                             help="deconflict export directories of same name"
    )

    option_parser.add_option("-t", "--test",
                             action="store_true", dest="test",
                             help="don't actually copy files or import folders"
    )

    option_parser.add_option("-y", "--yeardir",
                             action="store_true", dest="year_dir",
                             help="add year directory to output"
    )

    option_parser.add_option("-e", "--date_delimiter",
                             action="store", type="string", dest="date_delimiter",
                             help="date delimiter default=%s" % default_date_delimiter
    )

    option_parser.add_option("-i", "--import",
                             action="store_true", dest="import_missing",
                             help="import missing albums from dest directory"
    )

    option_parser.add_option("-j", "--ignore_time_delta",
                             action="store_true", dest="ignore_time_delta",
                             help="ignore time delta when determining whether or not to copy a file"
    )

    option_parser.add_option("-z", "--import_from_date",
                             action="store", type="string", dest="import_from_date",
                             help="only import missing folers if folder date occurs after (YYYY-MM-DD). Uses date in folder name."
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
        if options.date_delimiter is None:
            options.date_delimiter = default_date_delimiter
        
        library = iPhotoLibrary(args[0], # src
                                args[1], # dest
                                use_album=options.albums,
                                use_date=options.date,
                                use_faces=options.faces,
                                use_metadata=options.metadata,
                                deconflict=options.deconflict,
                                quiet=options.quiet,
                                year_dir=options.year_dir,
                                import_missing=options.import_missing,
                                import_from_date=options.import_from_date,
                                test=options.test,
                                date_delimiter=options.date_delimiter,
                                ignore_time_delta=options.ignore_time_delta,
                                originals=options.originals
                                )
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
