image-deduplication-tool: simple tool to detect (and get rid of) similar images using perceptual hashing
--------------------

There's gonna be a lot of duplicates in almost any arbitrary collection of
images, and it can actually be surprising how many.

pHash lib, which is the core of the tool, easily detects cropped and retouched
images, or same thing in different resolutions and formats.

Tool goes over the specified paths, calculating the hashes of all the images
there, pickling them into a db file between runs (to save lots of time on
re-calculating all of them).
Then it just compares the hashes, showing closest results first.

pHash lib seem to be able to utilize multiple cpu cores for the hashing when
built with with openmp flag, but it didn't seem to work for me, so put much
simplier solution in place to scale such task - just forking worker pid for each
hardware thread.

Optinally, tool can start handy [feh](http://derf.homelinux.org/projects/feh/)
viewer, where human can make a decision to remove one image version or the other
(with pre-configured "rm" action) for each duplicate pair, skip to the next pair
or stop the comparison.


Warning
--------------------

As illustrated in
[#1](https://github.com/mk-fg/image-deduplication-tool/issues/1) and
[CImg#49](https://sourceforge.net/p/cimg/bugs/49/), libpHash/CImg will fall back
to using potentially unsafe (exploitable with crafted pathnames) "sh -c"
commands for non-image file formats and might not get filename-escaping
correctly there (especially with CImg versions up to 1.5.3).

Simple safeguard for that particular issue would be only to run the tool on
image paths (where CImg doesn't run "sh"), not paths that contain mixed-type
files, or at least make sure there's no funky stuff in the filenames, script
doesn't enforce any kind of policy there.

Note also that thing libpHash/CImg runs (usually) is ImageMagick's "convert",
which can have all sort of issues with malicious file contents (see e.g.
[ImageTragick](imagetragick.com) bug there), so maybe it's not a good idea to
run the tool on a bunch of unsanitized images, ever.

One other precaution is that with the --feh option, script will run "feh"
program, and --feh-args parameter may contain options (e.g. --info) that will be
executed in the shell by feh, so either don't use --feh for weird and/or
possibly-malicious (e.g. really weird) filenames or at least remove --info
option from the --feh-args commandline.


Requirements
--------------------

* [Python 2.7](http://python.org) (with ctypes support)
* [libpHash](http://phash.org) (used via ctypes)
* (optional) [feh image viewer](http://derf.homelinux.org/projects/feh/)


Usage
--------------------

Just run as e.g. `./image_matcher.py --feh ~/media/images`.

	% ./image_matcher.py -h

	usage: image_matcher.py [-h] [--hash-db PATH] [-d [PATH]] [-p THREADS]
	                        [-n COUNT] [--feh] [--feh-args CMDLINE] [--debug]
	                        paths [paths ...]

	positional arguments:
	  paths                 Paths to match images in (can be files or dirs).

	optional arguments:
	  -h, --help            show this help message and exit
	  --hash-db PATH        Path to db to store hashes in (default:
	                        ./image_matcher.db).
	  -d [PATH], --reported-db [PATH]
	                        Record already-displayed pairs in a specified file and
	                        dont show these again. Can be specified without
	                        parameter to use "reported.db" file in the current dir.
	  -p THREADS, --parallel THREADS
	                        How many hashing ops can be done in parallel (default:
	                        try cpu_count() or 1).
	  -n COUNT, --top-n COUNT
	                        Limit output to N most similar results (default: print
	                        all).
	  --feh                 Run feh for each image match with removal actions
	                        defined (see --feh-args).
	  --feh-args CMDLINE    Feh commandline parameters (space-separated, unless
	                        quoted with ") before two image paths (default: -GNFY
	                        --info "echo '%f %wx%h (diff: {diff}, {diff_n} /
	                        {diff_count})'" --action8 "rm %f" --action1 "kill -INT
	                        {pid}", only used with --feh, python-format keywords
	                        available: path1, path2, n, pid, diff, diff_n,
	                        diff_count)
	  --debug               Verbose operation mode.

feh can be customized to do any action or show any kind of info alongside images
with --feh-args parameter. It's also possible to make it show images
side-by-side in montage mode or in separate windows in multiwindow mode, see
"man feh" for details.

Default feh command line:

	feh -GNFY --info "echo '%f %wx%h (diff: {diff}, {diff_n} / {diff_count})'" --action8 "rm %f" --action1 "kill -INT {pid}" {path1} {path2}

makes it show fullscreen image, some basic info (along with difference between
image hashes and how much images there are with the same level of difference)
about it and action reference, pressing "8" there will remove currently
displayed version, "1" will stop the comparison and quitting feh ("q") will go
to the next pair.

Without --feh (non-interactive / non-gui mode), script outputs pairs of images
and the integer [Hamming distance](https://en.wikipedia.org/wiki/Hamming_distance)
value for their perceptual hash values (basically the degree of difference
between the two).

Output is sorted by this "distance", so most similar images (with the lowest
number) should come first (see --top-n parameter).

Optional --reported-db (or "-d") parameter allows efficient skipping of
already-reported "similar" image pairs by recording these in a dbm file.
Intended usage for this option is to skip repeating same hash-similar pairs on
repeated runs, reporting similarity for new images instead.


Operation
--------------------

Script does these steps, in order:

* Try to load pre-calculated image hash values from --hash-db file.

* Calculate missing perceptual hash values (ph_dct_imagehash) for each image
  found, possibly in multiple subprocesses.

* Dump (pickle) produced hash values (back) to a --hash-db file.

* Calculate the difference between hashes of each image pair for all two-image
  combinations, sorting the results.

* Print (or run "feh" on) each found image-pair, in most-similar-first order,
  optionally skipping pairs matching those in --reported-db file.

It's fairly simple, with all the magic and awesomeness in calculation of that
"perceptual hash" values, which is contained in [libpHash](http://phash.org).


Known Issues
--------------------

pHash seem to be prone to hanging indefinitely on some non-image files without
consuming much resources. Use `./image_matcher.py --debug -p 1` to see on which
exact file it hangs on in such cases.
Might add some check for file magic to see if it's image before running pHash
over it in the future.

pHash also gives zero as a hash value for some images. No idea why it does that
atm, but these "0" values obviously can't be meaningfully compared to anything,
so tool skips them, issuing a log message (seen only with --debug).
