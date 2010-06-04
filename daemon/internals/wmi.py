# -*- coding: utf-8 -*-
"""
Licorn Daemon WMI internals.
WMI = Web Management Interface.

Copyright (C) 2007-2009 Olivier Cortès <olive@deep-ocean.net>
Licensed under the terms of the GNU GPL version 2.
"""

import os, mimetypes, urlparse, posixpath, urllib, socket, time

from SocketServer       import TCPServer
from BaseHTTPServer	    import BaseHTTPRequestHandler

from licorn.foundations import logging, exceptions, styles, process
from licorn.core        import configuration
from licorn.daemon.core import dname, wpid_path, wmi_port

def eventually_fork_wmi_server(start_wmi = True) :

	# FIXME : implement start_wmi in argparser module.

	if not configuration.daemon.wmi.enabled or not start_wmi :
		return

	try: 
		if os.fork() == 0 :
			# FIXME: drop_privileges() → become setuid('licorn:licorn')

			open(wpid_path,'w').write("%s\n" % os.getpid())
			process.set_name('%s/wmi' % dname)
			logging.progress("%s/wmi: starting (pid %d)." % (dname, os.getpid()))
			count = 0
			while True :
				count += 1
				try :
					httpd = TCPServer(('127.0.0.1', wmi_port), WMIHTTPRequestHandler)
					break
				except socket.error, e :
					if e[0] == 98 :
						logging.warning("%s/wmi: socket already in use. waiting (total: %dsec)." % (dname, count))
						time.sleep(1)
					else :
						logging.error("%s/wmi: socket error %s." % (dname, e))
						return
			httpd.serve_forever()
	except OSError, e: 
		logging.error("%s/wmi: fork failed: errno %d (%s)." % (dname, e.errno, e.strerror))
	except KeyboardInterrupt :
		logging.warning('%s/wmi: terminating on interrupt signal.' % dname)
		raise SystemExit

class WMIHTTPRequestHandler(BaseHTTPRequestHandler) :
	def do_HEAD(self) :
		f = self.send_head()
		if f :
			f.close()
	def do_GET(self) :
		f = self.send_head()
		if f :
			if type(f) in (type(""), type(u'')) :
				self.wfile.write(f)
			else :
				buf = f.read(_buffer_size)
				while buf :
					self.wfile.write(buf)
					buf = f.read(_buffer_size)
				f.close()
	def do_POST(self) :
		""" Handle POST data and create a dict to be used later."""

		# TODO: protect ourselves against POST flood : if (too_much_data) : send_header('BAD BAD') and stop()
		
		post_data = self.rfile.read(int(self.headers.getheader('content-length')))

		post_data = post_data.split('&')
		self.post_args = {}
		for var in post_data :
			if var not in ('', '=') :
				try :
					key, value = var.split('=')
				except ValueError :
					key = var
					value = ''

				if value != '' :
					value = urllib.unquote_plus(value)

				if self.post_args.has_key(key) :
					if type(self.post_args[key]) == type('') :
						self.post_args[key] = [ self.post_args[key], value ]
					else :
						self.post_args[key].append(value)
				else :
					self.post_args[key] = value
			
		#print '%s' % self.post_args

		self.do_GET()
	def send_head(self) :
		"""Common code for HEAD/GET/POST commands.

		This sends the response code and MIME headers.

		Return value is either a file object (which has to be copied
		to the outputfile by the caller unless the command was HEAD,
		and must be closed by the caller under all circumstances), or
		None, in which case the caller has nothing further to do.

		"""

		#logging.progress('serving HTTP Request: %s.' % self.path)
		
		retdata = None

		if self.user_authorized() :
			try :
				retdata = self.serve_virtual_uri()
			except exceptions.LicornWebException :
				retdata = self.serve_local_file()
		else :
			# return the 401 HTTP error code
			self.send_response(401, 'Unauthorized.')	
			self.send_header('WWW-authenticate', 'Basic realm="Licorn Web Management Interface"')
			retdata = ''

		self.end_headers()
		return retdata
	def user_authorized(self) :
		""" Return True if authorization exists AND user is authorized."""

		authorization = self.headers.getheader("authorization")
		if authorization :
			authorization = authorization.split()
			if len(authorization) == 2:
				if authorization[0].lower() == "basic":
					import base64, binascii
					try:
						authorization = base64.decodestring(authorization[1])
					except binascii.Error:
						pass
					else:
						authorization = authorization.split(':')
						if len(authorization) == 2 :
							#
							# TODO: make this a beautiful PAM authentication ?
							#
							if users.user_exists(login = authorization[0]) and users.check_password(authorization[0], authorization[1]) :
								if groups.group_exists(_wmi_group) :
									if authorization[0] in groups.auxilliary_members(_wmi_group) :
										return True
								else :
									return True
		return False
	def format_post_args(self) :
		""" Prepare POST data for exec statement."""

		# TODO: verify there is no other injection problem than the '"' !!

		postargs = []
		for key, val in self.post_args.items() :
			if type(val) == type('') :
				postargs.append('%s = "%s"' % (key,val.replace('"', '\"')))
			else :
				postargs.append('%s = %s' % (key, val))

		return postargs
	def serve_virtual_uri(self) :
		""" Serve dynamic URIs with our own code, and create pages on the fly. """

		retdata = None
		rettype = 'text'

		import licorn.interfaces.web as web

		if self.path == '/' :
			retdata = web.base.index(self.path)

		else :
			# remove the last '/' (useless for us, even it if is semantic for a dir/)
			if self.path[-1] == '/' :
				self.path = self.path[:-1]
			# remove the first '/' before splitting (it is senseless here).
			args = self.path[1:].split('/')

			if len(args) == 1 :
				args.append('main')
			elif args[1] == 'list' :
				args[1] = 'main'

			if args[0] in dir(web) :
				logging.progress("Serving %s %s." % (self.path, args))

				if hasattr(self, 'post_args') :
					py_code = 'retdata = web.%s.%s("%s" %s %s)' % (args[0], args[1], self.path,
						', "%s",' % '","'.join(args[2:]) if len(args)>2 else ', ',
						', '.join(self.format_post_args()) )
				else :
					py_code = 'retdata = web.%s.%s("%s" %s)' % (args[0], args[1], self.path, 
						', "%s",' % '","'.join(args[2:]) if len(args)>2 else '')

				try :
					#print "Exec'ing %s." % py_code
					exec py_code

				except (AttributeError, NameError), e :
					# this warning is needed as long as send_head() will produce a 404 for ANY error.
					# when it will able to distinguish between bad requests and real 404, this warning
					# will disapear.
					logging.warning("Exec: %s." % e)
					self.send_error(500, "Internal server error or bad request.")
			else :
				# not a web.* module
				raise exceptions.LicornWebException('Bad base request (probably a regular file request).')
						
		if retdata :
			self.send_response(200)

			if rettype == 'img' :
				self.send_header("Content-type", 'image/png')
			else :
				self.send_header("Content-type", 'text/html; charset=utf-8')
				self.send_header("Pragma", "no-cache")

			self.send_header("Content-Length", len(retdata))

		return retdata
	def serve_local_file(self) :
		""" Serve a local file (image, css, js...) if it exists. """

		retdata = None

		path = self.translate_path(self.path)

		if os.path.exists(path) :
			#logging.progress('serving file: %s.' % path)

			ctype = self.guess_type(path)

			if ctype.startswith('text/') :
				mode = 'r'
			else :
				mode = 'rb'

			try :
				retdata = open(path, mode)

			except (IOError, OSError), e :
				if e.errno == 13 :
					self.send_error(403, "Forbidden.")
				else :
					self.send_error(500, "Internal server error")

		else :
			self.send_error(404, "Not found.")

		if retdata :
			self.send_response(200)
			self.send_header("Content-type", ctype)

			fs = os.fstat(retdata.fileno())
			self.send_header("Content-Length", str(fs[6]))
			self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))

		return retdata
	def guess_type(self, path) :
		"""Guess the type of a file.

		Argument is a PATH (a filename).

		Return value is a string of the form type/subtype,
		usable for a MIME Content-type header.

		The default implementation looks the file's extension
		up in the table self.extensions_map, using application/octet-stream
		as a default; however it would be permissible (if
		slow) to look inside the data to make a better guess.
		"""
		base, ext = posixpath.splitext(path)
		if ext in self.extensions_map:
			return self.extensions_map[ext]
		ext = ext.lower()
		if ext in self.extensions_map:
			return self.extensions_map[ext]
		else:
			return self.extensions_map['']
	def translate_path(self, path) :
		"""Translate a /-separated PATH to the local filename syntax.

		Components that mean special things to the local file system
		(e.g. drive or directory names) are ignored.
		XXX They should probably be diagnosed.

		"""
		# abandon query parameters
		path = urlparse.urlparse(path)[2]
		path = posixpath.normpath(urllib.unquote(path))
		words = path.split('/')
		words = filter(None, words)
		if os.getenv('LICORN_DEVEL') :
			path = os.getcwd()
		else :
			path = '/usr/share/licorn/webadmin'
		for word in words :
			drive, word = os.path.splitdrive(word)
			head, word = os.path.split(word)
			if word in (os.curdir, os.pardir): continue
			path = os.path.join(path, word)
		return path

	#
	# TODO: implement and override BaseHTTPRequestHandler.log_{request,error,message}(), to
	# put logs into logfiles, like apache2 does ({access,error}.log). See
	# /usr/lib/python2.5/BaseHTTPServer.py for details.
	#

	#
	# Static code follows.
	#
	if not mimetypes.inited:
		mimetypes.init() # try to read system mime.types
	extensions_map = mimetypes.types_map.copy()
	extensions_map.update({
		'': 'application/octet-stream', # Default
        })