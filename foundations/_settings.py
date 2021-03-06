# -*- coding: utf-8 -*-
"""
Licorn Foundations: base settings - http://docs.licorn.org/foundations/

Copyright (C) 2011 Olivier Cortès <olive@deep-ocean.net>
Licensed under the terms of the GNU GPL version 2
"""

import time, os, getpass, errno, tempfile
from threading import current_thread

# ================================================= Licorn® foundations imports
import logging, styles, events
# WARNING: don't import "options", this would produce a circular loop.

from ltrace    import *
from ltraces   import *
from styles    import *
from pyutils   import resolve_attr, format_time_delta
from process   import cgroup
from threads   import RLock
from base      import ObjectSingleton, NamedObject, LicornConfigObject, BasicCounter
from constants import roles

# circumvent the `import *` local namespace duplication limitation.
stylize = styles.stylize

import readers, network, exceptions

class LicornSettings(ObjectSingleton, NamedObject, LicornConfigObject):
	def __init__(self, filename=None):
		assert ltrace_func(TRACE_SETTINGS)

		NamedObject.__init__(self, name='settings')
		LicornConfigObject.__init__(self)

		# make both classes happy when rendering str()
		self._name = self.name

		self.experimental_should_be_enabled = False

		self.defaults = LicornConfigObject(parent=self)

		self.defaults.home_base_path         = '/home'
		self.defaults.check_homedir_filename = '00_default'

		# default expiration time (float, in seconds) for various things
		# (see core.classes.CoreFSController._expire_events()).
		self.defaults.global_expire_time = 10.0

		# WARNING: Don't translate this group name.
		# TODO: move this into a plugin ? extension ? else ?
		self.defaults.admin_group = 'admins'

		# TODO: autodetect this & see if it not autodetected elsewhere.
		#self.defaults.quota_device = "/dev/hda1"

		# TODO: protect (all of?) these by turning them into R/O properties.
		self.config_dir              = u'/etc/licorn'
		self.data_dir                = u'/var/lib/licorn'
		self.cache_dir               = u'/var/cache/licorn'
		self.check_config_dir        = self.config_dir + u'/check.d'
		self.main_config_file        = self.config_dir + u'/licorn.conf'
		self.inotifier_exclude_file  = self.config_dir + u'/nowatch.conf'
		self.home_backup_dir         = self.defaults.home_base_path + u'/backup'
		self.home_archive_dir        = self.defaults.home_base_path + u'/archives'
		self.tasks_data_file         = self.config_dir + u'/tasks.conf'

		# the inotifier wants a lock. We don't use it internally otherwise.
		self.lock = RLock()

		# hints for inotified files.
		self.__hint_main    = BasicCounter(1)
		self.__hint_nowatch = BasicCounter(1)

		self.__load_factory_settings()

		# on first load, we don't emit the "settings_changed" event.
		# This would be like a false-positive.
		self.reload(emit_event=False)

		if self.experimental.enabled and os.geteuid() == 0:
			logging.warning(stylize(ST_ATTR, _(u'Experimental features '
												u'enabled. Have fun, and '
												u'hope it does not break '
												u'anything.')))

		events.collect(self)
	def __str__(self):
		return LicornConfigObject.__str__(self)
	def __load_factory_settings(self):
		""" The defaults set here are expected to exist
			by other parts of the programs.

			Note: we use port 299 for pyro. This is completely unusual. Port 299
			doesn't seem to be reserved in a recent /etc/services file, and this
			ensure that we are root when binding the port, and thus provide a
			*small* security guarantee (any attacker but first gain root
			privileges or crash our daemons to bind the port and spoof our
			protocol). """

		assert ltrace(TRACE_SETTINGS, '| load_factory_defaults()')

		self.merge_settings({
			'role'                         : roles.UNSET,

			# In case of multiple servers on the same LAN, the administrator
			# can eventually assign a lower priority to some, for testing or
			# debugging purposes. In normal conditions, this should not be
			# changed in the configuration, and is thus not documented
			# officially.
			'group'                        : cgroup or '/',
			'favorite_server'              : None,
			'pyro.port'                    : int(os.getenv('PYRO_PORT', 299)),

			# timeout for CLI connect; in seconds.
			'connect.timeout'              : 30,

			'experimental.enabled'         : self.experimental_should_be_enabled,

			# TODO: move the following directives to where they belong.

			# system profiles, compatible with gnome-system-tools
			'core.profiles.config_file'    : self.config_dir + u'/profiles.xml',
			'core.privileges.config_file'  : self.config_dir + u'/privileges-whitelist.conf',
			'core.keywords.config_file'    : self.config_dir + u'/keywords.conf',
			# extensions to /etc/group
			'backends.shadow.extended_group_file' : self.config_dir + u'/groups',
			'backends.openldap.organization'      : 'Licorn®',
			}, emit_event=False)
	def __convert_settings_values(self):
		assert ltrace(TRACE_SETTINGS, '| BaseDaemon.__convert_settings_values()')

		if self.role not in roles:
			# use upper() to avoid bothering user if he has typed "server"
			# instead of "SERVER". Just be cool when possible.
			if hasattr(roles, self.role.upper()):
				self.role = getattr(roles, self.role.upper())
	def __check_debug_variable(self):
		self.debug = []

		env_variable = os.getenv('LICORN_DEBUG', None)

		if env_variable is not None and os.geteuid() == 0:
			self.debug.extend(d.lower() for d in env_variable.split(','))

			logging.warning(_(u'{0}: internal debug enabled for {1}').format(
						stylize(ST_NAME, 'settings'),
						u', '.join(stylize(ST_NAME, x) for x in self.debug)))
	def check(self):
		""" Check directives which must be set, and values, for correctness. """

		assert ltrace_func(TRACE_SETTINGS)

		self.__check_settings_role()
		self.__check_debug_variable()

	def __check_settings_role(self):
		""" check the licornd.role directive for correctness. """

		assert ltrace_func(TRACE_SETTINGS)

		if self.role == roles.UNSET or self.role not in roles:
			raise exceptions.BadConfigurationError(_(u'{0} is currently '
				u'unset or invalid in {1}. Please set it to either {2} or '
				u'{3} and retry.').format(
					stylize(ST_SPECIAL, 'role'),
					stylize(ST_PATH, self.main_config_file),
					stylize(ST_COMMENT, 'SERVER'),
					stylize(ST_COMMENT, 'CLIENT')
					)
				)
	@events.handler_method
	def configuration_loaded(self, event, *args, **kwargs):
		""" This one needs to be defered until LMC.configuration is loaded,
			else we create a chicken-and-egg problem. """

		caller = stylize(ST_NAME, current_thread().name)

		if self.role == roles.CLIENT:
			logging.progress(_(u'{0}: looking up our Licorn® server…').format(caller))

			start = time.time()

			self.server_main_address, self.server_main_port = network.find_server(
											self.favorite_server, self.group)

			if self.server_main_port is None:
				self.server_main_port = self.pyro.port

			if self.server_main_address is None:
				logging.error(_(u'Could not find our Licorn® server via '
					u'autodetection. Please contact your network '
					u'administrator or set the {0} environment variable.').format(
					stylize(ST_NAME, 'LICORN_SERVER')))

			logging.notice(_(u'{0}: our Licorn® server is {1} (resolution '
								u'took {2}).').format(caller,
								stylize(ST_URL, 'pyro://{0}:{1}/'.format(
												self.server_main_address,
												self.server_main_port)),
								stylize(ST_COMMENT, format_time_delta(
									time.time() - start,
									long_output=False, big_precision=False))))
	def merge_settings(self, conf, overwrite=True, emit_event=True):
		""" Build the licorn configuration object from a dict. """

		assert ltrace_func(TRACE_SETTINGS)

		changed = False

		for key in conf.keys():
			subkeys = key.split('.')
			if len(subkeys) > 1:
				curobj = self
				for subkey in subkeys[:-1]:
					if not hasattr(curobj, subkey):
						setattr(curobj, subkey, LicornConfigObject(parent=curobj))
					#down one level.
					curobj = getattr(curobj, subkey)

				if hasattr(curobj, subkeys[-1]):
					if getattr(curobj, subkeys[-1]) != conf[key] and overwrite:
						assert ltrace(TRACE_SETTINGS, '  settings: subkey {0} '
							'changed from {1} to {2}', (ST_NAME, key),
								(ST_ATTR, getattr(curobj, subkeys[-1])),
								(ST_ATTR, conf[key]))
						setattr(curobj, subkeys[-1], conf[key])
						changed = True

				else:
					setattr(curobj, subkeys[-1], conf[key])
					changed = True

			else:
				if hasattr(self, key):
					if getattr(self, key) != conf[key] and overwrite:
						assert ltrace(TRACE_SETTINGS, '  settings: subkey {0} '
							'changed from {1} to {2}', (ST_NAME, key),
								(ST_ATTR, getattr(self, key)),
								(ST_ATTR, conf[key]))
						setattr(self, key, conf[key])
						changed = True

				else:
					setattr(self, key, conf[key])
					changed = True

		if changed and emit_event:
			from licorn.foundations.events import LicornEvent
			LicornEvent('settings_changed').emit()
	def __load_main_config_file(self, emit_event=True):
		"""Load main configuration file, and set mandatory defaults
			if it doesn't exist."""

		assert ltrace_func(TRACE_SETTINGS)

		try:
			self.merge_settings(readers.shell_conf_load_dict(
				self.main_config_file, convert='full'), emit_event=emit_event)

		except IOError, e:
			if e.errno != 2:
				# errno == 2 is "no such file or directory" -> don't worry if
				# main config file isn't here, this is not required.
				raise e

		assert ltrace_func(TRACE_SETTINGS, 1)
	@property
	def inotifier_exclusions(self):
		return self.__nowatch
	def __load_inotifier_exclusions(self, emit_event=True):

		if not hasattr(self, '__nowatch'):
			self.__nowatch = set()

		try:
			oldset = self.__nowatch.copy()

			self.__nowatch |= set(s.strip() for s in open(self.inotifier_exclude_file).readlines() if s[0] == '/')

		except (OSError, IOError), e:
			if e.errno != errno.ENOENT:
				logging.exception(_(u'Exception while loading {0}; no '
									u'exclusions defined'),
									(ST_PATH, self.inotifier_exclude_file))

			# no read, no contents, reset the exclusions.
			self.__nowatch = set()

		if oldset != self.__nowatch and emit_event:
			from licorn.foundations.events import LicornEvent
			LicornEvent('settings_inotifier_exclusions_changed').emit()
	def add_inotifier_exclusion(self, path):

		if path in self.__nowatch:
			return

		self.__nowatch.add(path)
		self.__save_inotifier_exclusions()
	def del_inotifier_exclusion(self, path):
		try:
			self.__nowatch.remove(path)

		except:
			logging.exception(_(u'Unable to remove {0} from inotifier exclusions'), (ST_PATH, path))

		else:
			self.__save_inotifier_exclusions()
	def __save_inotifier_exclusions(self):

		# don't save an empty file.
		if self.__nowatch != []:
			try:
				# prevent inotifier false-positive event.
				self.__hint_nowatch += 2

				open(self.inotifier_exclude_file, 'wb').write('\n'.join(self.__nowatch))

			except:
				logging.exception(_(u'Exception while saving {0}!'), (ST_PATH, self.inotifier_exclude_file))
	def _inotifier_install_watches(self, **kwargs):
		""" We watch 2 files and use the same trigger function, it reloads
			only if things really changed. """

		self.__hint_main    = L_inotifier_watch_conf(
									settings.main_config_file,
									self, self.reload)
		self.__hint_nowatch = L_inotifier_watch_conf(
									settings.inotifier_exclude_file,
									self, self.reload)
	def reload(self, emit_event=True, **kwargs):

		with self.lock:
			self.__load_main_config_file(emit_event)

			# TODO:
			#self.__load_config_directory()

			self.__convert_settings_values()

			self.__load_inotifier_exclusions(emit_event)

			self.check()
	def get(self, setting_name, default_value=None):

		with self.lock:
			if not setting_name.startswith('settings.'):
				setting_name = 'settings.' + setting_name

			try:
				value = resolve_attr(setting_name, {'settings': self})

			except AttributeError:
				if default_value is None:
					raise

				else:
					return default_value
	def set(self, setting_name, value):
		""" If value is explicitely ``None``, we will delete the key. """

		with self.lock:
			try:
				# Don't bother write the new setting if unchanged.
				if self.get(setting_name) == value:
					return

			except AttributeError:
				# No current setting with that name.

				if value is None:
					# Wanted to delete a non-existing setting.
					return

			if setting_name.startswith('settings.'):
				setting_name = setting_name[9:]

			if value is None:
				replace = False
			else:
				replace = True

			found   = False
			newdata = ''

			with open(self.main_config_file) as f:
				for line in f.readline():
					if line.startswith(setting_name + ' ') or line.startswith(setting_name + '='):
						if replace:
							newdata += '{0} = {1}\n'.format(setting_name, value)
							found = True

						else:
							# delete mode. skip the line
							continue

					else:
						# keep any non-matching line
						newdata += line

			if not found:
				# Setting was not present, but now needs to be.
				newdata += '{0} = {1}\n'.format(setting_name, value)

			# Cannot do this at the top of module,
			# because `fsapi` already imports us.
			from licorn.foundations import fsapi

			fsapi.backup_file(self.main_config_file)
			ftempp, fpathp = tempfile.mkstemp(dir=self.config_dir)
			os.write(ftempp, newdata)

			# This will be done later by a worker
			#os.fchmod(ftempp, 0644)
			#os.fchown(ftempp, 0, 0)

			os.close(ftempp)
			# Avoid a reload triggered by our own write().
			self.__hint_main += 1
			os.rename(fpathp, self.main_config_file)

			# If everything went fine, finally make the new setting
			# available for everyone else. We could do it faster with
			# dedicated code, but re-using :meth:`merge_settings` makes
			# it shorter and more maintainable.
			self.merge_settings({setting_name: value})

		# This will trigger the file checking in LMC.configuration,
		# without the need to import workers and LMC here.
		from licorn.foundations.events import LicornEvent
		LicornEvent('settings_file_written').emit()


settings = LicornSettings()

__all__ = ('settings', )
