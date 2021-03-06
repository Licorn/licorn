# -*- coding: utf-8 -*-
"""
Licorn extensions: OpenSSH - http://docs.licorn.org/extensions/openssh.html

:copyright: 2010 Olivier Cortès <olive@deep-ocean.net>

:license: GNU GPL version 2

"""

import os, errno

from licorn.foundations           import exceptions, logging, settings
from licorn.foundations           import fsapi, process
from licorn.foundations.styles    import *
from licorn.foundations.ltrace    import *
from licorn.foundations.ltraces   import *
from licorn.foundations.base      import ObjectSingleton
from licorn.foundations.classes   import ConfigFile
from licorn.foundations.constants import services, svccmds, roles, distros

from licorn.core               import LMC
from licorn.extensions         import ServiceExtension


class OpensshExtension(ObjectSingleton, ServiceExtension):
	""" Handle [our interesting subset of] OpenSSH configuration and options.
	"""
	def __init__(self):
		assert ltrace(TRACE_OPENSSH, '| OpensshExtension.__init__()')

		ServiceExtension.__init__(self,
			name='openssh',
			service_name='ssh',
			service_type=services.UPSTART
							if LMC.configuration.distro == distros.UBUNTU
							else services.SYSV
		)

		# Paths are the same on Ubuntu and Debian.
		self.paths.sshd_config = '/etc/ssh/sshd_config'
		self.paths.sshd_binary = '/usr/sbin/sshd'
		self.paths.pid_file    = '/var/run/sshd.pid'
		self.paths.disabler    = '/etc/ssh/sshd_not_to_be_run'

		# The administrator can change the group
		# name if desired. Default is 'remotessh'.
		self.group = settings.get('extensions.openssh.group', 'remotessh')

		self.defaults = {
				'UsePAM'                 : 'yes',
				'StrictModes'            : 'yes',
				'AllowGroups'            : '%s %s' % (
						settings.defaults.admin_group,
						self.group
					),
				'PermitRootLogin'        : 'no',
				'PasswordAuthentication' : 'yes',
			}
	def initialize(self):
		""" Return True if :program:`sshd` is installed on the system and if
			the file :file:`sshd_config` exists where it should be.

			.. note:: it's up to the ``openssh-server`` package maintainer
				to ensure the configuration file is created after package
				installation: it's not our role to create it, because we don't
				have enough default directives for that.

				If the configuration file or the executable don't exist, a
				:func:`~licorn.foundations.logging.warning2` will be issued to
				be sure the administrator can know what's going with relative
				ease (e.g. launch :program:`licornd -rvD`). We don't use
				:func:`~licorn.foundations.logging.warning` to not a pollute
				standard messages in normal/wanted situations (when OpenSSH is
				simply not installed).
		"""

		assert ltrace_func(TRACE_OPENSSH)

		if os.path.exists(self.paths.sshd_binary) \
				and os.path.exists(self.paths.sshd_config):
			self.available = True

			self.configuration = ConfigFile(self.paths.sshd_config,
															separator=' ')
		else:
			logging.warning2(_(u'{0}: not available because {1} or {2} do '
						u'not exist on the system.').format(self.pretty_name,
							stylize(ST_PATH, self.paths.sshd_binary),
							stylize(ST_PATH, self.paths.sshd_config)))


		assert ltrace(self._trace_name, '< initialize(%s)' % self.available)
		return self.available
	def is_enabled(self):
		""" OpenSSH server is enabled when the service-disabler
			does not exist. If we should run, verify the ``SSHd``
			process is currently running, else start it.

			..note:: Starting the ``SSHd`` process here is just a matter of
				consistency: :attr:`self.enabled` implies the service runs, so
				this must be carefully enforced.

				After that point, if the configuration changes because of our
				needs, the process will be reloaded as needed, but this is a
				distinct operation. For extension consistency, the two must be
				done.
		"""
		assert ltrace_func(TRACE_OPENSSH)

		must_be_running = not os.path.exists(self.paths.disabler)

		if must_be_running and not self.running(self.paths.pid_file):
			self.service(svccmds.START)

		# strip the OpenSSL stuff, then the 'OpenSSH_' prefix
		ssh_version = process.execute(('ssh', '-V'))[1].split(',')[0].split('_')[1]

		logging.info(_(u'{0}: extension available on top of {1} version '
				u'{2}, service currently {3}.').format(self.pretty_name,
								stylize(ST_NAME, 'OpenSSH'),
								stylize(ST_UGID, ssh_version),
								stylize(ST_OK, _('enabled'))
									if must_be_running
									else stylize(ST_BAD, _('disabled'))))

		assert ltrace(self._trace_name, '| is_enabled() → %s' % must_be_running)
		return must_be_running
	def check(self, batch=False, auto_answer=None):
		""" Check our OpenSSH needed things (the ``remotessh`` group and our
			predefined configuration directives and values), and
			:meth:`reload <~licorn.extensions.ServiceExtension.service>` the
			service on any change.

			.. note:: TODO: i'm not sure if creating the group really implies
				``SSHd`` to be reloaded. If it resolves the GID on start for
				performance consideration, we should. But if the ``AllowGroups``
				check is purely dynamic (which I think, because members could
				easily change during an ``SSHd`` run), the reload on group creation
				is useless. Go into sshd sources and see for ourselves... One day,
				When I've got time. As of now, stay as much careful as we can.
		"""

		assert ltrace_func(TRACE_OPENSSH)

		need_reload = False

		if settings.role != roles.CLIENT:
			# The 'remotessh' group is meant to be checked on the server side.
			# The client connects to LDAP (or anything equivalent), and the
			# group is expected to be there.

			# TODO if not self.group in LMC.groups.by_name:
			if not LMC.groups.exists(name=self.group):
				need_reload = True
				if batch or logging.ask_for_repair(_(u'{0}: group {1} must be '
									u'created. Do it?').format(
									self.pretty_name,
									stylize(ST_NAME, self.group)),
								auto_answer=auto_answer):
					LMC.groups.add_Group(name=self.group,
						description=_(u'Users allowed to connect via SSHd'),
						system=True, batch=batch)
				else:
					raise exceptions.LicornCheckError(_(u'{0}: group {1} must '
										u'exist before continuing.').format(
											self.pretty_name,
											stylize(ST_NAME, self.group)))

		logging.progress(_(u'{0}: checking good default values in {1}…').format(
						self.pretty_name, stylize(ST_PATH, self.paths.sshd_config)))

		need_rewrite = False
		for key, value in self.defaults.iteritems():
			if not self.configuration.has(key, value):
				need_rewrite = True
				self.configuration.add(key, value, replace=True)

		if need_rewrite:
			if batch or logging.ask_for_repair(_(u'{0}: {1} must be modified. '
							u'Do it?').format(self.pretty_name,
								stylize(ST_PATH, self.paths.sshd_config)),
							auto_answer=auto_answer):
				self.configuration.backup()
				self.configuration.save()
				logging.info(_(u'{0}: written configuration file {1}.').format(
					self.pretty_name,
					stylize(ST_PATH, self.paths.sshd_config)))
			else:
				raise exceptions.LicornCheckError(_(u'{0}: configuration file '
								u'{1} must be altered to continue.').format(
									self.pretty_name,
									stylize(ST_PATH, self.paths.sshd_config)))

		if need_reload or need_rewrite:
			self.service(svccmds.RELOAD)

		assert ltrace_func(TRACE_OPENSSH, True)
	def enable(self, batch=False, auto_answer=None):
		""" Start ``SSHd``, after having carefully checked all our needed
			parameters and unlinked the service disabler file.
		"""

		assert ltrace_func(TRACE_OPENSSH)

		self.check(batch=batch, auto_answer=auto_answer)

		try:
			# this has to be done as late as possible, thus after the check, to
			# avoid potential races (starting the service from outside Licorn®
			# while we are writing the config file in self.check(), for example).
			os.unlink(self.paths.disabler)

		except (OSError, IOError), e:
			if e.errno != errno.ENOENT:
				raise

		self.service(svccmds.START)

		self.enabled = True

		return True
	def disable(self):
		""" Stop the running SSHd and touch the disabler file to make sure
			it is not restarted outside of Licorn®.

			.. note:: TODO: we've got to check this operation is atomic.
				Shouldn't we create the disabler file before stopping the
				service, to be sure no one else can race-start it ?
			"""
		assert ltrace_func(TRACE_OPENSSH)

		self.service(svccmds.STOP)

		fsapi.touch(self.paths.disabler)

		self.enabled = False
		return True
