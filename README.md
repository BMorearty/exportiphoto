exportiphoto
============

Exports an iPhoto library to a folder structure, optionally writing
metadata to the copies.

This script has been tested with iPhoto 8.1.2 (from iLife '09); other versions
may or may not work.

Originally written by Derrick Childers and 
[posted to macosxhints](http://www.macosxhints.com/article.php?story=20081108132735425).
Modifications by Guillaume Boudreau, 
[Brian Morearty](http://github.com/BMorearty),
[Mark Nottingham](http://github.com/mnot),
[Duoglas Du](http://github.com/duoglas), and
[Avinash Meetoo](http://github.com/avinash)

Usage
-----

1. Run this:
        python exportiphoto.py [options] <iPhoto Library dir> <destination dir>
   Options include:
        -a, --albums    use albums instead of events
        -m, --metadata  write metadata to images
        -f, --faces     store faces as keywords (requires -m)
        -q, --quiet     use quiet mode
        -d, --date      stop using date prefix in folder name
2. There is no step 2

note that the -m flag is only available if extra libraries are installed; 
see below.

if you are facing encoding problems like "UnicodeEncodeError", try -q flag to stop the console output;

Output
------

By default, exportiphoto exports Events.  It can export Albums instead; use
the -a option on the command line.

It creates a separate folder on disk for each event.  Every folder is prefixed
by the event date in this format: yyyy-mm-dd (because this format is sortable by name)
unless you use the -d option.  
If the event has a name it is appended to the end of the folder name.

Example
-------

Let's say you have the following events in iPhoto--two unnamed and one named:

    Jun 10, 2009
    Charlie's Birthday Party
    Jun 20, 2009

Run:

    python exportiphoto.py ~/Pictures/iPhoto\ Library/ ~/iPhoto\ Export

If Charlie's birthday party was on June 15th, the output folders will be:

    2009-06-10
    2009-06-15 Charlie's Birthday Party
    2009-06-20

If you set the -d option to turn off the prepended date, the folder names will be:

    Jun 10, 2009
    Charlie's Birthday Party
    Jun 20, 2009

Writing Metadata
----------------

If pyexiv2 is installed, exportiphoto can write iPhoto metadata into 
images as they're exported, with the -m option. Currently, it writes:

 - iPhoto image name to Iptc.Application2.Headline
 - iPhoto description to Iptc.Application2.Caption
 - iPhoto keywords to Iptc.Application2.Keywords
 - iPhoto rating to Xmp.xmp.Rating

See below for information on installing pyexiv2.

NOTE: if you see messages like this:

    Error: Directory Canon with 1100 entries considered invalid; not read.
    
you can safely ignore them; they indicate a problem reading the metadata
already in the file. Installing a newer version of pyexiv2 should fix this
(as of this writing, it's fixed in the repository, but not released).

Installing pyexiv2
------------------

Unfortunately, there is no easy way to install pyexiv2, but if you have
MacPorts <http://macports.org/>, it's relatively simple; follow these steps
to set up:

    > sudo port install scons
    > sudo port install exiv2
    > sudo port install boost +python26
    
Then, after downloading Pyexiv2 <http://tilloy.net/dev/pyexiv2/> and changing 
into its source directory:
        
    > export CXXFLAGS="-I/opt/local/include"
    > export LDFLAGS="-L/opt/local/lib -lpython2.6"
    > sudo scons install
    > cd /opt/local/Library/Frameworks/Python.framework/Versions/2.6/lib/python2.6/site-packages/
    > sudo mv libexiv2python.dylib libexiv2python.so
    
Note that you'll have to use python2.6 to run the script; e.g.,

    > python2.6 exportiphoto ...
    
