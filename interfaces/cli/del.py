#!/usr/bin/python -OO
# -*- coding: utf-8 -*-
"""
Licorn CLI - http://dev.licorn.org/documentation/cli

delete - delete sompething on the system, an unser account, a group, etc.

Copyright (C) 2005-2007 Olivier Cortès <olive@deep-ocean.net>,
Partial Copyright (C) 2006-2007 Régis Cobrun <reg53fr@yahoo.fr>
Licensed under the terms of the GNU GPL version 2.

"""

import sys, re

from licorn.foundations import logging, exceptions, options, objects, styles

from licorn.core.configuration import LicornConfiguration
from licorn.core.users         import UsersController
from licorn.core.groups        import GroupsController
from licorn.core.profiles      import ProfilesController
from licorn.core.keywords      import KeywordsController

_app = {
	"name"     		: "licorn-delete",
	"description"	: "Licorn Delete Entries",
	"author"   		: "Olivier Cortès <olive@deep-ocean.net>, Régis Cobrun <reg53fr@yahoo.fr>"
	}

def desimport_groups(delete_filename):
	""" Delete the groups (and theyr members) present in a import file.
	"""

	configuration = LicornConfiguration()
	users = UsersController(configuration)
	groups = GroupsController(configuration, users)

	if delete_filename is None:
		raise exceptions.BadArgumentError, "You must specify a file name"

	delete_file = file(delete_filename, 'r')

	groups_to_del = []

	user_re = re.compile("^\"?\w*\"?;\"?\w*\"?;\"?(?P<group>\w*)\"?$", re.UNICODE)
	for ligne in delete_file:
		mo = user_re.match(ligne)
		if mo is not None:
			u = mo.groupdict()
			g = u['group']
			if g not in groups_to_del:
				groups_to_del.append(g)

	delete_file.close()

	# Deleting
	length_groups = len(groups_to_del)
	quantity = length_groups
	if quantity <= 0:
		quantity = 1
	delta = 100.0 / float(quantity) # increment for progress indicator
	progression = 0.0
	i = 0 # to print i/length

	for g in groups_to_del:
		try:
			i += 1
			sys.stdout.write("\rDeleting groups (" + str(i) + "/" + str(length_groups) + "). Progression: " + str(int(progression)) + "%")
			groups.DeleteGroup(profiles, g, True, True, users)
			progression += delta
			sys.stdout.flush()
		except exceptions.LicornException, e:
			logging.warning(str(e))
	profiles.WriteConf(configuration.profiles_config_file)
	print "\nFinished"
def delete_user():
	""" delete a user account. """

	configuration = LicornConfiguration()
	users = UsersController(configuration)
	# groups is needed to delete the user from its groups, else its name will
	# stay dangling in memberUid.
	groups = GroupsController(configuration, users)

	for login in opts.login.split(','):
		if login != '':
			try:
				users.DeleteUser(login, opts.no_archive, opts.uid)
			except KeyError, e:
				logging.warning(
					"User %s doesn't exist on the system (was: %s)." % (
						login, e))

	users.WriteConf()
def delete_user_from_groups():
	configuration = LicornConfiguration()
	users = UsersController(configuration)
	groups = GroupsController(configuration, users)

	for g in opts.groups_to_del.split(','):
		if g != "":
			try:
				groups.RemoveUsersFromGroup(g, opts.login.split(','))
			except exceptions.LicornRuntimeException, e:
				logging.warning(
					"Unable to remove user(s) %s from group %s (was: %s)."
					% (styles.stylize(styles.ST_LOGIN, opts.login),
					styles.stylize(styles.ST_NAME, g), str(e)))
			except exceptions.LicornException, e:
				raise exceptions.LicornRuntimeError(
					"Unable to remove user(s) %s from group %s (was: %s)."
					% (styles.stylize(styles.ST_LOGIN, opts.login),
					styles.stylize(styles.ST_NAME, g), str(e)))
def delete_group():
	""" delete an Licorn group. """

	configuration = LicornConfiguration()
	users = UsersController(configuration)
	groups = GroupsController(configuration, users)
	profiles = ProfilesController(configuration, groups, users)

	if opts.name is None:
		try:
			groups.DeleteGroup(None, opts.del_users, opts.no_archive, opts.gid)

		except KeyError:
			logging.warning("Group %s doesn't exist on the system." % name)
	else:
		for name in opts.name.split(','):
			if name != '':
				try:
					groups.DeleteGroup(name, opts.del_users, opts.no_archive,
						opts.gid)

				except KeyError:
					logging.warning(
						"Group %s doesn't exist on the system." % name)

def delete_profile():
	""" Delete a system wide User profile. """

	configuration = LicornConfiguration()
	users = UsersController(configuration)
	groups = GroupsController(configuration, users)
	profiles = ProfilesController(configuration, groups, users)


	profiles.DeleteProfile(opts.group, opts.del_users, opts.no_archive, users,
		batch=opts.no_sync)

	if opts.no_sync:
		users.WriteConf()
def delete_keyword():
	""" delete a system wide User profile. """

	configuration = LicornConfiguration()
	keywords = KeywordsController(configuration)

	keywords.DeleteKeyword(opts.name, opts.del_children)
def delete_privilege():
	configuration = LicornConfiguration()
	configuration.groups.privileges_whitelist.delete(
		opts.privileges_to_remove.split(','))
def delete_workstation():
	raise NotImplementedError("delete_workstations not implemented.")
def delete_webfilter():
	raise NotImplementedError("delete_webfilters_types not implemented.")

if __name__ == "__main__":

	try:
		configuration = LicornConfiguration()
		giantLock = objects.FileLock(configuration, "giant", 10)
		giantLock.Lock()
	except (IOError, OSError), e:
		logging.error(logging.GENERAL_CANT_ACQUIRE_GIANT_LOCK % str(e))

	try:
		try:
			if "--no-colors" in sys.argv:
				options.SetNoColors(True)

			from licorn.interfaces.cli import argparser

			if len(sys.argv) < 2:
				# automatically display help if no arg/option is given.
				sys.argv.append("--help")
				argparser.general_parse_arguments(_app)

			if len(sys.argv) < 3:
				# this will display help, but when parsed later by specific functions.
				# (for user/group/profile specific help)
				sys.argv.append("--help")
				help_appended = True
			else:
				help_appended = False

			mode = sys.argv[1]

			if mode == 'user':
				(opts, args) = argparser.delete_user_parse_arguments(_app)
				options.SetFrom(opts)

				if opts.login is None:
					if len(args) == 2:
						opts.login = args[1]
						delete_user()
					elif len(args) == 3:
						opts.login = args[1]
						opts.groups_to_del = args[2]
						delete_user_from_groups()
				else:
					delete_user()

			elif mode == 'group':
				(opts, args) = argparser.delete_group_parse_arguments(_app)
				if opts.name is None and len(args) == 2:
					opts.name = args[1]
				options.SetFrom(opts)
				delete_group()

			elif mode == 'groups':
				# delete multiple groups and theyr members
				(opts, args) = argparser.delimport_parse_arguments(_app)
				options.SetFrom(opts)
				desimport_groups(opts.filename)

			elif mode == 'profile':
				(opts, args) = argparser.delete_profile_parse_arguments(_app)
				if opts.group is None and len(args) == 2:
					opts.group = args[1]
				options.SetFrom(opts)
				delete_profile()

			elif mode == 'keyword':
				(opts, args) = argparser.delete_keyword_parse_arguments(_app)
				if opts.name is None and len(args) == 2:
					opts.name = args[1]
				options.SetFrom(opts)
				delete_keyword()
			elif mode in ('priv', 'privilege', 'privs', 'privileges'):
				(opts, args) = argparser.del_privilege_parse_arguments(_app)
				if opts.privileges_to_remove is None and len(args) == 2:
					opts.privileges_to_remove = args[1]
				options.SetFrom(opts)
				delete_privilege()
			else:
				if not help_appended:
					logging.warning(logging.GENERAL_UNKNOWN_MODE % mode)
					sys.argv.append("--help")

				argparser.general_parse_arguments(_app)

		except exceptions.LicornException, e:
			logging.error (str(e), e.errno)

		except KeyboardInterrupt:
			logging.warning(logging.GENERAL_INTERRUPTED)

	finally:
		configuration.CleanUp()
		giantLock.Unlock()
