# -*- coding: utf-8 -*-
"""
Licorn® WMI - users views

:copyright:
	* 2008-2011 Olivier Cortès <olive@deep-ocean.net>
	* 2010-2011 META IT - Olivier Cortès <oc@meta-it.fr>
	* 2011 Robin Lucbernet <robinlucbernet@gmail.com>
	* 2012 Olivier Cortès <olive@licorn.org>
:license: GNU GPL version 2
"""

import os, time, base64, tempfile, crack
from threading import current_thread

from django.shortcuts               import *
from django.template.loader         import render_to_string
from django.utils.encoding          import smart_str
from django.utils.translation       import ugettext_lazy as _
from django.core.servers.basehttp   import FileWrapper
from django.contrib.auth.decorators import login_required

from licorn.foundations           import exceptions, logging, settings
from licorn.foundations           import hlstr, pyutils
from licorn.foundations.base      import Enumeration, LicornConfigObject
from licorn.foundations.constants import filters, relation
from licorn.foundations.ltrace    import *
from licorn.foundations.ltraces   import *

from licorn.core                      import LMC
from licorn.interfaces.wmi.libs       import decorators, utils, perms_decorators

# FIXME: OLD!! MOVE FUNCTIONS to new interfaces.wmi.libs.utils.
from licorn.interfaces.wmi.libs                import old_utils as w
from licorn.interfaces.wmi.libs.old_decorators import check_users

from licorn.interfaces.wmi.app import wmi_event_app

from forms import UserForm, SkelInput, ImportForm

@login_required
def message(request, part, uid=None, *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	if uid != None:
		user = utils.select('users', [ uid ])[0]

	if part == 'delete':
		html = render_to_string('users/delete_message.html', {
			'user_login'  : user.login,
			'archive_dir' : settings.home_archive_dir,
			'admin_group' : settings.defaults.admin_group,
			})

	elif part == 'lock':
		is_member_remote = False
		remote_group = ''
		# TODO !
		#print utils.select('extensions', all=True)

		#if 'openssh' in LMC.extensions.keys() and user.login in LMC.groups.by_name(
		#	name=LMC.extensions.openssh.group).members:
		#		is_member_remote = True
		#		remote_group = LMC.extensions.openssh.group

		html = render_to_string('users/lock_message.html', {
			'user_login'       : user.login,
			'is_member_remote' : is_member_remote,
			'gnu_acr'          : w.acr('GNU'),
			'ssh_acr'          : w.acr('SSH'),
			'rsa_acr'          : w.acr('RSA'),
			'dsa_acr'          : w.acr('DSA'),
			'remote_group'     : remote_group})

	elif part == 'skel':
		html = render_to_string('users/skel_message.html', {
				'complete_template' : True,
				'user_login'        : user.login,
				'skel_input'        : SkelInput(class_name='skel_to_apply')
			})

	elif part == 'massive_skel':
		html = render_to_string('users/skel_message.html', {
				'complete_template' : False,
				'skel_input'        : SkelInput(class_name='skel_to_apply')
			})

	return HttpResponse(html)

@login_required
@perms_decorators.check_users('mod')
def mod(request, uid, action, value, *args, **kwargs):
	""" edit the gecos of the user """

	assert ltrace_func(TRACE_DJANGO)

	user = utils.select('users', [ uid ])[0]

	def mod_groups(group_id, rel_id):
		# /mod/user_id/groups/group_id/rel_id

		group = utils.select('groups', [ group_id ])[0]
		if user.is_standard:
			g_group = group.guest_group
			r_group = group.responsible_group

		if rel_id == relation.MEMBER:
			group.add_Users(users_to_add=[user.uidNumber], force=True)

		elif rel_id == relation.GUEST:
			g_group.add_Users(users_to_add=[user.uidNumber], force=True)

		elif rel_id == relation.RESPONSIBLE:
			r_group.add_Users(users_to_add=[user.uidNumber], force=True)

		else:
			# the user has to be deleted, but from standard group or from helpers ?
			if group.get_relationship(user.uidNumber) == relation.GUEST:
				g_group.del_Users(users_to_del=[user.uidNumber])

			elif group.get_relationship(user.uidNumber) == relation.RESPONSIBLE:
				r_group.del_Users(users_to_del=[user.uidNumber])

			elif group.get_relationship(user.uidNumber) == relation.MEMBER:
				group.del_Users(users_to_del=[user.uidNumber])

	if action == 'gecos':
		if value != user.gecos:
			user.gecos = value

	elif action == 'password':
		user.password = value

	elif action == 'shell':
		if value != user.loginShell:
			user.loginShell = value

	elif action == 'groups':
		mod_groups(*[ int(x) for x in value.split('/')])

	elif action == 'skel':
		user.apply_skel(value)

	elif action == 'lock':
		user.locked = True

	elif action == 'unlock':
		user.locked = False

	# updating the web page is done in the event handler, via the push stream.
	return HttpResponse('MOD DONE.')

@login_required
@perms_decorators.check_users('delete')
def delete(request, uid, no_archive, *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	# remote:
	#LMC.rwi.generic_controller_method_call('users', 'del_User',
	#					user=int(uid), no_archive=bool(no_archive))

	# local:
	LMC.users.del_User(user=int(uid), no_archive=bool(no_archive))

	return HttpResponse('DONE.')

@login_required
def massive(request, uids, action, *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	if action == 'delete':
		for uid in uids.split(','):
			delete(request, uid=int(uid), no_archive=bool(kwargs.get('no_archive', False)))

	if action == 'skel':
		for uid in uids.split(','):
			LMC.users.by_uid(int(uid)).apply_skel(kwargs.get('skel'))

	if action == 'export':
		#TODO
		pass
	return HttpResponse('MASSIVE DONE.')

@login_required
def create(request, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	if request.method == 'POST':

		gresolver = LMC.groups.by_gid

		groups = [ int(g) for g in request.POST.getlist('member_groups') if g != '' ]

		groups.extend(gresolver(int(gid)).guest_group.gidNumber
				for gid in request.POST.getlist('guest_groups') if gid != '')

		groups.extend(gresolver(int(gid)).responsible_group.gidNumber
				for gid in request.POST.getlist('resp_groups') if gid != '')

		lprint(groups)

		profile     = LMC.profiles[
									int(w.my_unquote(request.POST['profile']))
								]
		shell       = request.POST['shell']
		gecos       = w.my_unquote(request.POST['gecos'])
		login       = w.my_unquote(request.POST['login'])

		# XXX: why not unquote the password too ?
		password    = request.POST['password']

		try:
			LMC.users.add_User(
						login=login if login != '' else None,
						gecos=gecos if gecos != '' else None,
						password=password,
						in_groups=groups,
						shell=LMC.configuration.users.default_shell
										if shell is None else shell,
						profile=profile)

		except Exception, e:
			wmi_event_app.queue(request).put(notify(_('Unable to add '
									'user {0}: {1}.').format(login, e)))

	return HttpResponse('DONE.')

# TODO:
@login_required
def massive_import(uri, http_user, filename, firstname_col, lastname_col,
													group_col, **kwargs):
	assert ltrace_func(TRACE_DJANGO)

	pass

@login_required
def user(request, uid=None, login= None, action='edit', *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	try:
		# remote:
		#user = utils.select('users', [ uid ])[0]

		# local:
		user = LMC.users.by_uid(int(uid))

	except:
		try:
			# remote:
			#user = utils.select('users', [ login ])[0]

			# local:
			user = LMC.users.by_login(login)

		except:
			user = None


	if action=='edit':
		edit_mod = True
		title    = _('Edit user {0}').format(user.login)
		action   = 'edit'
		user_id  = user.uidNumber
	else:
		edit_mod = False
		title    = _('Add new user')
		action   = 'new'
		user_id  = ''

	f = UserForm(edit_mod, user)

	groups_list = [ (_('Standard groups'),{
					'user': user,
					'name': 'standard',
					'groups' : utils.select("groups", default_selection=filters.STANDARD)
				}),
				(_('Privileged groups'), {
					'user': user,
					'name': 'privileged',
					'groups' : utils.select("groups", default_selection=filters.PRIVILEGED)
				}) ]

	if request.user.is_superuser:
		groups_list.append( ( _('System groups') ,  {
			'user': user,
			'name': 'system',
			'groups' : [ group for group in
				utils.select("groups", default_selection=filters.SYSTEM)
					if not group.is_helper and not group.is_privilege ]
		}))

	_dict = {
				'user_uid'              : user_id,
				'action'                : action,
				'edit_mod'              : edit_mod,
				'title'                 : title,
				'form'                  : f,
				'groups_lists'          : groups_list
			}

	if request.is_ajax():
		return render(request, 'users/user.html', _dict)

	else:
		_dict.update({
				'users_list'            : utils.select('users', default_selection=filters.STANDARD),
				'system_users_list'     : utils.select('users', default_selection=filters.SYSTEM)
			})

		return render(request, 'users/user_template.html', _dict)

@login_required
def view(request, uid=None, login=None, *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	if uid != None:
		user = utils.select('users', include_id_lists=[(uid, 'by_uid')])[0]

	elif login != None:
		user = utils.select('users', include_id_lists=[(login, 'by_login')])[0]

	try:
		profile = user.primaryGroup.profile.name

	except Exception:
		profile = _("Standard account")

	resps     = []
	guests    = []
	stdgroups = []
	privs     = []
	sysgroups = []

	for group in user.groups:
		if group.is_responsible:
			resps.append(group.standard_group)

		elif group.is_guest:
			guests.append(group.standard_group)

		elif group.is_standard:
			stdgroups.append(group)

		elif group.is_privilege:
			privs.append(group)

		else:
			sysgroups.append(group)

	lists = [
				{
					'title'  : _('Responsibilities'),
					'kind'   : _('responsible'),
					'groups' : resps
				},
				{
					'title'  : _('Memberships'),
					'kind'   : _('member'),
					'groups' : stdgroups
				},
				{
					'title'  : _('Invitations'),
					'kind'   : _('guest'),
					'groups' : guests
				},
				{
					'title'  : _('Privileges'),
					'kind'   : _('privileged member'),
					'groups' : privs
				},
				{
					'title'  : _('Other system groups'),
					'kind'   : _('system member'),
					'groups' : sysgroups
				},

		]

	# TODO: reactivate the extensions methods
	#
	#exts_wmi_group_meths = [ ext._wmi_group_data
	#							for ext in LMC.extensions
	#							if 'groups' in ext.controllers_compat
	#							and hasattr(ext, '_wmi_group_data')
	#						]
	exts_wmi_group_meths = []

	colspan = 2 + len(exts_wmi_group_meths)

	#extensions_data='\n'.join('<tr><td><strong>%s</strong></td>'
	#	'<td class="not_modifiable">%s</td></tr>\n'
	#		% ext._wmi_user_data(user, hostname=kwargs['wmi_hostname'])
	#			for ext in LMC.extensions
	#				if 'users' in ext.controllers_compat
	#					and hasattr(ext, '_wmi_user_data'))
	extensions_data = ''

	_dict = {
				'user'             : user,
				'colspan'          : colspan,
				'extensions_data'  : extensions_data,
				'lists'            : lists,
			}
	if request.is_ajax():
		return render(request, 'users/view.html', _dict)

	else:
		_dict.update({
				'users_list'        : utils.select('users', default_selection=filters.STANDARD),
				'system_users_list' : utils.select('users', default_selection=filters.SYSTEM),
				'is_super_user'     : request.user.is_superuser
			})
		return render(request, 'users/view_template.html', _dict)

@login_required
def upload_file(request, *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	if request.method == 'POST':
		csv_file = request.FILES['file']

		csv_handler, csv_filename = tempfile.mkstemp()

		destination = open(csv_filename, 'wb+')
		t = ''
		for chunk in csv_file.chunks():
			destination.write(chunk)
			t += chunk
		destination.close()
		#lprint(destination)
		return HttpResponse(csv_filename)

@login_required
def import_download(request, import_id, *args, **kwargs):
	""" http://djangosnippets.org/snippets/365/ """

	assert ltrace_func(TRACE_DJANGO)

	filename = os.path.join(settings.home_archive_dir, import_id)
	wrapper = FileWrapper(file(filename))
	response = HttpResponse(wrapper, content_type='text/plain')
	response['Content-Length'] = os.path.getsize(filename)
	response['Content-Disposition'] = 'attachment; filename={0}'.format(import_id)
	return response

@login_required
def import_view(request, confirm='', *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	if request.method == 'POST':

		opts                = LicornConfigObject()
		opts.filename       = request.POST['csv_filepath']
		opts.profile        = request.POST['profile']
		opts.confirm_import = bool(confirm)
		opts.no_sync        = False
		opts.separator      = ';'
		opts.lastname_col   = int(request.POST['lastname']) \
								if request.POST['lastname'] != '' else None
		opts.firstname_col  = int(request.POST['firstname']) \
								if request.POST['firstname'] != '' else None
		opts.group_col      = int(request.POST['group']) \
								if request.POST['group'] != '' else None
		opts.login_col      = int(request.POST['login']) \
								if request.POST['login'] != '' else None
		opts.password_col   = int(request.POST['password']) \
								if request.POST['password'] != '' else None

		# Execute the import in background in order to return instantly
		# remote:
		#LMC.rwi.import_users(opts=opts, background=True)

		# local:
		from licorn.daemon.main import daemon
		daemon.rwi.import_users(opts=opts, background=True)

		return HttpResponse('DONE.')

	else:
		form = ImportForm()

		if request.is_ajax():
			return render(request, '/users/import.html', {'form': form})

		else:
			return render(request, '/users/import_template.html', {'form': form})

@login_required
def main(request, sort="login", order="asc", select=None, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	users_list = utils.select('users', default_selection=filters.STANDARD)

	system_users_list = utils.select('users', default_selection=filters.SYSTEM)

	return render(request, 'users/index.html', {
			'users_list'        : users_list,
			'system_users_list' : system_users_list,
			'is_super_user'     : request.user.is_superuser,
		})

# ================================================================ Helper Views
#
# They are not protected because they are not security-sensitive, and
# could possibly help other processes / programs outside of Licorn®.

def check_pwd_strenght(request, pwd, *args, **kwargs):

	assert ltrace_func(TRACE_DJANGO)

	try:
		crack.FascistCheck(pwd)

	except ValueError, e:
		return HttpResponse(e)

	else:
		return HttpResponse(pwd)

def generate_pwd(request, *args, **kwargs):
	return HttpResponse(hlstr.generate_password())