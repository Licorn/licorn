#!/usr/bin/python -OO
# -*- coding: utf-8 -*-
"""
Licorn testsuite for licorn.core objects.

Copyright (C) 2007-2010 Olivier Cortès <oc@meta-it.fr>
Copyright (C) 2010 Robin Lucbernet <rl@meta-it.fr>

Licensed under the terms of the GNU GPL version 2.
"""

import sys, os, curses, re, hashlib, tempfile, termios, fcntl, struct, stat, shutil

from subprocess                import Popen, PIPE, STDOUT
from licorn.foundations        import pyutils, logging, exceptions, process, fsapi
from licorn.foundations.styles import *
from licorn.core.configuration import LicornConfiguration

configuration = LicornConfiguration()

if __debug__:
	PYTHON = [ 'python' ]
	verbose=True
else:
	PYTHON = [ 'python', '-OO' ]
	verbose=False

CLIPATH='../interfaces/cli'
ADD    = PYTHON + [ CLIPATH + '/add.py']
DEL = PYTHON + [ CLIPATH + '/del.py']
MOD = PYTHON + [ CLIPATH + '/mod.py']
GET = PYTHON + [ CLIPATH + '/get.py']
CHK  = PYTHON + [ CLIPATH + '/chk.py']

system_files = ( 'passwd', 'shadow', 'group', 'gshadow', 'adduser.conf',
				'login.defs', 'licorn/main.conf', 'licorn/group',
				'licorn/profiles.xml')

bkp_ext = 'licorn'

state_files = {
	'context':  'data/.ctx_status',
	'scenarii':	'data/.sce_status',
	'owner':    'data/.owner'
	}

from optparse import OptionParser
parser = OptionParser()
parser.add_option("-s", "--scenario", dest="scenario_number", type="int",
	help="start at this scenario number")
parser.add_option("-c", "--context", dest="context_number", type="int",
	help="start at this context number")
parser.add_option("-r", "--reload", action="store_true", dest="reload",
	help="reload testsuite. Start from beginning")
parser.add_option("-v", "--verbose", action="store_true", dest="verbose",
	default=False, help="display commands before executing them.")

(options, args) = parser.parse_args()

verbose = options.verbose

if os.getuid() != 0 or os.geteuid() != 0:

	cmd=[ 'licorn-testsuite' ]
	cmd.extend(sys.argv)

	open(state_files['owner'], 'w').write('%s,%s' % (os.getuid(), os.getgid()))

	if verbose:
		logging.notice(
			'Relauching ourselves with sudo to gain root privileges...')
		logging.info('execvp(sudo %s)' % cmd)

	os.execvp('sudo', cmd)

def save_state(num, state_type='scenarii'):
	open(state_files[state_type],'w').write('%d' % num)
def get_state(state_type='scenarii'):
	if os.path.exists(state_files[state_type]):
		 return int(open(state_files[state_type]).read())
	else:
		return 0
def clean_state_files():
	for state_type in state_files:
		if state_type == 'owner':
			continue
		os.unlink(state_files[state_type])

if options.scenario_number != None:
	save_state(options.scenario_number)
if options.context_number != None:
	save_state(options.context_number,state_type='context')
if options.reload == True:
	try:
		clean_state_files()
		logging.notice('State files deleted.')
	except (OSError, IOError), e:
		if e.errno != 2:
			raise e

missing_error=False
for binary in ( '/usr/bin/setfacl', '/usr/bin/attr', '/bin/chmod', '/bin/rm',
	'/usr/bin/touch', '/bin/chown', '/usr/bin/colordiff', '/usr/sbin/slapcat'):
	if not os.path.exists(binary):
		missing_error=True
		logging.warning('''%s does not exist on this system and is '''
			'''mandatory for this testsuite.''' % binary)

if missing_error:
	logging.error('Please install missing packages before continuing.')

curses.setupterm()
clear = curses.tigetstr('clear')
def clean_path_name(command):
	""" return a multo-OS friendly path for a given command."""
	return ('_'.join(command)).replace(
		'../', '').replace('./', '').replace('//','_').replace(
		'/','_').replace('>','_').replace('&', '_').replace(
		'`', '_').replace('\\','_').replace("'",'_').replace(
		'|','_').replace('^','_').replace('%', '_').replace(
		'(', '_').replace(')', '_').replace ('*', '_').replace(
		' ', '_').replace('__', '_')
def clear_term():
	sys.stdout.write(clear)
	sys.stdout.flush()
def term_size():
	#print '(rows, cols, x pixels, y pixels) =',
	return struct.unpack("HHHH",
		fcntl.ioctl(
			sys.stdout.fileno(),
			termios.TIOCGWINSZ,
			struct.pack("HHHH", 0, 0, 0, 0)
			)
		)
def cmdfmt(cmd, prefix=''):
	'''convert a sequence to a colorized string.'''
	return '%s%s' % (prefix, stylize(ST_NAME, small_cmd(cmd)))
def cmdfmt_big(cmd, prefix=''):
	'''convert a sequence to a colorized string.'''
	return '%s%s' % (prefix, stylize(ST_LOG, small_cmd(cmd)))
def small_cmd(cmd):
	return re.sub(r'((sudo|python|-OO) |\.\./interfaces/cli/|\.py\b)', r'', ' '.join(cmd))
def test_message(msg):
	""" display a message to stderr. """
	sys.stderr.write("%s>>> %s%s\n"
		% (colors[ST_LOG], msg, colors[ST_NO]) )
def log_and_exec (command, inverse_test=False, result_code=0, comment="",
	verb=verbose):
	"""Display a command, execute it, and exit if soemthing went wrong."""

	sys.stderr.write("%s>>> running %s%s%s\n" % (colors[ST_LOG],
		colors[ST_PATH], command, colors[ST_NO]))

	output, retcode = execute(command)
	must_exit = False

	#
	# TODO: implement a precise test on a precise exit value.
	# for example, when you try to add a group with an invalid name,
	# licorn-add should exit (e.g.) 34. We must test on this precise
	# value and not on != 0, because if something wrong but *other* than
	# errno 34 happened, we won't know it if we don't check carefully the
	# program output.
	#

	if inverse_test:
		if retcode != result_code:
			must_exit = True
	else:
		if retcode != 0:
			must_exit = True

	if must_exit:
		if inverse_test:
			test = ("	%s→ it should have failed with reason: %s%s%s\n"
				% (colors[ST_PATH], colors[ST_BAD],
					comment, colors[ST_NO]))
		else:
			test = ""

		sys.stderr.write("	%s→ return code of command: %s%d%s (expected: %d)%s\n%s	→ log follows:\n"
			% (	colors[ST_LOG], colors[ST_BAD],
				retcode, colors[ST_LOG], result_code,
				colors[ST_NO], test) )
		sys.stderr.write(output)
		sys.stderr.write(
			"The last command failed to execute, or return something wrong !\n")
		raise SystemExit(retcode)

	if verb:
		sys.stderr.write(output)
def execute(cmd, verbose=verbose):
	if verbose:
		logging.notice('running %s.' % ' '.join(cmd))
	p4 = Popen(cmd, shell=False,
		  stdin=PIPE, stdout=PIPE, stderr=STDOUT, close_fds=True)
	output = p4.stdout.read()
	retcode = p4.wait()
	if verbose:
		sys.stderr.write(output)
	return output, retcode
def strip_moving_data(output):
	""" strip dates from warnings and traces, else outputs and references
	always compare false ."""
	return re.sub(r'(\.\d\d\d\d\d\d\d\d-\d\d\d\d\d\d|\s\[\d\d\d\d/\d\d/\d\d\s\d\d:\d\d:\d\d\.\d\d\d\d\]\s)',
		r' [D/T] ',re.sub(r'(Autogenerated\spassword\sfor\suser\s.*:|Set\spassword\sfor\suser\s.*\sto)\s.*', r'\1 [Password]', output))
class ScenarioTest:
	counter = 0

	def __init__(self, cmds, context='std', descr=None):

		self.context = context

		self.sce_number = ScenarioTest.counter

		# we have to give a unique number to commands in case they are repeated.
		# this is quite common, to test commands twice (the second call should
		# fail in that case).
		self.cmd_counter = 0

		self.name = '%s%s%s%s%s' % (
			stylize(ST_NAME, 'Scenario #'),
			stylize(ST_OK, ScenarioTest.counter),
			stylize(ST_NAME, ' (%s)' % descr) if descr else '',
			stylize(ST_NAME, ', context '),
			stylize(ST_OK, self.context))

		ScenarioTest.counter += 1

		self.cmds = {}

		for cmd in cmds:
			self.cmds[self.cmd_counter] = cmd
			self.cmd_counter += 1

		self.hash = hashlib.sha1(self.name).hexdigest()
		self.base_path = 'data/scenarii/%s' % self.hash

	def SaveOutput(self, cmdnum, output, code):

		try:
			os.makedirs('%s/%s' % (self.base_path, cmdnum))
		except (OSError, IOError), e:
			if e.errno != 17:
				raise e

		open('%s/%s/cmdline.txt' % (self.base_path, cmdnum), 'w').write(
			' '.join(self.cmds[cmdnum]))
		open('%s/%s/out.txt' % (self.base_path, cmdnum), 'w').write(
			strip_moving_data(output))
		open('%s/%s/code.txt' % (self.base_path, cmdnum), 'w').write(str(code))
	def show_commands(self, highlight_num):
		""" output all commands, to get an history of the current scenario,
			and higlight the current one. """

		data = ''

		for cmdcounter in self.cmds:
			if cmdcounter < highlight_num:
				data += '	%s\n' % cmdfmt(self.cmds[cmdcounter],
					prefix='  ')
			elif cmdcounter == highlight_num:
				data += '	%s\n' % cmdfmt_big(self.cmds[cmdcounter],
					prefix='> ')
			elif cmdcounter > highlight_num:
				data += '	%s%s\n' % (
					cmdfmt(self.cmds[cmdcounter],
						prefix='  '),
					'\n	%s' % cmdfmt(u'[…]', prefix='  ') \
						if len(self.cmds) > cmdcounter+1 \
						else '')
				break

		return data
	def RunCommand(self, cmdnum, batch=False):

		if os.path.exists('%s/%s' % (self.base_path, cmdnum)):
			ref_output = open('%s/%s/out.txt' % (self.base_path, cmdnum)).read()
			ref_code = int(open(
				'%s/%s/code.txt' % (self.base_path, cmdnum)).read())

			output, retcode = execute(self.cmds[cmdnum])
			output = strip_moving_data(output)

			if retcode != ref_code or ref_output != output:

				clear_term()

				handle, tmpfilename = tempfile.mkstemp(
					prefix=clean_path_name(self.cmds[cmdnum]))
				open(tmpfilename, 'w').write(output)
				diff_output = process.execute(['diff', '-u',
					'%s/%s/out.txt' % (self.base_path, cmdnum),
					tmpfilename])[0]

				logging.warning(
					'''command #%s/%s failed (sce#%s, ctx %s). Retcode %s '''
					'''(ref %s).

%s

%s''' % (
					stylize(ST_OK, cmdnum+1), stylize(ST_OK, len(self.cmds)),
					stylize(ST_OK, self.sce_number),
					stylize(ST_OK, self.context),
					stylize(ST_BAD, retcode),
					stylize(ST_OK, ref_code),
					self.show_commands(highlight_num=cmdnum),
					diff_output))
				if batch or logging.ask_for_repair('''Should I keep the new '''
					'''return code and trace as reference for future runs?'''):
					self.SaveOutput(cmdnum, output, retcode)
				else:
					raise exceptions.LicornRuntimeException(
						'command "%s" failed.\nPath: %s.' % (
							cmdfmt(self.cmds[cmdnum]), '%s/%s/*' % (
								self.base_path, cmdnum)))
			else:
				logging.notice('command #%d "%s" completed successfully.' % (
				cmdnum+1, cmdfmt(self.cmds[cmdnum])))
		else:
			clear_term()

			output, retcode = execute(self.cmds[cmdnum])

			logging.notice('''no reference output for %s, cmd #%s/%s:'''
				'''\n\n%s\n\n%s'''
				% (
					self.name,
					stylize(ST_OK, cmdnum+1), stylize(ST_OK, len(self.cmds)),
					self.show_commands(highlight_num=cmdnum),
					strip_moving_data(output)))

			if logging.ask_for_repair('''is this output good to keep as '''
				'''reference for future runs?'''):
				# Save the output AND the return code for future
				# references and comparisons
				self.SaveOutput(cmdnum, output, retcode)
				# return them for current test, strip_dates to avoid an
				# immediate false negative.
				return (strip_moving_data(output), retcode)
			else:
				logging.error('''you MUST have a reference output; please '''
					'''fix code or rerun this test.''')
	def Run(self, options=[], batch=False, inverse_test=False):
		""" run each command of the scenario, in turn. """

		start_scenario = get_state()

		if self.sce_number < start_scenario:
			logging.notice('Skipping %s' % stylize(ST_NAME, self.name))
			return

		logging.notice('Running %s' % stylize(ST_NAME, self.name))

		for cmdnum in self.cmds:
			self.RunCommand(cmdnum)

		save_state(self.sce_number+1)

		logging.notice('End run %s' % stylize(ST_NAME, self.name))
	@staticmethod
	def reinit():
		ScenarioTest.counter = 0
		save_state(0)
def test_integrated_help():
	"""Test extensively argmarser contents and intergated help."""

	commands = []

	for program in (GET, ADD, MOD, DEL, CHK):

		commands.extend([
			program + ['-h'],
			program + ['--help']])

		if program == ADD:
			modes = [ 'user', 'users', 'group', 'profile' ]
		elif program == MOD:
			modes = [ 'configuration', 'user', 'group', 'profile' ]
		elif program == DEL:
			modes = [ 'user', 'group', 'groups', 'profile' ]
		elif program == GET:
			modes = [ 'user', 'users', 'passwd', 'group', 'groups', 'profiles',
				'configuration' ]
		elif program == CHK:
			modes = [ 'user', 'users', 'group', 'groups', 'profile', 'profiles',
				'configuration' ]

		for mode in modes:
			if program == GET and mode == 'configuration':
				commands.append(program + [ mode ])
			else:
				commands.extend([
					program + [ mode, '-h' ],
					program + [ mode, '--help' ]
					])

	ScenarioTest(commands, descr="integrated help").Run()
def test_get(context):
	"""Test GET a lot."""

	commands = []

	for category in [ 'config_dir', 'main_config_file',
		'extendedgroup_data_file' ]:
		for mode in [ '', '-s', '-b', '--bourne-shell', '-c', '--c-shell',
			'-p', '--php-code' ]:
			commands.append(GET + [ 'configuration', category, mode ])

	for category in [ 'skels', 'shells', 'backends' ]:
		commands.append(GET + [ 'config', category ])

	commands += [
		# users
		GET + [ "users" ],
		GET + [ "users", "--xml" ],
		GET + [ "users", "--long" ],
		GET + [ "users", "--long", "--xml" ],
		GET + [ "users", "--all" ],
		GET + [ "users", "--xml", "--all" ],
		GET + [ "users", "--all", "--long" ],
		GET + [ "users", "--xml", "--all", "--long" ],
		# groups
		GET + [ "groups" ],
		GET + [ "groups", "--xml" ],
		GET + [ "groups", "--long" ],
		GET + [ "groups", "--long", "--xml" ],
		GET + [ "groups", "--xml", "--all" ],
		GET + [ "groups", "--xml", "--all", "--long" ],
		GET + [ "groups", "--xml", "--guests" ],
		GET + [ "groups", "--xml", "--guests", "--long" ],
		GET + [ "groups", "--xml", "--responsibles" ],
		GET + [ "groups", "--xml", "--responsibles", "--long" ],
		GET + [ "groups", "--xml", "--privileged" ],
		GET + [ "groups", "--xml", "--privileged", "--long" ],
		# Profiles
		GET + [ "profiles" ],
		GET + [ "profiles", "--xml" ],
		]

	ScenarioTest(commands, context=context, descr="get tests").Run()
def test_find_new_indentifier():
	#test_message('''starting identifier routines tests.''')
	assert(pyutils.next_free([5,6,48,2,1,4], 5, 30) == 7)
	assert(pyutils.next_free([5,6,48,2,1,4], 1, 30) == 3)
	assert(pyutils.next_free([1,3], 1, 30) == 2)
	try:
		pyutils.next_free([1,2], 1, 2)
	except:
		assert(True) # good behaviour
	else:
		assert(False)

	assert(pyutils.next_free([1,2], 1, 30) == 3)
	assert(pyutils.next_free([1,2,4,5], 3, 5) == 3)
	#test_message('''identifier routines tests finished.''')
def test_regexes():
	""" Try funky strings to make regexes fail (they should not)."""

	# TODO: test regexes directly from defs in licorn.core....

	test_message('''starting regexes tests.''')
	regexes_commands = []

	# groups related
	regexes_commands.extend([
		ADD + [ 'group', "--name='_-  -_'" ],
		CHK + [ 'group', "--name='_-  -_'" ],
		ADD + [ 'group', "--name=';-)'" ],
		ADD + [ 'group', "--name='^_^'" ],
		ADD + [ 'group', "--name='le copain des groupes'" ],
		CHK + [ 'group', '-v', "--name='le copain des groupes'" ],
		ADD + [ 'group', "--name='héhéhé'" ],
		ADD + [ 'group', "--name='%(\`ls -la /etc/passwd\`)'" ],
		ADD + [ 'group', "--name='echo print coucou | python | nothing'" ],
		ADD + [ 'group', "--name='**/*-'" ],
		CHK + [ 'group', '-v', "--name='**/*-'" ]
		])

	# users related
	regexes_commands.extend([
		ADD + [ 'user', "--login='_-  -_'" ],
		ADD + [ 'user', "--login=';-)'" ],
		ADD + [ 'user', "--login='^_^'" ],
		ADD + [ 'user', "--login='le copain des utilisateurs'" ],
		ADD + [ 'user', "--login='héhéhé'" ],
		ADD + [ 'user', "--login='%(\`ls -la /etc/passwd\`)'" ],
		ADD + [ 'user', "--login='echo print coucou | python'" ],
		ADD + [ 'user', "--login='**/*-'" ]
		])

	ScenarioTest(regexes_commands).Run()

	# TODO: profiles ?

	test_message('''regexes tests finished.''')
def clean_system():
	""" Remove all stuff to make the system clean, testsuite-wise."""

	test_message('''cleaning system from previous runs.''')

	# delete them first in case of a previous failed testsuite run.
	# don't check exit codes or such, this will be done later.

	for argument in (
		['user', '''toto,tutu,tata,titi,test,utilisager.normal,''' \
			'''test.responsibilly,utilicateur.accentue,user_test,''' \
			'''grp-acl-user,utest_267,user_test2,user_test3,user_testsys,''' \
			'''user_testsys2,user_testsys3,user_test_DEBIAN''',
			 '--no-archive', '-v' ],
		['profile', '''--group=utilisagers,responsibilisateurs,'''
			'''profil_test''',
			'--del-users', '--no-archive', '-v' ],
		['group', '''test_users_A,test_users_B,groupeA,B-Group_Test,''' \
			'''groupe_a_skel,ACL_tests,MOD_tests,SYSTEM-test,SKEL-tests,''' \
			'''ARCHIVES-test,group_test,group_testsys,group_test2,''' \
			'''group_test3,GRP-ACL-test,gtest_267,group_test4,ce1,ce2,cm2,cp''',
			'--no-archive', '-v' ],
		['privilege', '--name=group_test', '-v' ]
		):

		execute(DEL + argument)

	for directory in (
		configuration.home_backup_dir,
		configuration.home_archive_dir
		):
		clean_dir_contents(directory)

	execute(ADD + ['group', '--system', 'acl,admins,remotessh,licorn-wmi'])

	test_message('''system cleaned from previous testsuite runs.''')
def clean_dir_contents(directory):
	""" Totally empty the contents of a given directory, the licorn way. """

	if verbose:
		test_message('Cleaning directory %s.' % directory)

	def delete_entry(entry):
		if verbose:
			logging.notice('Deleting %s.' % entry)

		if os.path.isdir(entry):
			shutil.rmtree(entry)
		else:
			os.unlink(entry)

	for entry in fsapi.minifind(directory, mindepth=1, maxdepth=2,
		type=stat.S_IFDIR|stat.S_IFREG):
		delete_entry(entry)

	if verbose:
		test_message('Cleaned directory %s.' % directory)

def make_backups(mode):
	"""Make backup of important system files before messing them up ;-) """

	# this is mandatory, else there could be some inconsistencies following
	# backend (de)activation, and backup comparison could fail (false-negative)
	# because of this.
	execute([ 'chk', 'config', '-avvb'])

	if mode == 'unix':
		for file in system_files:
			if os.path.exists('/etc/%s' % file):
				execute([ 'cp', '-f', '/etc/%s' % file,
					'/tmp/%s.bak.%s' % (file.replace('/', '_'), bkp_ext)])

	elif mode == 'ldap':
		execute([ 'slapcat', '-l', '/tmp/backup.1.ldif' ])

	else:
		logging.error('backup mode not understood.')

	test_message('''made backups of system config files.''')
def compare_delete_backups(mode):
	test_message('''comparing backups of system files after tests for side-effects alterations.''')

	if mode == 'unix':

		for file in system_files:
			if os.path.exists('/etc/%s' % file):
				log_and_exec([ '/usr/bin/colordiff', '/etc/%s' % file,
					'/tmp/%s.bak.%s' % (file.replace('/', '_'), bkp_ext)], False,
				comment="should not display any diff (system has been cleaned).",
				verb = True)
				execute([ 'rm', '/tmp/%s.bak.%s' % (file.replace('/', '_'), bkp_ext)])

	elif mode == 'ldap':
		execute([ 'slapcat', '-l', '/tmp/backup.2.ldif'])
		log_and_exec([ '/usr/bin/colordiff', '/tmp/backup.1.ldif', '/tmp/backup.2.ldif'],
			False,
			comment="should not display any diff (system has been cleaned).",
			verb = True)
		execute([ 'rm', '/tmp/backup.1.ldif', '/tmp/backup.2.ldif'])

	else:
		logging.error('backup mode not understood.')

	test_message('''system config files backup comparison finished successfully.''')
def test_groups(context):
	"""Test ADD/MOD/DEL on groups in various ways."""

	gname = 'groupeA'

	def chk_acls_cmds(group, subdir=None):
		return [ 'getfacl', '-R', '%s/%s/%s%s' % (
		configuration.defaults.home_base_path,
		configuration.groups.names['plural'],
		group,
		'/%s' % subdir if subdir else '') ]

	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname, '-v' ],
		chk_acls_cmds(gname),
		ADD + [ 'group', gname ],
		ADD + [ 'group', gname, '-v' ],
		DEL + [ 'group', gname ],
		DEL + [ 'group', gname ],
		],
		context=context,
		descr='''create group, verify ACL, '''
			'''try to create again in short mode, '''
			'''remove various components then check, '''
			'''then delete group and try to re-delete.'''
		).Run()

	gname = 'ACL_tests'

	# completeny remove the shared group dir and verify CHK repairs it.
	remove_group_cmds = [ "rm", "-vrf",
		"%s/%s/%s" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)
		]

	# idem with public_html shared subdir.
	remove_group_html_cmds = [ "rm", "-vrf",
		"%s/%s/%s/public_html" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)
		]

	# remove the posix ACLs and let CHK correct everything (after having
	# declared an error first with --auto-no).
	remove_group_acls_cmds = [ "setfacl", "-R", "-b",
		"%s/%s/%s" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)
		]

	# idem for public_html subdir.
	remove_group_html_acls_cmds = [ "setfacl", "-R", "-b",
		"%s/%s/%s/public_html" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)
		]

	bad_chown_group_cmds = [ 'chown', 'bin:daemon', '--changes',
		'%s/%s/%s/public_html' % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)
		]

	for break_acl_pre_cmd, chk_acl_cmd in (
		(remove_group_cmds, chk_acls_cmds(gname)),
		(remove_group_html_cmds, chk_acls_cmds(gname, 'public_html')),
		(remove_group_acls_cmds, chk_acls_cmds(gname)),
		(remove_group_html_acls_cmds, chk_acls_cmds(gname, 'public_html')),
		(bad_chown_group_cmds, chk_acls_cmds(gname))):

		for subopt_l1 in ('--auto-no', '--auto-yes', '-b'):
			for subopt_l2 in ('-v', '-ve', '-vv', '-vve'):

				ScenarioTest([
					ADD + [ 'group', gname, '-v' ],
					break_acl_pre_cmd,
					CHK + [ 'group', gname, subopt_l1, subopt_l2 ],
					chk_acl_cmd,
					DEL + [ 'group', gname, '-v', '--no-archive' ]
				],
				descr='''Various ACLs tests on groups, '''
					'''with various and combined options''',
				context=context).Run()

	gname = 'MOD_tests'

	ScenarioTest([
		ADD + [ 'group', gname, '-v' ],
		MOD + [ "group", "--name=%s" % gname, "--skel=/etc/doesntexist" ],
		MOD + [ "group", '--name=%s' % gname, '--not-permissive' ],
		chk_acls_cmds(gname),
		MOD + [ "group", "--name=%s" % gname, "--permissive" ],
		chk_acls_cmds(gname),
		MOD + [ "group", "--name=%s" % gname, "--permissive" ],
		DEL + [ 'group', gname, '-v' ]
		],
		descr='''modify with a non-existing profile, re-make not-permissive, '''
			'''make permissive.''',
		context=context).Run()

	gname = 'SYSTEM-test'

	ScenarioTest([
		ADD + [ 'group', "--name=%s" % gname, "--system" ],
		GET + [ 'groups' ],
		CHK + [ "group", "-v", "--name=%s" % gname ],
		DEL + ["group", "--name", gname],
		GET + [ 'groups' ],
		CHK + [ "group", "-v", "--name=%s" % gname ]
		],
		descr='''add --system, check, delete and recheck.''',
		context=context).Run()

	ScenarioTest([
		ADD + [ 'group', gname, '--gid=1520' ],
		GET + [ 'groups', '-la' ],
		DEL + ["group", gname ],
		GET + [ 'groups', '-la' ],
		ADD + [ 'group', gname, '--gid=15200', '--system' ],
		GET + [ 'groups', '-la' ],
		DEL + ["group", gname ],
		GET + [ 'groups', '-la' ],
		ADD + [ 'group', gname, '--gid=199', '--system' ],
		GET + [ 'groups', '-la' ],
		DEL + ["group", gname ],
		GET + [ 'groups', '-la' ]
		],
		context=context,
		descr='''ADD and DEL groups with fixed GIDs (ONE should fail).''').Run()

	gname = 'SKEL-tests'

	ScenarioTest([
		ADD + ["group", "--name=%s" % gname, "--skel=/etc/skel",
			"--description='Vive les skel'"],
		GET + [ 'groups', '-la' ],
		DEL + ["group", gname ],
		GET + [ 'groups', '-la' ]
		],
		descr='ADD group with specified skel and descr',
		context=context).Run()

	gname = 'ARCHIVES-test'

	clean_dir_contents(configuration.home_archive_dir)

	ScenarioTest([
		ADD + [ 'group', gname, '-v' ],
		[ 'touch', 		"%s/%s/%s/test.txt" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname) ],
		[ 'mkdir', "%s/%s/%s/testdir" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname) ],
		[ 'touch', "%s/%s/%s/testdir/testfile" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname) ],
		CHK + [ "group", "-vb", gname ],
		DEL + [ 'group', gname ],
		[ 'find', configuration.home_archive_dir ],
		[ 'getfacl', '-R', configuration.home_archive_dir ]
		],
		context=context,
		descr='''verify the --archive option of DEL group and check on '''
				'''shared dir contents, ensure #256 if off.'''
		).Run()

	clean_dir_contents(configuration.home_archive_dir)

	uname = 'user_test'
	gname = 'group_test'

	ScenarioTest([
		ADD + [ 'user', '--login=%s' % uname ],
		ADD + [ 'group', '--name=%s' % gname ],
		MOD + [ 'user', '--login=%s' % uname, '--add-groups=%s' % gname ],
		GET + [ 'groups' ],
		GET + [ 'users', '--long' ],
		DEL + [ 'group', '--name=%s' % gname ],
		GET + [ 'groups' ],
		GET + [ 'users', '--long' ],
		DEL + [ 'user', '--login=%s' % uname ]
		],
		context=context,
		descr='''check if a user is assigned to a specified group and if'''
				''' the user list is up to date when the group is deleted.'''
		).Run()

	#fix #259
	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname ],
		[ 'rm', '-vrf', "%s/%s/%s" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)],
		DEL + [ 'group', '--name=%s' % gname ],
		],
		context=context,
		descr='''check the message when a group (wich group dir has been '''
			'''deleted) is deleted (avoids #259).'''
		).Run()

	ScenarioTest([
		# should fail because gid 50 is "staff" on debian systems.
		ADD + [ 'group', '--name=%s' % gname, '--gid=50', '-v' ],
		GET + [ 'groups', '50' ],
		ADD + [ 'group', '--name=%s2' % gname, '--gid=15000', '-v' ],
		GET + [ 'groups', '15000' ],
		# should fail too, 150 is now taken.
		ADD + [ 'group', '--name=%s3' % gname, '--gid=15000', '-v' ],
		GET + [ 'groups', '15000' ],
		# should fail too, 150 is now taken.
		ADD + [ 'group', '--name=%s3' % gname, '--gid=15000',
			'--description=description', '-v' ],
		GET + [ 'groups', '15000' ],
		# should fail too, 150 is now taken.
		ADD + [ 'group', '--name=%s3' % gname, '--gid=15000', '--permissive',
			'-v' ],
		GET + [ 'groups', '15000' ],
		# should fail too, 150 is now taken.
		ADD + [ 'group', '--name=%s3' % gname, '--gid=15000', '--skel=/etc/skel',
			'-v' ],
		GET + [ 'groups', '15000' ],
		DEL + [ 'group', '--name=%s' % gname, '--no-archive' ],
		DEL + [ 'group', '%s2,%s3' % (gname, gname), '--no-archive' ],
		],
		context=context,
		descr='''check if add 2 groups with same GID produce an error (avoid #262)'''
		).Run()

	uname = 'grp-acl-user'
	gname = 'GRP-ACL-test'

	ScenarioTest([
		ADD + [ 'user', uname, '-v' ],
		ADD + [ 'group', gname, '-v' ],
		chk_acls_cmds(gname),
		[ 'chown', '-R', '-c', uname, "%s/%s/%s" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)],
		chk_acls_cmds(gname),
		CHK + [ 'group', gname, '-vb' ],
		chk_acls_cmds(gname),
		[ 'chgrp', '-R', '-c', 'audio', "%s/%s/%s" % (
			configuration.defaults.home_base_path,
			configuration.groups.names['plural'],
			gname)],
		chk_acls_cmds(gname),
		CHK + [ 'group', gname, '-vb' ],
		chk_acls_cmds(gname),
		DEL + [ 'group', gname ],
		DEL + [ 'user', uname ]
		],
		context=context,
		descr='''avoid #268.'''
		).Run()

	# don't test this one on other context than Unix. The related code is
	# generic (doesn't lie in backends) and the conditions to reproduce it are
	# quite difficult with LDAP. The result will be the same anyway.
	if context == 'unix' :

		uname = 'utest_267'
		gname = 'gtest_267'

		ScenarioTest([
			ADD + [ 'user', uname, '-v' ],
			ADD + [ 'group', gname, '-v' ],
			GET + [ 'users', '-l' ],
			GET + [ 'groups' ],
			# should do nothing
			CHK + [ 'groups', '-avb' ],
			CHK + [ 'groups', '-aveb' ],
			[ 'sed', '-i', '/etc/group',
				'-e', r's/^\(root:.*\)$/\1nouser/',
				'-e', r's/^\(audio:.*\)$/\1,foobar,%s/' % uname,
				'-e', r's/^\(%s:.*\)$/\1foobar,%s/' % (gname, uname),
				'-e', r's/^\(adm:.*\)$/\1,perenoel,%s,schproudleboy/' % uname ],
			# should display the dangling users
			GET + [ 'users', '-l' ],
			GET + [ 'groups' ],
			# should do nothing
			CHK + [ 'groups', '-avb' ],
			# should point the problems with dangling users
			CHK + [ 'groups', '-ave', '--auto-no' ],
			# should repair everything
			CHK + [ 'groups', '-aveb' ],
			GET + [ 'users', '-l' ],
			GET + [ 'groups' ],
			DEL + [ 'user', uname ],
			DEL + [ 'group', gname ]
			],
			context=context,
			descr='''avoid #267.'''
			).Run()

	#fix #297
	gname = 'group_test'
	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname, '--system', '-v' ],
		[ 'get', 'group', gname ],
		ADD + [ 'privileges', '--name=%s' % gname, '-v'],
		GET + [ 'privileges' ],
		DEL + [ 'group', '--name=%s' % gname, '-v' ],
		[ 'get', 'groups', gname ],
		GET + [ 'privileges' ]
		],
		context=context,
		descr='''Check if privilege list is up to date after group deletion'''
			''' (fix #297)'''
		).Run()

	#fix #293
	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname, '--gid=15200', '-v' ],
		# should fail (gid already in use)
		ADD + [ 'group', '--name=%s2' % gname, '--gid=15200', '-v' ],
		ADD + [ 'group', '--name=%ssys' % gname, '--gid=199', '--system',
			'-v' ],
		# should fail (gid already in use)
		ADD + [ 'group', '--name=%ssys2' % gname, '--gid=199', '--system',
			'-v' ],
		GET + [ 'groups', '-la' ],
		DEL + [ 'group', '--name=%s' % gname, '-v' ],
		DEL + [ 'group', '--name=%ssys' % gname, '-v' ],
		],
		context=context,
		descr='tests of groups commands with --gid option (fix #293)'
		).Run()

	# fix #286
	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname, '-v' ],
		GET + [ 'groups' ],
		GET + [ 'group', gname ],
		GET + [ 'group', gname, '-l' ],
		GET + [ 'group', '10000' ],
		GET + [ 'group', '10000' , '-l' ],
		#should fail (gid 11000 is not used)
		GET + [ 'group', '11000' ],
		GET + [ 'group', '11000' , '-l' ],
		GET + [ 'group', '%s,root' % gname ],
		GET + [ 'group', '0,root' ],
		DEL + [ 'group', '--name=%s' % gname, '-v' ],
		GET + [ 'group', 'root' ],
		GET + [ 'group', 'root', '-l' ],
		GET + [ 'group', '0' ],
		GET + [ 'group', '0', '-l' ],
		GET + [ 'group', '1' ],
		GET + [ 'group', '1', '-l' ],
		GET + [ 'groups' ]
		],
		context=context,
		descr='''test command get group <gid|group> (fix #286)'''
		).Run()

	# TODO: test other mod group arguments.

	# TODO:
	#FunctionnalTest(DEL + [ 'group', '--name', gname, '--del-users',
	#	'--no-archive'], context=context).Run()

	# RENAME IS NOT SUPPORTED YET !!
	#log_and_exec(MOD + " group --name=TestGroup_A --rename=leTestGroup_A/etc/power")

	# FIXME: get members of group for later verifications...
	#FunctionnalTest(DEL + ["group", "--name", gname, '--del-users',
	#	'--no-archive'],
	#	context=context).Run()
	# FIXME: verify deletion of groups + deletion of users...
	# FIXME: idem last group, verify users account were archived, shared dir ws archived.

	test_message('''groups related tests finished.''')
def test_users(context):

	def chk_acls_cmds(dir):
		return [ 'getfacl', '-R', dir ]

	uname = 'user_test'
	gname = 'group_test'

	"""Test ADD/MOD/DEL on user accounts in various ways."""

	ScenarioTest([
		ADD + [ 'user', '--login=%s' % uname, '-v' ],
		GET + [ 'users' ],
		#should fail (incorrect shell)
		MOD + [ 'user', '--login=%s' % uname, '--shell=/bin/badshell' ],
		GET + [ 'users' ],
		MOD + [ 'user', '--login=%s' % uname, '--shell=/bin/sh', '-v' ],
		GET + [ 'users' ],
		DEL + [ 'user', '--login=%s' % uname ],
		],
		context=context,
		descr='''check if a user can be modified with an incorrect shell and with a correct shell'''
		).Run()

	# fix #275
	ScenarioTest([
		GET + [ 'users', '-a' ],
		# should be OK
		ADD + [ 'user', '--login=%s' % uname, '--uid=1100' ],
		# should fail (already taken)
		ADD + [ 'user', '--login=%s2' % uname, '--uid=1100' ],
		# should fail, <1000 are for system accounts
		ADD + [ 'user', '--login=%s3' % uname, '--uid=200' ],
		# should be OK
		ADD + [ 'user', '--login=%ssys' % uname, '--system', '--uid=200' ],
		# should fail, >1000 are for standard accounts
		ADD + [ 'user', '--login=%ssys2' % uname, '--system', '--uid=1101' ],
		# should fail (already taken)
		ADD + [ 'user', '--login=%ssys3' % uname, '--system', '--uid=1' ],
		GET + [ 'users', '-a' ],
		DEL + [ 'user', '--login=%s' % uname ],
		DEL + [ 'user', '--login=%ssys' % uname ],
		],
		context=context,
		descr='''User tests with --uid option (avoid #273)'''
		).Run()

	# fix #286
	ScenarioTest([
		ADD + [ 'user', '--name=%s' % uname, '-v' ],
		GET + [ 'users' ],
		GET + [ 'user', uname ],
		GET + [ 'user', uname, '-l' ],
		GET + [ 'user', '1001' ],
		GET + [ 'user', '1001' , '-l' ],
		#should fail (uid 1100 is not used)
		GET + [ 'user', '1100' ],
		GET + [ 'user', '1100' , '-l' ],
		GET + [ 'users', '%s,root' % uname ],
		GET + [ 'users', '0,root' ],
		DEL + [ 'user', '--name=%s' % uname, '-v' ],
		GET + [ 'user', 'root' ],
		GET + [ 'user', 'root', '-l' ],
		GET + [ 'user', '0' ],
		GET + [ 'user', '0', '-l' ],
		GET + [ 'user', '1' ],
		GET + [ 'user', '1', '-l' ],
		GET + [ 'users' ],
		],
		context=context,
		descr='''test command get user <uid|user> (fix #286)'''
		).Run()

	#fix #284
	ScenarioTest([
		ADD + [ 'user', '--firstname=Robin', '--lastname=Lucbernet', '-v' ],
		ADD + [ 'user', '--firstname=Robin',
			'--lastname=LucbernetLucbernetLucbernetLucbernetLucbernetLucbernet',
			'-v' ],
		GET + [ 'users' ],
		DEL + [ 'user', '--login=robin.lucbernet' ],
		GET + [ 'users' ],
		],
		context=context,
		descr='test add user with --firstname and --lastname options (fix #284)'
		).Run()

	#fix #182
	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname, '-v' ],
		ADD + [ 'group', '--name=%s2' % gname, '-v' ],
		ADD + [ 'group', '--name=%s3' % gname, '-v' ],
		ADD + [ 'user', '--login=%s' % uname ],
		GET + [ 'user' , uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--add-groups=%s' % gname ],
		GET + [ 'user' , uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--add-groups=%s2,%s3' %
			(gname, gname), '--del-groups=%s' % gname,
			'--gecos=Robin Lucbernet', '--shell=/bin/sh'  ],
		GET + [ 'user', uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--add-groups=%s' % gname,
			'--del-groups=%s2,%s3' % (gname, gname) ],
		GET + [ 'user', uname, '--long' ],
		DEL + [ 'group', '--name=%s' % gname, '-v' ],
		DEL + [ 'group', '--name=%s2' % gname, '-v' ],
		DEL + [ 'group', '--name=%s3' % gname, '-v' ],
		DEL + [ 'user', '--login=%s' % uname, '-v' ],
		],
		context=context,
		descr='modify one or more parameters of a user (avoid #181 #197)'
		).Run()

	#fix #248
	ScenarioTest([
		# should work but doesn't record the specfied home dir
		# (non sytem user can't specify home dir)
		ADD + [ 'user', '--login=%s' % uname, '--home=/home/users/folder_test',
			'-v' ],
		GET + [ 'users', uname, '--long' ],
		ADD + [ 'user', '--login=%ssys' % uname, '--system',
			'--home=/home/folder_test', '-v' ],
		chk_acls_cmds('/home/folder_test'),
		GET + [ 'users', '-a', '%ssys' %uname, '--long' ],
		DEL + [ 'user', uname ],
		DEL + [ 'user', '%ssys' %uname ],
		],
		context=context,
		descr='check option --home of user command (fix #248)'
		).Run()

	ScenarioTest([
		ADD + [ 'user', '--login=%s' % uname ],
		GET + [ 'users', uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--lock', '-v' ],
		GET + [ 'users', uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--lock', '-v' ],
		GET + [ 'users', uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--unlock', '-v' ],
		GET + [ 'users', uname, '--long' ],
		MOD + [ 'user', '--login=%s' % uname, '--unlock', '-v' ],
		GET + [ 'users', uname, '--long' ],
		DEL + [ 'user', '--login=%s' % uname, '-v' ],
		],
		context=context,
		descr='''check messages of --lock and --unlock on mod user command
			and answer of get user --long (avoid #309)'''
		).Run()

	pname = 'profil_test'
	ScenarioTest([
		ADD + [ 'profile', '--name', 'Profil-Test-Name', '--group=profil_test',
			'-v' ],
		GET + [ 'profiles' ],
		ADD + [ 'user', '--login=%s' % uname, '--profile=%s' % pname, '-v' ],
		GET + [ 'users', uname, '--long' ],
		DEL + [ 'profile', '--group=%s' % pname, '--del-users', '-v' ],
		],
		context=context,
		descr='''Add a profil and check if it has been affected to a new user
			(avoid #277)'''
		).Run()

	fname = 'nibor'
	lname = 'tenrebcul'
	ScenarioTest([
		ADD + [ 'user', '--firstname=%s' % fname, '--lastname=%s' % lname, '-v' ],
		GET + [ 'users' ],
		ADD + [ 'user', '--firstname=%s' % fname, '--lastname=%s' % lname, '-v' ],
		GET + [ 'users' ],
		ADD + [ 'user', '--firstname=.', '--lastname=%s' % lname, '-v' ],
		GET + [ 'users' ],
		ADD + [ 'user', '--firstname=%s' % fname, '--lastname=.', '-v' ],
		GET + [ 'users' ],
		ADD + [ 'user', '--firstname=', '--lastname=', '-v' ],
		ADD + [ 'user', '--firstname=%s2' % fname, '--lastname=', '-v' ],
		ADD + [ 'user', '--firstname=%s2' % fname, '--lastname=', '-v' ],
		ADD + [ 'user', '--firstname=', '--lastname=%s2' % lname, '-v' ],
		ADD + [ 'user', '--firstname=', '--lastname=%s2' % lname, '-v' ],
		DEL + [ 'user', '--login=%s.%s' % (fname, lname), '-v' ],
		DEL + [ 'user', '--login=%s' % fname, '-v' ],
		DEL + [ 'user', '--login=%s' % lname, '-v' ],
		DEL + [ 'user', '--login=%s2' % lname, '-v' ],
		DEL + [ 'user', '--login=%s2' % fname, '-v' ],
		],
		context=context,
		descr='check add user with --firstname and --lastname (avoid #303 #305)'
		).Run()

	ScenarioTest([
		ADD + [ 'user', uname, '--password=toto', '-v' ],
		GET + [ 'users' ],
		ADD + [ 'user', '%s2' % uname, '--password=toto', '--force', '-v' ],
		GET + [ 'users' ],
		ADD + [ 'user', '%s3' % uname, '-S 32', '-v' ],
		GET + [ 'users' ],
		MOD + [ 'user', uname, '-P', '-S 128', '-v' ],
		MOD + [ 'user', uname, '-p totototo', '-v' ],
		DEL + [ 'user', uname, '-v' ],
		DEL + [ 'user', '%s2' % uname, '-v' ],
		DEL + [ 'user', '%s3' % uname, '-v' ],
		],
		context=context,
		descr='''various password change tests (avoid #184)'''
		).Run()

	""" # start of old test_users() commands
	log_and_exec(MOD + " user --login=utilisager.normal -v --add-groups test_users_A")
	log_and_exec(MOD + " user --login=utilisager.normal -v --add-groups test_users_B")

	# should produce nothing, because nothing is wrong.
	log_and_exec(CHK + " group -v --name test_users_B")

	os.system("rm ~utilisager.normal/test_users_A")

	# all must be OK, extended checks are not enabled, the program will not "see" the missing link.
	log_and_exec(CHK + " group -v --name test_users_A")

	# the link to group_A isn't here !
	log_and_exec(CHK + " group -vv --name test_users_A --extended --auto-no",
		True, 7, comment = "a user lacks a symlink.")
	log_and_exec(CHK + " group -vv --name test_users_A --extended --auto-yes")

	# the same check, but checking from users.py
	#os.system("rm ~utilisager.normal/test_users_A")
	#log_and_exec(CHK + " user --name utilisager.normal")
	# not yet implemented
	#log_and_exec(CHK + " user --name utilisager.normal --extended --auto-no", True, 7, comment="user lacks symlink")
	#log_and_exec(CHK + " user --name utilisager.normal --extended --auto-yes")

	# checking for Maildir repair capacity...
	if configuration.users.mailbox_type == configuration.MAIL_TYPE_HOME_MAILDIR:
		os.system("rm -rf ~utilisager.normal/" + configuration.users.mailbox)
		log_and_exec(CHK + " user -v --name utilisager.normal --auto-no",
			True, 7, comment="user lacks ~/" + configuration.users.mailbox)
		log_and_exec(CHK + " user -v --name utilisager.normal --auto-yes")

	os.system("touch ~utilisager.normal/.dmrc ; chmod 666  ~utilisager.normal/.dmrc")
	log_and_exec(CHK + " user -v --name utilisager.normal --auto-yes")

	os.system("mv -f ~utilisager.normal/test_users_B ~utilisager.normal/mon_groupe_B_préféré")
	# all must be ok, the link is just renamed...
	log_and_exec(CHK + " group -vv --name test_users_B --extended")

	# FIXME: verify the user can create things in shared group dirs.

	log_and_exec(MOD + " user --login=utilisager.normal --del-groups test_users_A")

	# should fail
	log_and_exec(MOD + " user --login=utilisager.normal --del-groups test_users_A",
		comment = "already not a member.")

	log_and_exec(ADD + " user --login test.responsibilly --profile responsibilisateurs")

	log_and_exec(MOD + " profile --group utilisagers --add-groups cdrom")
	log_and_exec(MOD + " profile --group utilisagers --add-groups cdrom,test_users_B")

	log_and_exec(MOD + " profile --group utilisagers --apply-groups")


	log_and_exec(MOD + " profile --group responsibilisateurs --add-groups plugdev,audio,test_users_A")
	log_and_exec(MOD + " profile --group responsibilisateurs --del-groups audio")

	log_and_exec(MOD + " profile --group responsibilisateurs --apply-groups")

	# clean the system
	log_and_exec(DEL + " user --login utilicateur.accentue")
	log_and_exec(DEL + " user --login utilisateur.accentuen2",
		True, 5, comment = "this user has *NOT* been created previously.")
	log_and_exec(DEL + " profile -vvv --group utilisagers --del-users --no-archive")

	#os.system(GET + " users")

	log_and_exec(DEL + " profile --group responsibilisateurs", True, 12,
		comment = "there are still some users in the pri group of this profile.")
	log_and_exec(DEL + " group --name=test_users_A --del-users --no-archive")

	log_and_exec(DEL + " user --login test.responsibilly")
	# this should work now that the last user has been deleted
	log_and_exec(DEL + " profile --group responsibilisateurs")
	log_and_exec(DEL + " group --name=test_users_B -vv")

	# already deleted before
	#log_and_exec(DEL + " user --login utilisager.normal")
	#log_and_exec(DEL + " user --login test.responsibilly")
	test_message('''users related tests finished.''')
	""" # end of old test_users() commands
def test_imports(context):
	pname = 'profil_test'
	ScenarioTest([
		ADD + [ 'profile', pname, '-v' ],
		ADD + [ 'users', '--filename=data/tests_users.csv',
			'--profile=%s' % pname ],
		ADD + [ 'users', '--filename=data/tests_users.csv',
			'--profile=%s' % pname, '--confirm-import' ],
		GET + [ 'users', '-l' ],
		GET + [ 'profiles' ],
		DEL + [ 'profiles', pname, '--del-users', '--no-archive' ],
		GET + [ 'users', '-l' ],
		GET + [ 'profiles' ],
		DEL + [ 'group', '--empty', '--no-archive', '-v' ],
		],
		context=context,
		descr='''test user import from csv file'''
		).Run()

	ScenarioTest([
		ADD + [ 'profile', pname, '-v' ],
		ADD + [ 'users', '--filename=data/tests_users.csv',
			'--profile=%s' % pname, '--lastname-column=0',
			'--firstname-column=1' ],
		ADD + [ 'users', '--filename=data/tests_users.csv',
			'--profile=%s' % pname, '--lastname-column=1',
			'--firstname-column=0', '--group-column=2',
			'--password-column=3', '--confirm-import', '-v' ],
		GET + [ 'users' ],
		DEL + [ 'profiles', pname, '--del-users', '--no-archive', '-v' ],
		DEL + [ 'group', 'cp,ce1,ce2,cm2', '--no-archive', '-v' ],
		],
		context=context,
		descr='''various test on user import'''
		).Run()

	"""
	os.system(DEL + " profile --group utilisagers         --del-users --no-archive")
	os.system(DEL + " profile --group responsibilisateurs --del-users --no-archive")
	log_and_exec(GET + " groups --empty | cut -d\":\" -f 1 | xargs -I% " + DEL + " group --name % --no-archive")

	log_and_exec(ADD + " profile --name Utilisagers         --group utilisagers                                                                 --comment 'profil normal créé pour la suite de tests utilisateurs'")
	log_and_exec(ADD + " profile --name Responsibilisateurs --group responsibilisateurs --groups cdrom,lpadmin,plugdev,audio,video,scanner,fuse --comment 'profil power user créé pour la suite de tests utilisateurs.'")

	log_and_exec(ADD + " users --filename ./testsuite/tests_users.csv", True,
		12, comment = "You should specify a profile")

	log_and_exec(ADD + " users --filename ./testsuite/tests_users.csv --profile utilisagers")
	log_and_exec(ADD + " users --filename ./testsuite/tests_users.csv --profile utilisagers --lastname-column 1 --firstname-column 0")
	log_and_exec("time " + ADD + " users --filename ./testsuite/tests_users.csv --profile utilisagers --lastname-column 1 --firstname-column 0 --confirm-import")
	log_and_exec(ADD + " users --filename ./testsuite/tests_resps.csv --profile responsibilisateurs")
	log_and_exec(ADD + " users --filename ./testsuite/tests_resps.csv --profile responsibilisateurs --lastname-column 1 --firstname-column 0")
	log_and_exec("time " + ADD + " users --filename ./testsuite/tests_resps.csv --profile responsibilisateurs --lastname-column 1 --firstname-column 0 --confirm-import")

	# activer les 2 lignes suivantes pour importer 860 utilisateurs de Latresne...
	log_and_exec(ADD + " users --filename ./testsuite/tests_users2.csv --profile utilisagers")
	log_and_exec("time " + ADD + " users --filename ./testsuite/tests_users2.csv --profile utilisagers --confirm-import")

	os.system("sleep 5")
	log_and_exec(DEL + " profile --group utilisagers         --del-users --no-archive")
	log_and_exec(DEL + " profile --group responsibilisateurs --del-users --no-archive")

	log_and_exec(GET + " groups --empty | cut -d\":\" -f 1 | xargs -I% " + DEL + " group --name % --no-archive")
	"""
def test_profiles(context):
	"""Test the applying feature of profiles."""

	pname = 'profil_test'
	gname = 'group_test'

	def chk_acls_cmd(user):
		return [ 'getfacl', '-R', '%s/%s' % (
		configuration.users.base_path,
		user) ]

	#fix #271 & #219
	ScenarioTest([
		ADD + [ 'profile', '--name=%s' % pname, '-v' ],
		GET + [ 'profiles' ],
		# should fail
		MOD + [ 'profile', '--name=%s' % pname, '--add-groups=%s' %
			pname, '-v' ],
		ADD + [ 'group', '--name=%s' % gname, '--system', '-v' ],
		ADD + [ 'group', '--name=%s2' % gname, '--system', '-v' ],
		ADD + [ 'group', '--name=%s3' % gname, '--system', '-v' ],
		GET + [ 'privileges' ],
		ADD + [ 'privilege', '--name=%s' % gname ],
		GET + [ 'groups', '-a' ],
		GET + [ 'privileges' ],
		MOD + [ 'profile', '--name=%s' % pname, '--add-groups=%s,%s2,%s3' %
			(gname, gname, gname), '-v' ],
		GET + [ 'profiles' ],
		DEL + [ 'group', '--name=%s' % gname, '-v' ],
		GET + [ 'profiles' ],
		MOD + [ 'profile', '--name=%s' % pname, '--del-groups=%s' % gname,
			'-v' ],
		MOD + [ 'profile', '--name=%s' % pname, '--del-groups=%s2,%s3' %
			(gname, gname), '-v' ],
		GET + [ 'profiles' ],
		DEL + [ 'group', '--name=%s2' % gname, '-v' ],
		DEL + [ 'group', '--name=%s3' % gname, '-v' ],
		# don't work with --name option
		DEL + [ 'profile', '--group=%s' % pname, '-v' ],
		DEL + [ 'privilege', '--name=%s' % gname, '-v' ],
		],
		context=context,
		descr='''scenario for ticket #271 - test some commands of mod profile'''
			''' --add-group and --del-groups & fix #219'''
		).Run()

	ScenarioTest([
		ADD + [ 'profile', '--name=%s' % pname, '-v' ],
		GET + [ 'profiles' ],
		#should fail
		MOD + [ 'profile', '--name=%s' % pname, '--add-groups=%s' %	gname,
			'-v' ],
		GET + [ 'profiles' ],
		DEL + [ 'profile', '--group=%s' % pname, '-v' ],
		],
		context=context,
		descr='check if a error occurs when a non-existing group is added to a profile'
		).Run()

	ScenarioTest([
		ADD + [ 'group', '--name=%s' % gname, '-v' ],
		#should fail (group already exists)
		ADD + [ 'profile', '--name=%s' % pname, '--group=%s' % gname,
			"--description='test_profil'", '-v' ],
		GET + [ 'profiles' ],
		#should fail (group is not a system group)
		ADD + [ 'profile', '--name=%s' % pname, '--group=%s' % gname,
			"--description='test_profil'", '-v', '--force-existing' ],
		GET + [ 'profiles' ],
		#should work (creating a new system group)
		ADD + [ 'group', '--name=%s2' % gname, '--system', '-v' ],
		ADD + [ 'profile', '--name=%s' % pname, '--group=%s2' % gname,
			"--description='test_profil'", '-v', '--force-existing' ],
		GET + [ 'profiles' ],
		DEL + [ 'profile', '--name=%s' % pname, '-v' ],
		DEL + [ 'group', gname, '-v' ],
		],
		context=context,
		descr='''Check if it is possible to force a profil group to a non '''
			'''system group (avoid #300 #320)'''
		).Run()

	ScenarioTest([
		ADD + [ 'profile', '--name=%s' % pname, '-v' ],
		GET + [ 'profiles' ],
		DEL + [ 'group', '--name=%s' % pname],
		GET + [ 'profiles' ],
		GET + [ 'group', pname ],
		DEL + [ 'profile', pname, '-v' ],
		GET + [ 'group', pname ],
		],
		context=context,
		descr='''when a profile group is deleted, an error message has to be '''
			'''presented (avoid #302)'''
		).Run()

	# profile scenario implemented with old commands (fix #292)
	ScenarioTest([
		ADD + [ 'profile', '--name=Utilisagers', '--group=utilisagers',
			'--description="testsuite profile, feel free to delete."', '-v' ],
		ADD + [ 'profile', '--name=Responsibilisateurs',
			'--group=responsibilisateurs',
			'--groups=cdrom,lpadmin,plugdev,audio,video,scanner,fuse',
			'--description="power testsuite profile, feel free to delete"',
			'-v' ],
		GET + [ 'profiles' ],
		ADD + [ 'user', '--name=toto', '--profile=Utilisagers' ],
		ADD + [ 'user', '--name=tutu', '--profile=Utilisagers' ],
		ADD + [ 'user', '--name=tata', '--profile=Responsibilisateurs' ],
		GET + [ 'user', '-l' ],
		ADD + [ 'group', gname, '-v' ],
		MOD + [ 'profile', '--group=utilisagers', '--add-groups=%s' % gname,
			'-v' ],
		GET + [ 'profiles' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-groups',
			'--to-groups=utilisagers', '-v' ],
		GET + [ 'groups', '--long' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-groups',
			'--to-members', '-v' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-skel',
			'--to-users=toto', '--auto-no' ],
		chk_acls_cmd('toto'),
		MOD + [ 'profile', '--group=utilisagers', '--apply-skel',
			'--to-users=toto', '--auto-yes'],
		chk_acls_cmd('toto'),
		MOD + [ 'profile', '--group=utilisagers', '--apply-skel',
			'--to-users=toto', '--batch', '-v' ],
		chk_acls_cmd('toto'),
		MOD + [ 'profile', '--group=utilisagers', '--apply-groups',
			'--to-users=toto', '--auto-no' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-groups',
			'--to-users=toto', '--auto-yes' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-groups',
			'--to-users=toto', '--batch', '-v' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-all',
			'--to-users=toto', '--auto-no' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-all',
			'--to-users=toto', '--auto-yes' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-all',
			'--to-users=toto', '--batch', '-v' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-all',  '--to-all',
			'--auto-no' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-all',  '--to-all',
			'--auto-yes' ],
		MOD + [ 'profile', '--group=utilisagers', '--apply-all',  '--to-all',
			'--batch', '-v' ],
		DEL + [ 'profile', '--group=responsibilisateurs', '--no-archive',
			'--del-users', '-v' ],
		DEL + [ 'profile', '--group=utilisagers', '--del-users',
			'--no-archive', '-v' ],
		DEL + [ 'group', gname ]
		],
		context=context,
		descr='''various tests on profiles (fix #292)'''
		).Run()
	""" # start of old test_profiles() commands
	test_message('''starting profiles related tests.''')
	log_and_exec(ADD + " profile --name Utilisagers --group utilisagers --comment 'profil normal créé pour la suite de tests utilisateurs'")
	log_and_exec(ADD + " profile --name Responsibilisateurs --group responsibilisateurs --groups cdrom,lpadmin,plugdev,audio,video,scanner,fuse --comment 'profil power user créé pour la suite de tests utilisateurs.'")

	log_and_exec(ADD + " user toto --profile utilisagers")
	log_and_exec(ADD + " user tutu --profile utilisagers")
	log_and_exec(ADD + " user tata --profile utilisagers")

	log_and_exec(MOD + " profile --group utilisagers --apply-groups --to-groups utilisagers")
	log_and_exec(MOD + " profile --group utilisagers --apply-groups --to-members")
	log_and_exec(MOD + " profile --group utilisagers --apply-skel --to-users toto --auto-no")
	log_and_exec(MOD + " profile --group utilisagers --apply-skel --to-users toto --batch")
	log_and_exec(MOD + " profile --group utilisagers --apply-group --to-users toto")
	log_and_exec(MOD + " profile --group utilisagers --apply-all --to-users toto")
	log_and_exec(MOD + " profile --group utilisagers --apply-all --to-users toto")
	log_and_exec(MOD + " profile --group utilisagers --apply-all --to-all")

	log_and_exec(DEL + " profile --group responsibilisateurs --no-archive")
	log_and_exec(DEL + " user toto --no-archive")

	log_and_exec(DEL + " profile --group utilisagers --del-users --no-archive")

	test_message('''profiles related tests finished.''')
	""" # ends of old test_profiles() commands
def test_privileges(context):
	# test features of privileges

	gname = 'group_test'
	for cmd in [ 'priv', 'privs', 'privilege', 'privileges' ]:
		ScenarioTest([
			GET + [ cmd ],
			ADD + [ 'group', '--name=%s' % gname, '-v' ],
			ADD + [ cmd, '--name=%s' % gname, '-v' ],
			GET + [ cmd ],
			DEL + [ 'group', '--name=%s' % gname, '-v' ],
			ADD + [ 'group', '--name=%s' % gname, '--system', '-v' ],
			ADD + [ 'group', '--name=%s2' % gname, '--system', '-v' ],
			ADD + [ 'group', '--name=%s3' % gname, '--system', '-v' ],
			ADD + [ cmd, '--name=%s' % gname, '-v' ],
			GET + [ cmd ],
			ADD + [ cmd, '--name=%s2,%s3' % (gname, gname), '-v' ],
			GET + [ cmd ],
			DEL + [ cmd, '--name=%s' % gname, '-v' ],
			GET + [ cmd ],
			DEL + [ cmd, '--name=%s2,%s3' % (gname, gname), '-v' ],
			GET + [ cmd ],
			DEL + [ 'group', '--name=%s' % gname, '-v' ],
			DEL + [ 'group', '--name=%s2' % gname, '-v' ],
			DEL + [ 'group', '--name=%s3' % gname, '-v' ],
			],
			context=context,
			descr='''test new privileges commands (using argument %s) '''
				'''(avoid #204 #174)''' % cmd
			).Run()

def test_short_syntax():
	uname = 'user_test'
	gname = 'group_test'
	pname = 'profil_test'

	ScenarioTest([
		ADD + [ 'user', uname, '-v' ],
		GET + [ 'user', uname ],
		ADD + [ 'group', gname, '-v' ],
		GET + [ 'group', gname ],
		ADD + [ 'user', uname, gname, '-v' ],
		GET + [ 'user', uname, '-l' ],
		ADD + [ 'group', '%s2' % gname, '-v' ],
		GET + [ 'group', '%s2' % gname ],
		ADD + [ 'group', '%s3,%s4' % (gname, gname), '-v' ],
		# should fail (already present)
		GET + [ 'group', '%s3,%s4' % (gname, gname) ],
		# should add user2 & user3
		ADD + [ 'user', '%s2,%s3' % (uname, uname), '-v' ],
		GET + [ 'user', '%s2,%s3' % (uname, uname) ],
		# add 2 users in 3 groups each
		ADD + [ 'user', '%s2,%s3' % (uname, uname), '%s2,%s3,%s4' %
			(gname,gname,gname), '-v' ],
		GET + [ 'user', '%s2,%s3' % (uname, uname), '-l' ],
		# should add ONLY ONE user in a group and bypass empty one
		ADD + [ 'user', ',%s' % uname, ',%s2' % gname, '-v' ],
		# idem
		ADD + [ 'user', '%s,' % uname, '%s3,' % gname, '-v' ],
		GET + [ 'user', uname, '-l' ],
		# should delete only one user and bypass empty one
		DEL + [ 'user', ',%s' % uname, '-v'],
		# should fail (already deleted)
		DEL + [ 'user', '%s,' % uname, '-v'],
		# IDEM
		DEL + [ 'user', uname, '-v'],
		# delete 2 users at same time
		DEL + [ 'user', '%s2,%s3' % (uname, uname), '-v'],
		# delete groups, one, then two, then one (bypassing empty)
		DEL + [ 'group', gname, '-v'],
		DEL + [ 'group', '%s2,%s3' %  (gname, gname), '-v'],
		DEL + [ 'group', ',%s4' %  gname, '-v'],
		DEL + [ 'group', '%s4,' %  gname, '-v'],
		DEL + [ 'group', '%s4' %  gname, '-v'],
		],
		descr='test short users/groups commands'
		).Run()

	ScenarioTest([
		ADD + [ 'group', gname, '-v' ],
		#should fail (the group is not a system group)
		ADD + [ 'privilege', gname, '-v' ],
		GET + [ 'privileges' ],
		ADD + [ 'group', '%ssys' % gname, '--system', '-v' ],
		ADD + [ 'privilege', '%ssys' % gname, '-v' ],
		GET + [ 'privileges' ],
		DEL + [ 'privilege', '%ssys' % gname ],
		GET + [ 'privileges' ],
		DEL + [ 'group', gname ],
		DEL + [ 'group', '%ssys' % gname ],
		],
		descr='test short privileges commands'
		).Run()

	ScenarioTest([
		ADD + [ 'group', gname, '--system', '-v' ],
		ADD + [ 'group', '%s2' % gname, '-v' ],
		ADD + [ 'group', '%s3' % gname, '-v' ],
		# should fail (not a system group)
		ADD + [ 'profile', pname, '--group=%s2' % gname, '--force-existing' ],
		GET + [ 'profiles' ],
		# should be OK
		ADD + [ 'profile', pname, '--group=%s' % gname, '--force-existing' ],
		GET + [ 'profiles' ],
		MOD + [ 'profile', pname, '--add-groups=%s2,%s3' % (gname,gname) ],
		GET + [ 'profiles' ],
		MOD + [ 'profile', pname, '--del-groups=%s2,%s3' % (gname,gname) ],
		GET + [ 'profiles' ],
		DEL + [ 'profile', pname ],
		DEL + [ 'group', '%s2' % gname, '-v' ],
		DEL + [ 'group', '%s3' % gname, '-v' ],
		GET + [ 'profiles' ],
		],
		descr='test short profiles commands'
		).Run()

	ScenarioTest([
		ADD + [ 'group', gname, '-v' ],
		ADD + [ 'group', '%s2' % gname, '-v' ],
		CHK + [ 'group', gname, '--auto-no', '-vv' ],
		CHK + [ 'group', gname, '--auto-yes', '-vv' ],
		CHK + [ 'group', gname, '-vb' ],
		CHK + [ 'group', '%s,%s2' % (gname,gname), '--auto-no', '-vv' ],
		CHK + [ 'group', '%s,%s2' % (gname,gname), '--auto-yes', '-vv' ],
		CHK + [ 'group', '%s,%s2' % (gname,gname), '-vb' ],
		DEL + [ 'group', '%s,%s2' % (gname,gname), '-v' ],
		CHK + [ 'config','--auto-no', '-vvae' ],
		CHK + [ 'config','--auto-yes', '-vvae' ],
		CHK + [ 'config','--batch', '-vvae' ],
		ADD + [ 'user', uname, '-v' ],
		CHK + [ 'user', uname, '--auto-no', '-v' ],
		CHK + [ 'user', uname, '--auto-yes', '-v' ],
		CHK + [ 'user', uname, '-vb' ],
		DEL + [ 'user', uname, '-v' ],
		],
		descr='test short chk commands'
		).Run()

	"""
	# extended check on user not implemented yet
	CHK + [ 'user', '%s,%s2' % (uname,uname), '--auto-no', '-vve' ],
	CHK + [ 'user', '%s,%s2' % (uname,uname), '--auto-yes', '-vve' ],
	CHK + [ 'user', '%s,%s2' % (uname,uname), '--batch', '-vve' ],
	DEL + [ 'user', '%s,%s2' % (uname,uname), '-v' ],
	# check on profile not implemented yet
	ADD + [ 'profile', '%s,%s2' % (pname,pname), '-v' ],
	CHK + [ 'profile', pname, '--auto-no', '-vve' ],
	CHK + [ 'profile', pname, '--auto-yes', '-vve' ],
	CHK + [ 'profile', pname, '--batch', '-vve' ],
	CHK + [ 'profile', '%s,%s2' % (pname,pname), '--auto-no', '-vve' ],
	CHK + [ 'profile', '%s,%s2' % (pname,pname), '--auto-yes', '-vve' ],
	CHK + [ 'profile', '%s,%s2' % (pname,pname), '--batch', '-vve' ],
	DEL + [ 'profile', '%s,%s2' % (pname,pname), '-v' ],
	"""
def to_be_implemented():
	""" TO BE DONE !
		#
		# Profiles
		#

		# doit planter pour le groupe
		log_and_exec $ADD profile --name=profileA --group=a

		# doit planter pour le groupe kjsdqsdf
		log_and_exec $ADD profile --name=profileB --group=b --comment="le profil b" --shell=/bin/bash --quota=26 --groups=cdrom,kjsdqsdf,audio --skeldir=/etc/skel && exit 1

		# doit planter pour le skel pas un répertoire, pour le groupe jfgdghf
		log_and_exec $MOD profile --name=profileA --rename=theprofile --rename-primary-group=theprofile --comment=modify --shell=/bin/sh --skel=/etc/power --quota=10 --add-groups=cdrom,remote,qsdfgkh --del-groups=cdrom,jfgdghf

		log_and_exec $DEL profile --name=profileB --del-users --no-archive

		log_and_exec $DEL profile --name=profileeD
		log_and_exec $MOD profile --name=profileeC --not-permissive
		log_and_exec $ADD profile --name=theprofile
		log_and_exec $MOD profile --name=theprofile --skel=/etc/doesntexist
	}

	"""
	pass


if __name__ == "__main__":
	try:
		# Unit Tests.
		test_find_new_indentifier()

		# clean old testsuite runs.
		clean_system()

		if get_state(state_type='context') == 0:
			# Functionnal Tests
			test_integrated_help()
			#test_check_config()
			test_regexes()
			save_state(1, state_type='context')
			ctx_will_change = True
		else:
			logging.notice('Skipping context %s' % stylize(ST_NAME, "std"))
			ctx_will_change = False

		for ctxnum, ctx, activate_cmd in (
			(1, 'unix', [ 'mod', 'config', '-B', 'ldap']),
			(2, 'ldap', [ 'mod', 'config', '-b', 'ldap'])
			):

			if execute(activate_cmd)[1] == 0:

				start_ctx = get_state('context')

				if ctxnum < start_ctx:
					logging.notice('Skipping context %s' %
						stylize(ST_NAME, ctx))
					continue

				test_message('testing %s context.' % ctx)

				make_backups(ctx)

				if get_state(state_type='scenarii') == 0 \
					or ctx_will_change == True:
					ScenarioTest.reinit()

				test_get(ctx)
				test_groups(ctx)
				test_users(ctx)
				test_profiles(ctx)
				test_privileges(ctx)
				test_imports(ctx)
				compare_delete_backups(ctx)
				clean_system()

				save_state(ctxnum + 1, state_type='context')
				ctx_will_change = True
		# TODO: test_concurrent_accesses()

		clean_state_files()
		logging.notice("Testsuite terminated successfully.")
	finally:
		# give back all the scenarii tree to calling user.
		uid, gid = [ int(x) for x in \
			open(state_files['owner']).read().strip().split(',') ]
		logging.notice('giving back all scenarii data to %s:%s.' % (
			stylize(ST_UGID, uid), stylize(ST_UGID, gid)))
		for entry in fsapi.minifind('data'):
			os.chown(entry, uid, gid)
