# -*- coding: utf-8 -*-
"""
Licorn extensions: squid - http://docs.licorn.org/extensions/squid.html

:copyright: 2010 Robin Lucbernet <robinlucbernet@gmail.com>

:license: GNU GPL version 2

"""

import os, gconf

from licorn.foundations.pyutils   import add_or_dupe_enumeration
from licorn.foundations           import logging, exceptions, readers, process
from licorn.foundations.styles    import *
from licorn.foundations.base      import Singleton, Enumeration
from licorn.foundations.classes   import ConfigFile
from licorn.foundations.ltrace    import ltrace
from licorn.foundations.constants import licornd_roles, services, svccmds

from licorn.core                  import LMC
from licorn.extensions            import ServiceExtension

class SquidExtension(Singleton, ServiceExtension):
	""" A proxy extension using squid.

		On the server:

			- if config file present, the extension is available.
			- else non-available.

		On a client:

			- always avalaible.
		 	- enabled if extension is also enabled on the server.


		.. note:: On Ubuntu there is no distinction between available and
			enabled because we have no way to make the service not start at
			system boot. Thus, if available, this extension **is** enabled.


	"""

	def __init__(self):

		ServiceExtension.__init__(self,
			name='squid',
			service_name='squid',
			service_type=services.UPSTART
		)
		assert ltrace(self.name, '| __init__()')
		self.server_only=False

		# no particular controller for this extension, it is a
		# standalone one (no data, just configuration).
		self.controllers_compat = []

		self.service_name = 'squid'
		self.paths.squid_conf = '/etc/squid/squid.conf'
		self.paths.squid_bin = '/usr/sbin/squid'
		self.paths.squid_pid = '/var/run/squid.pid'

		self.defaults_conf = self.get_defaults_conf()

		if LMC.configuration.licornd.role == licornd_roles.SERVER:
			self.defaults = Enumeration()
			for key, value in (
				('http_port',self.defaults_conf.port),
				('acl', 'localnetwork src %s' % self.defaults_conf.subnet),
				('acl', 'server src %s' % '127.0.0.1'),
				('acl', 'all src all'),
				('http_access', 'allow localnetwork'),
				('http_access', 'allow server'),
				('http_access', 'deny all')):
				add_or_dupe_enumeration(self.defaults, key, value)

	def get_defaults_conf(self):
		""" TODO """

		#attention: "dict" est un mot réservé (builtin "dict()" de python)
		dict = Enumeration()
		dict['port'] = '3128'
		dict['client_file'] = '/etc/environment'
		dict['apt_conf'] = '/etc/apt/apt.conf.d/proxy'
		dict['client_cmd_http'] = 'http_proxy'
		dict['client_cmd_ftp'] = 'ftp_proxy'

		if LMC.configuration.licornd.role == licornd_roles.SERVER:
			dict['subnet'] = '192.168.0.0/24'
			dict['config_file'] = '/etc/squid/squid.conf'
			dict['host'] = '127.0.0.1'
		else:
			dict['host'] = LMC.configuration.server_main_address

		dict['client_cmd_value_http'] = '"http://%s:%s/"' % (
			dict['host'], dict['port'])
		dict['client_cmd_value_ftp'] = '"ftp://%s:%s/"' % (
			dict['host'], dict['port'])
		dict['apt_cmd_http'] = 'Acquire::http::Proxy'
		dict['apt_cmd_http_value'] = '"http://%s:%s";' % (
			dict['host'], dict['port'])
		dict['apt_cmd_ftp'] = 'Acquire::ftp::Proxy'
		dict['apt_cmd_ftp_value'] = '"ftp://%s:%s";' % (
			dict['host'], dict['port'])

		return dict

	def is_enabled(self):
		""" Squid extension is enabled when squid's pid file exists and the
			process runs.

			.. note:: as stated above, the service **MUST** be running if
				installed. This method starts it if needed.
		"""
		if self.available:
			if not self.running(self.paths.squid_pid):
				self.service(svccmds.START)
			return True
		else:
			return False
	def initialize(self):
		""" TODO """
		assert ltrace(self.name, '> initialize()')
		if LMC.configuration.licornd.role == licornd_roles.SERVER:

			if os.path.exists(self.paths.squid_bin) \
				and os.path.exists(self.paths.squid_conf):
				self.available = True

				self.configuration = ConfigFile(self.paths.squid_conf,
							separator=' ')
			else:
				logging.warning2('%s: not available because %s or %s do not '
					'exist on the system.' % (
						self.name, stylize(ST_PATH,
						self.paths.squid_bin),
						stylize(ST_PATH, self.paths.squid_conf)))
				self.remove_configuration()

		else:
			# squid extension is always available on clients.
			self.available = True
		assert ltrace(self.name, '< initialize()')
		return self.available
	def update_client(self, batch=None, auto_answer=None):
		""" update the client, make the client connecting through the proxy if
		the extension is enabled.
			We need to set/unset several parameters in different places :

				- environment parameter 'http_proxy' for current process and
					sub-process.
				- 'http_proxy' in /etc/environment to set this env param for
					future logged-in user.
				- deal with gconf to set proxy for gnome apps.
				- params in apt configuration
		"""
		assert ltrace(self.name, '> update_client()' )

		env_file = ConfigFile(self.defaults_conf.client_file,
			separator='=')
		env_need_rewrite = False

		if self.enabled:
			# set the env param
			os.putenv(self.defaults_conf.client_cmd_http,
				self.defaults_conf.client_cmd_value_http)
			os.putenv(self.defaults_conf.client_cmd_ftp,
				self.defaults_conf.client_cmd_value_ftp)

			# set 'http_proxy' in /etc/environment
			for cmd, value in (
				(self.defaults_conf.client_cmd_http,
				self.defaults_conf.client_cmd_value_http) ,
				(self.defaults_conf.client_cmd_ftp,
				self.defaults_conf.client_cmd_value_ftp)):

				if env_file.has(cmd):
					if env_file[cmd] != value:

						env_need_rewrite = True
						env_file.add(
							key=cmd,
							value=value,
							replace=True)
				else:
					env_need_rewrite = True
					env_file.add(
						key=cmd,
						value=value)

			if env_need_rewrite:
				if batch or logging.ask_for_repair('%s must be modified' %
					stylize(ST_PATH, self.defaults_conf.client_file),
					auto_answer=auto_answer):
					env_file.backup()
					env_file.save()
					logging.info('Written configuration file %s.' %
					stylize(ST_PATH, self.defaults_conf.client_file))
				else:
					raise exceptions.LicornModuleError(
						'configuration file %s must be altered to continue.' %
							self.defaults_conf.client_file)

			# set mandatory proxy params for gnome.
			gconf_values = (
				['string', '--set', '/system/http_proxy/host',
					self.defaults_conf.host ],
				[ 'string', '--set', '/system/proxy/ftp_host',
					self.defaults_conf.host ],
				[ 'string', '--set', '/system/proxy/mode', 'manual' ],
				[ 'bool', '--set', '/system/http_proxy/use_http_proxy', 'true'],
				[ 'int', '--set', '/system/http_proxy/port',
					str(self.defaults_conf.port) ],
				[ 'int', '--set', '/system/proxy/ftp_port',
					str(self.defaults_conf.port) ] )
				# TODO : addresses in ignore_host.
				#[ 'list', '--set', '/system/http_proxy/ignore_hosts', '[]',
				#'--list-type',  'string'])
			base_command = [ 'gconftool-2', '--direct', '--config-source',
				'xml:readwrite:/etc/gconf/gconf.xml.mandatory', '--type' ]
			for gconf_value in gconf_values:
				command = base_command[:]
				command.extend(gconf_value)

				process.execute(command)

			# set params in apt conf
			apt_file = ConfigFile(self.defaults_conf.apt_conf,
				separator=' ')
			apt_need_rewrite = False

			if not apt_file.has(key=self.defaults_conf.apt_cmd_http):
				apt_need_rewrite = True
				apt_file.add(key=self.defaults_conf.apt_cmd_http,
					value=self.defaults_conf.apt_cmd_http_value)
			if not apt_file.has(key=self.defaults_conf.apt_cmd_ftp):
				apt_need_rewrite = True
				apt_file.add(key=self.defaults_conf.apt_cmd_ftp,
					value=self.defaults_conf.apt_cmd_ftp_value)
			if apt_need_rewrite:
				if batch or logging.ask_for_repair('%s must be modified' %
					stylize(ST_PATH, self.defaults_conf.apt_conf),
					auto_answer=auto_answer):
					apt_file.backup()
					apt_file.save()
					logging.info('Written configuration file %s.' %
					stylize(ST_PATH, self.defaults_conf.apt_conf))
				else:
					raise exceptions.LicornModuleError(
						'configuration file %s must be altered to continue.' %
							elf.defaults_conf.apt_conf)


		else:
			self.remove_configuration()

		assert ltrace(self.name, '< update_client()' )
	def check(self, batch=None, auto_answer=None):
		""" check if *stricly needed* values are in the configuration file.
		if they are not, the extension will not be enabled

			needed squid params:
				- general:
					- http_port: squid port.
				- security:
					- acl all src all
					- acl localnetwork src 192.168.0.0/24 : range  of machines
						allowed to connect to the proxy server.
					- acl localhost src 127.0.0.1 : allow the server to
						connect through the proxy
					- http_access allow localhost : allow access to the server.
					- http_access allow localnetwork : allow access to the
						server.
					- http_access deny all : disable access to others.
		"""
		assert ltrace(self.name, '> check()' )
		if LMC.configuration.licornd.role == licornd_roles.SERVER:


			logging.progress('Checking good default values in %s…' %
					stylize(ST_PATH, self.paths.squid_conf))

			need_rewrite = False

			for key, value in self.defaults.iteritems():
				if hasattr(value, '__iter__'):
					for v in value:
						if not self.configuration.has(key, v):
							need_rewrite = True
							self.configuration.add(key, v)
				else:
					if not self.configuration.has(key, value):
						need_rewrite = True
						self.configuration.add(key, value)

			if need_rewrite:
				if batch or logging.ask_for_repair('%s must be modified' %
						stylize(ST_PATH, self.paths.squid_conf),
						auto_answer=auto_answer):
					self.configuration.backup()
					self.configuration.save()
					logging.info('Written configuration file %s.' %
						stylize(ST_PATH, self.paths.squid_conf))
				else:
					raise exceptions.LicornCheckError(
						'configuration file %s must be altered to continue.' %
							self.paths.sshd_config)

				self.service(svccmds.RELOAD)

		# finally, update system to deal or not with the extension.
		self.update_client()

		assert ltrace(self.name, '< check()' )
		return True
	def remove_configuration(self, batch=None, auto_answer=None):
		""" TODO """
		env_file = ConfigFile(self.defaults_conf.client_file,
			separator='=')
		env_need_rewrite = False

		# unset env param
		os.putenv(self.defaults_conf.client_cmd_http,'')
		os.putenv(self.defaults_conf.client_cmd_ftp,'')

		# unset 'http_proxy' in /etc/environment
		for cmd in (self.defaults_conf.client_cmd_http,
			self.defaults_conf.client_cmd_ftp):

			if env_file.has(cmd):
				env_file.remove(key=cmd)
				env_need_rewrite = True

		# unset gnome proxy configuration
		for file in ('xml:readwrite:/etc/gconf/gconf.xml.mandatory',
			'xml:readwrite:/etc/gconf/gconf.xml.defaults'):
			process.execute(['gconftool-2', '--direct', '--config-source',
				file, '--recursive-unset', '/system/http_proxy'])
			process.execute(['gconftool-2', '--direct', '--config-source',
				file, '--recursive-unset', '/system/proxy'])

		# unset apt conf params
		if os.path.exists(self.defaults_conf.apt_conf):
			os.unlink(self.defaults_conf.apt_conf)

		if env_need_rewrite:
			if batch or logging.ask_for_repair('%s must be modified' %
				stylize(ST_PATH, self.defaults_conf.client_file),
				auto_answer=auto_answer):
				env_file.backup()
				env_file.save()
				logging.info('Written configuration file %s.' %
				stylize(ST_PATH, self.defaults_conf.client_file))
			else:
				raise exceptions.LicornModuleError(
						'configuration file %s must be altered to continue.' %
							self.defaults_conf.client_file)


	def enable(self, batch=False, auto_answer=None):
		""" TODO """
		self.check(batch=batch, auto_answer=auto_answer)
		self.service(svccmds.START)
	def disable(self):
		# TODO : self.remove_configuration()
		self.service(svccmds.STOP)