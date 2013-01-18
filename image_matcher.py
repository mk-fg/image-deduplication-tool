#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function


import itertools as it, operator as op, functools as ft
import os, sys, ctypes, errno, pickle, select, signal, struct


class pHash(object):

	def __init__(self):
		self._lib = ctypes.CDLL('libpHash.so.0', use_errno=True)

	def dct_imagehash_async(self, path):
		r, w = os.pipe()
		pid = os.fork()
		if not pid:
			with os.fdopen(w, 'wb') as dst:
				pickle.dump(self.dct_imagehash(path), dst)
			os._exit(0) # so "finally" clauses won't get triggered
		else:
			os.close(w)
			return r, pid

	def dct_imagehash(self, path):
		phash = ctypes.c_uint64()
		if self._lib.ph_dct_imagehash(path, ctypes.pointer(phash)):
			errno_ = ctypes.get_errno()
			err, err_msg = (errno.errorcode[errno_], os.strerror(errno_))\
				if not errno else ('none', 'errno was set to 0')
			print(( 'Failed to get image hash'
				' ({!r}): [{}] {}' ).format(path, err, err_msg), file=sys.stderr)
			return None
		return phash.value

	def hamming_distance(self, hash1, hash2):
		return self._lib.ph_hamming_distance(
			*map(ctypes.c_uint64, [hash1, hash2]) )


def update_dcts(dcts, paths, threads=False):
	dcts_nx, dcts_pool = set(dcts), dict()
	paths = ( os.path.join(root, path)
			for root, dirs, files in it.chain.from_iterable(
				it.imap(os.walk, paths) )
			for path in files )
	try:
		for path in paths:
			dcts_nx.discard(path)
			if path in dcts: continue
			log.debug('Processing path: {}'.format(path))
			if not threads: dcts[path] = phash.dct_imagehash(path)
			else:
				r, pid = phash.dct_imagehash_async(path)
				dcts_pool[r] = path, pid
				while len(dcts_pool) >= threads:
					pipes, _, _ = select.select(dcts_pool.keys(), [], [])
					for r in pipes:
						path, pid = dcts_pool.pop(r)
						dcts[path] = pickle.load(os.fdopen(r, 'rb'))
						os.waitpid(pid, 0)
		for r, (path, pid) in dcts_pool.viewitems():
			dcts[path] = pickle.load(os.fdopen(r, 'rb'))
			os.waitpid(pid, 0)
	finally:
		for _, pid in dcts_pool.viewvalues():
			try: os.kill(pid, signal.SIGTERM)
			except: pass
	for path in dcts_nx: del dcts[path]


def sort_by_similarity(dcts):
	import heapq
	dcts_sorted, paths_skipped = list(), set()
	log.debug('Calculating/sorting Hamming distances')
	for img1, img2 in it.combinations(dcts.viewitems(), 2):
		for path, h in img1, img2:
			if h == 0 or h is None:
				if path not in paths_skipped:
					log.debug('Skipping no-hash path: {}'.format(path))
					paths_skipped.add(path)
				break
		else:
			(path1, hash1), (path2, hash2) = img1, img2
			d = phash.hamming_distance(hash1, hash2)
			if d == 0: yield (d, path1, path2) # can't be lower than that
			else: heapq.heappush(dcts_sorted, (d, path1, path2))
	for i in xrange(len(dcts_sorted)): yield heapq.heappop(dcts_sorted)


def main():
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument('paths', nargs='+',
		help='Paths to match images in (can be files or dirs).')
	parser.add_argument('--hash-db', metavar='PATH',
		default='{}.db'.format(os.path.splitext(sys.argv[0])[0]),
		help='Path to db to store hashes in (default: %(default)s).')
	parser.add_argument('-d', '--reported-db',
		nargs='?', metavar='PATH', default=False,
		help='Record already-displayed pairs in'
				' a specified file and dont show these again.'
			' Can be specified without parameter to use "reported.db" file in the current dir.')
	parser.add_argument('-p', '--parallel', type=int, metavar='THREADS',
		help='How many hashing ops'
			' can be done in parallel (default: try cpu_count() or 1).')
	parser.add_argument('-n', '--top-n', type=int, metavar='COUNT',
		help='Limit output to N most similar results (default: print all).')
	parser.add_argument('--feh', action='store_true',
		help='Run feh for each image match with'
			' removal actions defined (see --feh-args).')
	parser.add_argument('--feh-args', metavar='CMDLINE',
		default=( '-GNFY --info "echo \'%f %wx%h'
			' (diff: {diff}, {diff_n} / {diff_count})\'"'
			' --action8 "rm %f" --action1 "kill -INT {pid}"' ),
		help='Feh commandline parameters (space-separated,'
			' unless quoted with ") before two image paths (default: %(default)s,'
			' only used with --feh, python-format keywords available:'
			' path1, path2, n, pid, diff, diff_n, diff_count)')
	parser.add_argument('--debug',
		action='store_true', help='Verbose operation mode.')
	optz = parser.parse_args()

	if optz.feh:
		def quote_split(arg_line):
			argz = arg_line.split('"', 2)
			if len(argz) == 2: parser.error('feh-cmd: unmatched quotes')
			elif len(argz) == 1: return argz[0].split()
			elif len(argz) == 3: argz = argz[:-1] + quote_split(argz[-1])
			return argz[0].split() + argz[1:]
		optz.feh_args = quote_split(optz.feh_args)
	if optz.parallel is None:
		try:
			import multiprocessing
			optz.parallel = multiprocessing.cpu_count()
		except (ImportError, NotImplementedError): optz.parallel = 1
	elif optz.parallel <= 0: parser.error('parallel: must be >0')

	from subprocess import Popen, PIPE
	import logging

	global log
	logging.basicConfig( level=logging.DEBUG\
		if optz.debug else logging.WARNING )
	log = logging.getLogger()

	global phash # no point in re-initializing it every time
	phash = pHash()

	try:
		try: dcts = pickle.load(open(optz.hash_db, 'rb'))
		except (OSError, IOError): dcts = dict()
		else: log.debug('Loaded hashes for {} paths'.format(len(dcts)))

		try:
			update_dcts( dcts, optz.paths,
				threads=optz.parallel if optz.parallel > 1 else False )
		finally: pickle.dump(dcts, open(optz.hash_db, 'wb'))

		if optz.reported_db is not False:
			import shelve
			optz.reported_db = shelve.open(optz.reported_db or 'reported.db', 'c')
			log.debug('Cleaning up reported_db of non-existent paths')
			for paths_key in optz.reported_db.keys():
				path1, path2 = paths_key.split('\0')
				if not all(it.imap(os.path.exists, [path1, path2])):
					del optz.reported_db[paths_key]
		else: optz.reported_db = None

		if optz.top_n != 0:
			n, pid = 0, os.getpid()
			for d, diff_tier in it.groupby(sort_by_similarity(dcts), key=op.itemgetter(0)):
				diff_tier = list(diff_tier)
				diff_count = len(diff_tier)
				for diff_n, (d, path1, path2) in enumerate(diff_tier):
					n += 1
					if optz.reported_db is not None:
						paths_key = '{}\0{}'.format(*sorted([path1, path2]))
						if paths_key in optz.reported_db:
							log.debug('Skipped path-pair due to reported_db: {} {}'.format(path1, path2))
							continue
					print(path1, path2, d)
					if optz.feh and all(it.imap(os.path.exists, [path1, path2])):
						cmd = ['feh'] + list(
							arg.format( path1=path1, path2=path2, pid=pid,
								diff=d, n=n+1, diff_n=diff_n+1, diff_count=diff_count )
							for arg in optz.feh_args ) + [path1, path2]
						log.debug('Feh command: {}'.format(cmd))
						Popen(cmd).wait()
					if optz.reported_db is not None\
							and all(it.imap(os.path.exists, [path1, path2])):
						optz.reported_db[paths_key] = True
					if optz.top_n is not None and n >= optz.top_n: break
	except KeyboardInterrupt: sys.exit(0)
	finally:
		if optz.reported_db: optz.reported_db.sync()


if __name__ == '__main__': main()
