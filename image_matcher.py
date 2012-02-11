#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function


import itertools as it, operator as op, functools as ft
import os, sys, ctypes, pickle, select, signal, struct


class pHash(object):

	def __init__(self):
		self._lib = ctypes.CDLL('libpHash.so.0', use_errno=True)

	def dct_imagehash_async(self, path):
		r, w = os.pipe()
		pid = os.fork()
		if not pid:
			pickle.dump(self.dct_imagehash(path), os.fdopen(w, 'wb'))
			os._exit(0) # so "finally" clauses won't get triggered
		else:
			os.close(w)
			return r, pid

	def dct_imagehash(self, path):
		phash = ctypes.c_uint64()
		if self._lib.ph_dct_imagehash(path, ctypes.pointer(phash)):
			errno_ = ctypes.get_errno()
			raise OSError(errno_, os.strerror(errno_))
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
			if h == 0:
				if path not in paths_skipped:
					log.debug('Skipping 0-hash path: {}'.format(path))
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
	parser.add_argument('-p', '--parallel', type=int, metavar='THREADS',
		help='How many hashing ops'
			' can be done in parallel (default: try cpu_count() or 1).')
	parser.add_argument('-n', '--top-n', type=int, metavar='COUNT',
		help='Limit output to N most similar results (default: print all).')
	parser.add_argument('--feh', action='store_true',
		help='Run feh for each image match with'
			' removal actions defined (see --feh-args).')
	parser.add_argument('--feh-args', metavar='CMDLINE',
		default=( '-GNFY --info "echo \'%f %wx%h (diff: {diff})\'"'
			' --action8 "rm %f" --action1 "kill -INT {pid}"' ),
		help='Feh commandline parameters (space-separated,'
			' unless quoted with ") before two image paths (default: %(default)s,'
			' only used with --feh, python-format keywords available: path1, path2, pid, diff)')
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

		if optz.top_n != 0:
			for i, (d, path1, path2) in enumerate(sort_by_similarity(dcts)):
				print(path1, path2, d)
				if optz.feh:
					cmd = ['feh'] + list(arg.format( path1=path1, path2=path2,
						pid=os.getpid(), diff=d ) for arg in optz.feh_args) + [path1, path2]
					log.debug('Feh command: {}'.format(cmd))
					Popen(cmd).wait()
				if optz.top_n is not None and i >= optz.top_n: break
	except KeyboardInterrupt: sys.exit(0)


if __name__ == '__main__': main()
