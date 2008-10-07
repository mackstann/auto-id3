#!/usr/bin/env python

# Written by Nick Welch <mack@incise.org> in the years 2005(?)-2008.
# Author disclaims copyright.

import os, sys, re, shelve, subprocess, tempfile, shutil, bisect
from stat import *

re_decls = dict(
    track  = r'[abcdefg\d]\d+',
    artist = r'[^/]+',
    album  = r'[^/]+',
    song   = r'[^/]+',
    ext    = r'\.mp3',
)

re_match_formats = [
    # these are regular expressions with the added feature of :foo: being
    # replaced with the corresponding pattern above in re_decls.  hope you
    # didn't actually need colons in your filename patterns...

    # any item (such as album or track) not available in a pattern will simply
    # be unset on the files.

    # any other tags such as genre will be wiped out.

    # change this
    'music/:artist:/:album:/:artist: - :track: - :song::ext:',
    # other examples
    #'(?:old)?music/:artist:/:artist: - :song::ext:',
    #'newmusic/misc/none/:artist: - :track: - :song::ext:',
]

class FileChangeDB:
    def __init__(self, filename):
        self.db = shelve.open(filename)

    def update_file_hash(self, filename):
        self.db[filename] = self._calculate_file_hash(filename)

    def file_has_changed(self, filename):
        stored = self.db.get(filename, None)
        current = self._calculate_file_hash(filename)
        return stored != current

    def _calculate_file_hash(self, filename):
        filestat = os.stat(filename)
        fields = (
            filestat[ST_SIZE],
            filestat[ST_MTIME],
            filestat[ST_MODE],
        )
        return ' '.join([ "%d" for f in fields ]) % fields

TEMP_FILE_SUFFIX = '.id3tmp'

def update_tags(filename, tags):
    """
    update tags in file atomically, so that the file is either in its original
    state or in its new tagged state, but never any other inconsistent state.
    this function can be interrupted at any point and the worst that will
    happen is a stale temp file left in the same directory as the file.  (and
    that will only happen if the interpreter is terminated uncleanly)
    """

    try:
        tempf = tempfile.NamedTemporaryFile(
            prefix=filename+'.',
            suffix=TEMP_FILE_SUFFIX,
            dir=os.path.dirname(filename) # stay on same filesystem
        )
        shutil.copyfileobj(file(filename), tempf)
        shutil.copystat(filename, tempf.name)
        os.fsync(tempf.fileno())

        run_cmd_or_die('id3v2', '--delete-all', tempf.name)

        args = ['id3v2']
        for k, v in tags.items():
            args += [ '--'+k, v ]
        args += [tempf.name]
        run_cmd_or_die(*args)

        os.rename(tempf.name, filename)

    finally:
        try:
            tempf.close()
        except OSError:
            # we moved it, so it fails when trying to remove it
            pass

def run_cmd_or_die(*argv):
    if subprocess.call(argv, stdout=subprocess.PIPE):
        print >>sys.stderr, "died calling:", ' '.join(argv)
        raise SystemExit(1)

def absolutify_directories(dirs):
    ret = []
    for d in dirs:
        if not os.path.isdir(d):
            print >>sys.stderr, 'no such directory:', d
            raise SystemExit(1)
        ret.append(os.path.abspath(d))
    return ret

def all_files_in_dirs(dirs):
    proc = subprocess.Popen(['find'] + dirs + ['-type', 'f'],
            stdout=subprocess.PIPE)
    return [ line.rstrip('\r\n') for line in proc.stdout.readlines() ]

def get_tags_for_file(filename):
    for r in file_pattern_regexps:
        match = r.search(filename)
        if match:
            break
    else:
        print "couldn't match file:", filename
        raise SystemExit(1)

    matches = match.groupdict()
    return dict((
        (tagname, matches[tagname])
        for tagname in ('artist', 'album', 'track', 'song')
        if matches.get(tagname)
    ))

def progress_str(nfiles_done, nfiles, filename):
    numlen = len(str(nfiles))
    formatstr = "%"+str(numlen)+"d/%d"
    s = formatstr % (nfiles_done, nfiles)

    progress_percent = float(nfiles_done) / nfiles * 100
    position = max(int(round(progress_percent / 10)) - 1, 0)
    s += ' ['
    for i in range(10):
        s += '*' if i == position else '-'
    s += '] '
    s += '/'.join(filename.split('/')[-2:]).replace('.mp3', '')
    return s

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print >>sys.stderr, "usage:",  sys.argv[0], "DIRECTORY [ DIRECTORIES ]"
        raise SystemExit(1)

    for name, pattern in re_decls.items():
        for i, f in enumerate(re_match_formats):
            f = f.replace(':%s:' % name, '(?P<%s>%s)' % (name, pattern), 1)
            f = f.replace(':%s:' % name, '(?P=%s)' % (name))
            re_match_formats[i] = f

    file_pattern_regexps = map(re.compile, re_match_formats)

    dirs = absolutify_directories(sys.argv[1:])

    file_list = []

    for fn in all_files_in_dirs(dirs):
        if fn.endswith(TEMP_FILE_SUFFIX):
            print "deleting stale temp file: %s" % fn
            os.unlink(fn)
        elif re.match('.*%s$' % re_decls['ext'], fn):
            bisect.insort(file_list, fn)

    hash_db = FileChangeDB(os.path.expanduser('~/.mp3_md5_db'))

    for i, filename in enumerate(file_list):
        print progress_str(i+1, len(file_list), filename)
        if hash_db.file_has_changed(filename):
            tags = get_tags_for_file(filename)
            update_tags(filename, tags)
            hash_db.update_file_hash(filename)

