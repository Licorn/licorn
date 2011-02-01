# -*- coding: utf-8 -*-
"""
Licorn Foundations - http://dev.licorn.org/documentation/foundations

fsapi - File System API

These functions interact with a posix compatible filesystem, to ease common
operations like finding files, recursively checking / changing permissions
and ACLs, making / removing symlinks, and so on.

Copyright (C) 2005-2010 Olivier Cortès <olive@deep-ocean.net>
Licensed under the terms of the GNU GPL version 2
"""

import os, posix1e
from stat import *

from licorn.foundations.ltrace import ltrace
from licorn.foundations        import logging, exceptions, pyutils, process
from licorn.foundations.styles import *

from licorn.core import LMC

# WARNING: DON'T IMPORT licorn.core.configuration HERE.
# just pass "configuration" as a parameter if you need it somewhere.
# fsapi is meant to to be totally independant of licorn.core.configuration !!

def minifind(path, type=None, perms=None, mindepth=0, maxdepth=99, exclude=[],
	followlinks=False, followmounts=True):
	""" Mimic the GNU find behaviour in python. returns an iterator. """

	if mindepth > maxdepth:
		raise  exceptions.BadArgumentError("mindepth must be <= maxdepth.")

	if maxdepth > 99:
		raise  exceptions.BadArgumentError(
			"please don't try to exhaust maxdepth.")

	assert ltrace('fsapi', '''> minifind(%s, type=%s, mindepth=%s, maxdepth=%s, '''
		'''exclude=%s, followlinks=%s, followmounts=%s)''' % (
			path, type, mindepth, maxdepth, exclude, followlinks, followmounts))

	paths_to_walk      = [ path ]
	next_paths_to_walk = []
	current_depth      = 0
	S_IFSTD            = S_IFDIR | S_IFREG

	while True:

		if paths_to_walk != []:
			entry = paths_to_walk.pop(0)

		elif next_paths_to_walk != []:
			paths_to_walk      = next_paths_to_walk
			next_paths_to_walk = []
			entry              = paths_to_walk.pop(0)
			current_depth     += 1

		else:
			break

		try:
			entry_stat = os.lstat(entry)
			entry_type = entry_stat.st_mode & 0170000
			entry_mode = entry_stat.st_mode & 07777
		except (IOError, OSError), e:
			if e.errno == 2 or (e.errno == 13 and entry[-5:] == '.gvfs'):
				continue
			else:
				raise e
		else:
			if current_depth >= mindepth \
				and ( (type is None and entry_type & S_IFSTD) \
					or entry_type == type) \
				and ( perms is None or (entry_mode & perms) ):
				#ltrace('fsapi', '  minifind(yield=%s)' % entry)
				yield entry

			#print 'type %s %s %s' % (entry_type, S_IFLNK, entry_type & S_IFLNK)

			if (entry_type == S_IFLNK and not followlinks) \
				or (os.path.ismount(entry) and not followmounts):
				logging.progress('minifind(): skipping link or mountpoint %s.' %
					stylize(ST_PATH, entry))
				continue

			if entry_type == S_IFDIR and current_depth < maxdepth:
				try:
					for x in os.listdir(entry):
						if x not in exclude:
							next_paths_to_walk.append("%s/%s" % (entry, x))
						else:
							assert ltrace('fsapi', '  minifind(excluded=%s)' % entry)
				except (IOError, OSError), e:
					if e.errno == 2:
						# happens on recursive delete() applyed on minifind()
						# results: the dir vanishes during the os.listdir().
						continue
					else:
						raise e
def check_dirs_and_contents_perms_and_acls_new(dirs_infos, batch=False, auto_answer=None):
	""" general function to check file/dir """

	assert ltrace('fsapi', '> check_dirs_and_contents_perms_and_acls_new('
		'dirs_infos=%s, batch=%s, auto_answer=%s)' % (
			dirs_infos, batch, auto_answer))

	def check_one_dir_and_acl(dir_info, batch=batch, auto_answer=auto_answer):
		all_went_ok = True

		# Does the file/dir exist ?
		try:
			entry_stat = os.lstat(dir_info['path'])
		except OSError, e:
			if e.errno == 13:
				raise exceptions.InsufficientPermissionsError(str(e))
			elif e.errno == 2:
				warn_message = ("Directory %s does not exist." %
					stylize(ST_PATH, dir_info['path']))

				if batch or logging.ask_for_repair(warn_message, auto_answer,
					to_listener=True):
					os.mkdir(dir_info['path'])
					entry_stat = os.lstat(dir_info['path'])
					logging.info("Created directory %s." %
						stylize(ST_PATH, dir_info['path']),
						to_listener=True)
				else:
					# we cannot continue if dir does not exist.
					raise exceptions.LicornCheckError(
						"Can't continue checks for directory %s (was: %s)." % (
							dir_info['path'], e) )
			else:
				# FIXME: do more things to recover from more system errors…
				raise e

		# if it is a file
		if ( entry_stat.st_mode & 0170000 ) == S_IFREG:
			logging.progress("Checking file %s…" %
				stylize(ST_PATH, dir_info['path']))
			if dir_info.files_perm and dir_info.user \
				and dir_info.group:
				check_perms(
					file_type=S_IFREG,
					dir_info=dir_info,
					batch=batch, auto_answer=auto_answer)

		# if it is a dir
		elif ( entry_stat.st_mode & 0170000 ) == S_IFDIR:
			logging.progress("Checking dir %s…" %
				stylize(ST_PATH, dir_info['path']))
			# if the directory ends with '/' that mean that we will only
			# affect the content of the dir.
			# the dir itself will receive default licorn ACL rights (those
			# defined in the configuration)
			if dir_info.path[-1] == '/':
				dir_info_root = dir_info.copy()
				dir_info_root.root_dir_acl = True
				dir_info_root.root_dir_perm = "%s,g:%s:rwx,%s" % (
					LMC.configuration.acls.acl_base,
					LMC.configuration.defaults.admin_group,
					LMC.configuration.acls.acl_mask)
				dir_info_root.group = "acl"

				# now that the "root dir" has its special treatment,
				# prepare dir_info for the rest (its contents)
				dir_info.path = dir_info.path[:-1]
			else:
				dir_info_root = dir_info

			logging.progress("Checking %s's %s…" % (
				stylize(ST_PATH, dir_info['path']),
				"ACLs" if dir_info.root_dir_acl else "posix perms"))
			# deal with root dir
			check_perms(
				is_root_dir=True,
				file_type=S_IFDIR,
				dir_info=dir_info_root,
				batch=batch, auto_answer=auto_answer)

			if dir_info.files_perm != None or dir_info.dirs_perm != None:
				try:
					exclude_list = dir_info.exclude
				except AttributeError :
					exclude_list = []

			if dir_info.files_perm != None:
				logging.progress("Checking %s's contents %s…" % (
					stylize(ST_PATH, dir_info['path']),
					'ACLs' if dir_info.content_acl else 'posix perms'))

				dir_path = dir_info['path']

				if dir_info.dirs_perm != None:
					for dir in minifind(dir_path, exclude=exclude_list, mindepth=1,
						type=S_IFDIR):
						dir_info.path=dir
						check_perms(
							file_type=S_IFDIR,
							dir_info=dir_info,
							batch=batch, auto_answer=auto_answer)

				# deal with files inside root dir
				for file in minifind(dir_path, exclude=exclude_list, mindepth=1,
					type=S_IFREG):
						dir_info.path = file
						check_perms(
						file_type=S_IFREG,
						dir_info=dir_info,
						batch=batch, auto_answer=auto_answer)

		else:
			logging.warning('''The type of %s is not recognised by the '''
				'''check_user() function.''' % dir_info['path'])
		return all_went_ok

	if dirs_infos != None:
		# first, check default rule
		try:
			check_one_dir_and_acl(dirs_infos._default)
		except AttributeError:
			pass
		# check all specials_dirs
		for dir_info in dirs_infos:
			if check_one_dir_and_acl(dir_info) is False:
				return False

		return True

	else:
		raise exceptions.BadArgumentError(
			"You must pass something through dirs_infos to check!")

	assert ltrace('fsapi', '< check_dirs_and_contents_perms_and_acls_new()')
def check_perms(dir_info, file_type=None, is_root_dir=False,
					batch=None, auto_answer=None, full_display=True):
	""" general function to check if permissions are ok on file/dir """
	assert ltrace('fsapi', '> check_perms(dir_info=%s, file_type=%s, '
		'is_root_dir=%s, batch=%s, auto_answer=%s' % (
			dir_info, file_type, is_root_dir, batch, auto_answer))

	# get the access_perm and the type of perm (POSIX1E or POSIX) that will be
	# applyed on path
	if file_type is S_IFDIR:
		if is_root_dir:
			access_perm = dir_info.root_dir_perm
			perm_acl = dir_info.root_dir_acl
		else:
			access_perm = dir_info.dirs_perm
			perm_acl = dir_info.content_acl
	else:
		access_perm = dir_info.files_perm
		perm_acl = dir_info.content_acl

	# if we are going to set POSIX1E acls, check '@GX' or '@UX' vars
	if perm_acl:
		# FIXME : allow @X only.
		execperms = execbits2str(dir_info.path)

		if '@GX' in access_perm or '@UX' in access_perm:
			access_perm = access_perm.replace(
							'@GX', execperms[1]).replace(
							'@UX', execperms[0])

		access_perm = posix1e.ACL(text='%s' % access_perm)

	if is_root_dir:
		gid = dir_info.root_gid
	elif dir_info.content_gid is not None:
		gid = dir_info.content_gid
	else:
		gid = dir_info.root_gid

	uid=dir_info.uid

	check_uid_and_gid(path=dir_info.path, uid=uid, gid=gid,
		batch=batch, full_display=full_display)

	if full_display:
		logging.progress(_(u'Checking {perm_type} of {path}.').format(
				perm_type=_(u'POSIX.1e ACL')
					if perm_acl else _(u'posix perms'),
				path=stylize(ST_PATH, dir_info.path)))

	if perm_acl:
		# apply posix1e access perm on the file/dir
		current_perm = posix1e.ACL(file=dir_info.path)
		if current_perm != access_perm:

			if batch or logging.ask_for_repair(
							_(u'Invalid access ACL for {path} '
							'(it is {current_acl} but '
							'should be {access_acl}).').format(
								path=stylize(ST_PATH, dir_info.path),

								current_acl=stylize(ST_BAD,
											current_perm.to_any_text(
												separator=',',
												options=posix1e.TEXT_ABBREVIATE
												| posix1e.TEXT_SOME_EFFECTIVE)),

								access_acl=stylize(ST_ACL,
												access_perm.to_any_text(
												separator=',',
												options=posix1e.TEXT_ABBREVIATE
												| posix1e.TEXT_SOME_EFFECTIVE))
							),
							auto_answer=auto_answer):

					# be sure to pass an str() to acl.applyto(), else it will
					# raise a TypeError if onpath is an unicode string…
					# (checked 2006 08 08 on Ubuntu Dapper)
					# TODO: recheck this, as we don't use any unicode strings
					# anywhere (or we are before the move to using them
					# everywhere).
					posix1e.ACL(acl=access_perm).applyto(str(dir_info.path),
													posix1e.ACL_TYPE_ACCESS)

					logging.info(
						_(u'Applyed access ACL '
						'{access_acl} on {path}.').format(
							access_acl=stylize(ST_ACL,
											access_perm.to_any_text(
												separator=',',
												options=posix1e.TEXT_ABBREVIATE
												| posix1e.TEXT_SOME_EFFECTIVE)),
							path=stylize(ST_PATH, dir_info.path))
						)
			else:
				all_went_ok = False

		# if it is a directory, apply default ACLs
		if file_type is S_IFDIR:
			current_default_perm = posix1e.ACL(filedef=dir_info.path)

			if dir_info.dirs_perm != None and ':' in str(dir_info.dirs_perm):
				default_perm = dir_info.dirs_perm
			else:
				default_perm = dir_info.root_dir_perm

			default_perm = posix1e.ACL(text=default_perm)

			if current_default_perm != default_perm:

				if batch or logging.ask_for_repair(
							_(u'Invalid default ACL for {path} '
							'(it is {current_acl} but '
							'should be {access_acl}).').format(
								path=stylize(ST_PATH, dir_info.path),

								current_acl=stylize(ST_BAD,
											current_default_perm.to_any_text(
												separator=',',
												options=posix1e.TEXT_ABBREVIATE
												| posix1e.TEXT_SOME_EFFECTIVE)
								),
								access_acl=stylize(ST_ACL,
											default_perm.to_any_text(
												separator=',',
												options=posix1e.TEXT_ABBREVIATE
												| posix1e.TEXT_SOME_EFFECTIVE)
								)
							),
							auto_answer=auto_answer):

					# Don't remove str() (see above).
					default_perm.applyto(str(dir_info.path),
											posix1e.ACL_TYPE_DEFAULT)

					logging.info(
							_(u'Applyed access ACL {access_acl} '
							'on {path}.').format(
								path=stylize(ST_PATH, dir_info.path),

								access_acl=stylize(ST_ACL,
										default_perm.to_any_text(
												separator=',',
												options=posix1e.TEXT_ABBREVIATE
												| posix1e.TEXT_SOME_EFFECTIVE)
								)
							)
						)
				else:
					all_went_ok = False
	else:
		# delete previus ACL perms in case of existance
		if has_extended_acl(dir_info.path):
			# if an ACL is present, this could be what is borking the Unix mode.
			# an ACL is present if it has a mask, else it is just standard posix
			# perms expressed in the ACL grammar. No mask == Not an ACL.

			if batch or logging.ask_for_repair(
							_('An ACL is present on {path}, '
							'but it should not.').format(
								path=stylize(ST_PATH, dir_info.path)),
							auto_answer=auto_answer):

				# if it is a directory we need to delete DEFAULT ACLs too
				if file_type is S_IFDIR:
					posix1e.ACL(text='').applyto(str(dir_info.path),
											posix1e.ACL_TYPE_DEFAULT)

					logging.info(_(u'Deleted default ACL from {path}.').format(
									path=stylize(ST_PATH, dir_info.path)))

				# delete ACCESS ACLs if it is a file or a directory
				posix1e.ACL(text='').applyto(str(dir_info.path),
					posix1e.ACL_TYPE_ACCESS)
				logging.info(_(u'Deleted access ACL from {path}.').format(
							path=stylize(ST_PATH, dir_info.path)))
			else:
				all_went_ok = False

		pathstat = os.lstat(dir_info.path)
		current_perm = pathstat.st_mode & 07777

		if current_perm != access_perm:

			if batch or logging.ask_for_repair(
							_(u'Invalid Unix mode for {path} '
							'(it is {current_mode} but '
							'should be {wanted_mode}).').format(
								path=stylize(ST_PATH, dir_info.path),
								current_mode=stylize(ST_BAD,
									perms2str(current_perm)),
								wanted_mode=stylize(ST_ACL,
									perms2str(access_perm))),
							auto_answer=auto_answer):

					os.chmod(dir_info.path, access_perm)

					logging.info(_(u'Applyed perms {wanted_mode} '
						'on {path}.').format(
							wanted_mode=stylize(ST_ACL, perms2str(access_perm)),
							path=stylize(ST_PATH, dir_info.path)))
			else:
				all_went_ok = False

	assert ltrace('fsapi', '< check_perms()')
def check_uid_and_gid(path, uid=-1, gid=1, batch=None, auto_answer=None,
	full_display=True):
	""" function that check the uid and gid of a file or a dir. """
	if full_display:
		logging.progress(_(u'Checking posix uid/gid/perms of %s.') %
								stylize(ST_PATH, path))
	try:
		pathstat = os.lstat(path)
	except OSError, e:
		if e.errno == 2:
			# causes of this error:
			#     - this is a race condition: the dir/file has been deleted between the minifind()
			#       and the check_*() call. Don't blow out on this.
			#     - when we explicitely want to check a path which does not exist because it has not
			#       been created yet (eg: ~/.dmrc on a brand new user account).
			return True
		else:
			raise e

	# if one or both of the uid or gid are empty, don't check it, use the
	# current one present in the file meta-data.
	if uid == -1:
		uid = pathstat.st_uid
		try:
			desired_login = LMC.users[uid]['login']
		except KeyError:
			desired_login = 'root'
			uid = 0
	else:
		try:
			desired_login = LMC.users.uid_to_login(uid)
		except exceptions.DoesntExistsException:
			desired_login = 'root'
			uid = 0

	if gid == -1:
		gid = pathstat.st_gid
		try:
			desired_group = LMC.groups[gid]['name']
		except KeyError:
			desired_group = gid
	else:
		desired_group = LMC.groups.gid_to_name(gid)

	if pathstat.st_uid != uid or pathstat.st_gid != gid:

		try:
			current_login = LMC.users[pathstat.st_uid]['login']
		except KeyError:
			current_login = pathstat.st_uid

		try:
			current_group = LMC.groups[pathstat.st_gid]['name']
		except KeyError:
			current_group = pathstat.st_gid

		if batch or logging.ask_for_repair(_(u'Invalid ownership for {path} '
						'(it is {current_user}:{current_group} '
						'but should be {wanted_user}:{wanted_group}).').format(
							path=stylize(ST_PATH, path),
							current_user=stylize(ST_BAD, current_login),
							current_group=stylize(ST_BAD, current_group),
							wanted_user=stylize(ST_UGID, desired_login),
							wanted_group=stylize(ST_UGID, desired_group)),
						auto_answer=auto_answer):

			os.chown(path, uid, gid)

			logging.info(_(u'Changed owner of {path} from '
				'{current_user}:{current_group} '
				'to {wanted_user}:{wanted_group}').format(
					path=stylize(ST_PATH, path),
					current_user=stylize(ST_BAD, current_login),
					current_group=stylize(ST_BAD, current_group),
					wanted_user=stylize(ST_UGID, desired_login),
					wanted_group=stylize(ST_UGID, desired_group)
				))
		else:
			all_went_ok = False
def make_symlink(link_src, link_dst, batch=False, auto_answer=None):
	"""Try to make a symlink cleverly."""
	try:
		os.symlink(link_src, link_dst)
		logging.info(_(u'Created symlink {link}, pointing to {orig}.').format(
							link=stylize(ST_LINK, link_dst),
							orig=stylize(ST_PATH, link_src)))
	except OSError, e:
		if e.errno == 17:
			# 17 == file exists
			if os.path.islink(link_dst):
				try:
					read_link = os.path.abspath(os.readlink(link_dst))

					if read_link != link_src:
						if os.path.exists(read_link):
							if batch or logging.ask_for_repair(
											_('A symlink {link} '
											'already exists, but points '
											'to {dest}, instead of {good}. '
											'Correct it?').format(
											link=stylize(ST_LINK, link_dst),
											dest=stylize(ST_PATH, read_link),
											good=stylize(ST_PATH, link_src)
										),
										auto_answer=auto_answer):

								os.unlink(link_dst)
								os.symlink(link_src, link_dst)

								logging.info(_(u'Overwritten symlink {link} '
										'with destination {good} '
										'instead of {dest}.').format(
										link=stylize(ST_LINK, link_dst),
										good=stylize(ST_PATH, link_src),
										dest=stylize(ST_PATH, read_link))
									)
							else:
								raise exceptions.LicornRuntimeException(
									"Can't create symlink %s to %s!" % (
										link_dst, link_src))
						else:
							# TODO: should we ask the question ? This isn't
							# really needed, as the link is broken.
							# Just replace it and don't bother the administrator.
							logging.info(_(u'Symlink {link} is currently '
									'broken, pointing to non-existing '
									'target {dest}); making it point '
									'to {good}.').format(
										link=stylize(ST_LINK, link_dst),
										dest=stylize(ST_PATH, read_link),
										good=stylize(ST_PATH, link_src)
									)
								)
							os.unlink(link_dst)
							os.symlink(link_src, link_dst)

				except OSError, e:
					if e.errno == 2:
						# no such file or directory, link has disapeared…
						os.symlink(link_src, link_dst)
						logging.info(_(u'Repaired vanished symlink %s.') %
							stylize(ST_LINK, link_dst))
			else:

				# TODO / WARNING: we need to investigate a bit more: if current
				# link_src is a file, overwriting it could be very bad (e.g.
				# user could loose a document). This is the same for a
				# directory, modulo the user could loose much more than just a
				# document. We should scan the dir and replace it only if empty
				# (idem for the file), and rename it (thus find a unique name,
				# like 'the file.autosave.XXXXXX.txt' where XXXXXX is a random
				# string…)

				if batch or logging.ask_for_repair(_(u'{path} already '
								'exists but it is not a symlink, thus '
								'it does not point to {dest}. '
								' Replace it with a correct symlink?').format(
									link=stylize(ST_LINK, link_dst),
									dest=stylize(ST_PATH, link_src)
								),
								auto_answer=auto_answer):

					pathname, ext = os.path.splitext(link_dst)
					newname = (pathname + _(' (%s conflict)') % time.strftime(
							_(u'%d %m %Y at %H:%M:%S')) + ext)
					os.rename(link_dst, newname)
					os.symlink(link_src, link_dst)

					logging.info(_(u'Renamed {link} to {newname} '
							'and replaced it by a symlink '
							'pointing to {dest}.').format(
								link=stylize(ST_LINK, link_dst),
								newname=stylize(ST_PATH, newname),
								dest=stylize(ST_PATH, link_src)
							)
						)
				else:
					raise exceptions.LicornRuntimeException(_(u'While making '
						'symlink to {dest}, the destination {link} '
						'already exists and is not a link.').format(
							dest=link_src, link=link_dst))

# various unordered functions, which still need to find a more elegant home.

def has_extended_acl(pathname):
	# return True if the posix1e representation of pathname's ACL has a MASK.
	for acl_entry in posix1e.ACL(file = pathname):
		if acl_entry.tag_type is posix1e.ACL_MASK:
			return True
	return False

# use pylibacl 0.4.0 accelerated C function if possible.
if hasattr(posix1e, 'HAS_EXTENDED_CHECK'):
	if posix1e.HAS_EXTENDED_CHECK:
		has_extended_acl = posix1e.has_extended

def backup_file(filename):
	""" make a backup of a given file. """
	bckp_ext='.licorn.bak'
	backup_name = filename + bckp_ext
	open(backup_name, 'w').write(open(filename).read())
	os.chmod(backup_name, os.lstat(filename).st_mode)
	logging.progress(_(u'Backed up {orig} as {backup}.').format(
			orig=stylize(ST_PATH, filename),
			backup=stylize(ST_COMMENT, backup_name)))
def is_backup_file(filename):
	"""Return true if file is a backup file (~,.bak,…)."""
	if filename[-1] == '~':
		return True
	if filename[-4:] in ('.bak', '.old', '.swp'):
		return True
	return False
def get_file_encoding(filename):
	""" Try to find the encoding of a given file.
		(python's file.encoding is not very reliable, or I don't use use it like I should).

		TODO: use python mime module to do this ?
	"""

	# file -b: brief (the file name is not printed)
	encoding = process.execute(['file', '-b', filename])[0][:-1].split(' ')

	if encoding[0] == "ISO-8859":
		ret_encoding = "ISO-8859-15"
	elif encoding[0] == "UTF-8" and encoding[1] == "Unicode":
		ret_encoding = "UTF-8"
	elif encoding[0] == "Non-ISO" and encoding[1] == "extended-ASCII":
		# FIXME: find the correct encoding when a file comme from Windows ?
		ret_encoding = None
	else:
		ret_encoding = None

	return ret_encoding
def execbits2str(filename):
	"""Find if a file has executable bits and return (only) then as a list of strings, used later to build an ACL permission string.

		TODO: as these exec perms are used for ACLs only, should not we avoid testing setuid and setgid bits ? what does setguid means in a posix1e ACL ?
	"""

	fileperms = os.lstat(filename).st_mode & 07777
	execperms = []

	# exec bit for owner ?
	if fileperms & S_IXUSR:
		execperms.append('x')
	else:
		execperms.append('-')

	# exec bit for group ?
	if fileperms & S_IXGRP:
		execperms.append('x')
	else:
		execperms.append('-')

	# skip exec bit for other, not used in our ACLs.

	return execperms
def perms2str(perms, acl_form = False):
	""" Convert an int mode to a readable string like "ls" does.  """

	string = ''

	# USER

	if acl_form:
		string += "user::"

	if perms & S_IRUSR:
		string += 'r'
	else:
		string += '-'

	if perms & S_IWUSR:
		string += 'w'
	else:
		string += '-'

	if perms & S_IXUSR:
		if perms & S_ISUID:
			string += 's'
		else:
			string += 'x'
	else:
		if perms & S_ISUID:
			string += 'S'
		else:
			string += '-'

	if acl_form:
		string += "\ngroup::"

	# GROUP

	if perms & S_IRGRP:
		string += 'r'
	else:
		string += '-'

	if perms & S_IWGRP:
		string += 'w'
	else:
		string += '-'

	if perms & S_IXGRP:
		if perms & S_ISGID:
			string += 's'
		else:
			string += 'x'
	else:
		if perms & S_ISGID:
			string += 'S'
		else:
			string += '-'

	if acl_form:
		string += "\nother::"

	# OTHER

	if perms & S_IROTH:
		string += 'r'
	else:
		string += '-'

	if perms & S_IWOTH:
		string += 'w'
	else:
		string += '-'

	if perms & S_IXOTH:
		if perms & S_ISVTX:
			string += 't'
		else:
			string += 'x'
	else:
		if perms & S_ISVTX:
			string += 'T'
		else:
			string += '-'

	if acl_form:
		string += "\n"

	return string
def touch(fname, times=None):
	""" this touch reimplementation comes from
	`http://stackoverflow.com/questions/1158076/implement-touch-using-python`_
	and I find it great.
	"""
	with file(fname, 'a'):
		os.utime(fname, times)
