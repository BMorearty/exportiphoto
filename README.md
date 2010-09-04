exportiphoto
============

Exports an iPhoto library to a folder structure.

Originally written by Derrick Childers and 
[posted to macosxhints](http://www.macosxhints.com/article.php?story=20081108132735425).
Modifications by Guillaume Boudreau, 
[Brian Morearty](http://github.com/BMorearty), and
[Mark Nottingham](http://github.com/mnot).

Usage
-----

1. Run this:
        python exportiphoto.py [options] <AlbumData.xml> <destination dir>
   Options include:
        -t, --test       don't copy images; dry run
        -a, --albums     use albums instead of events
2. There is no step 2

Output
------

By default, exportiphoto exports Events.  It can also export Albums if you want.  (Use
the -a option on the command line).

It creates a separate folder on disk for each event.  Every folder is prefixed
by the event date in this format: yyyy-mm-dd (because this format is sortable by name).
If the event has a name it is appended to the end of the folder name.

Example
-------

Let's say you have the following events in iPhoto--two unnamed and one named:

    Jun 10, 2009
    Charlie's Birthday Party
    Jun 20, 2009

Run:

    python exportiphoto.py ~/Pictures/iPhoto\ Library/AlbumData.xml ~/Downloads/iPhoto\ Export

If Charlie's birthday party was on June 15th, the output folders will be:

    2009-06-10
    2009-06-15 Charlie's Birthday Party
    2009-06-20

If you set useDate to False in the code, the folder names will be:

    Jun 10, 2009
    Charlie's Birthday Party
    Jun 20, 2009
