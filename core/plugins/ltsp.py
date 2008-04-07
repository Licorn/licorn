# -*- coding: utf-8 -*-
"""
Licorn core - http://dev.licorn.org/documentation/core

Copyright (C) 2005-2007 Olivier Cortès <oc@5sys.fr>
Licensed under the terms of the GNU GPL version 2

"""
import re
from licorn.foundations import exceptions

class LTSPConfiguration (dict) :

	def __init__(self, config_file = '/opt/ltsp/i386/etc/lts.conf', version = 4) :
		"""Create an LTSPConfiguration instance."""

		dict.__init__(self)

		self.config_file  = config_file
		self.ltsp_version = version
	
		self._parse()
	def _parse(self) :
		"""fill the internal data structure with the contents of the configuration file."""
		
		section      = None
		section_data = None
		data_re      = re.compile('''^\s*(?P<key>[a-z0-9_]*)\s*=\s*["']?(?P<value>[^"'\n]*)["']?\s*(#.*)?$''', re.IGNORECASE)
		line_no      = 1

		for line in open(self.config_file) :
			if line[0] == '[' :
				if section is not None :
					# store previous section in the data structure, 
					# in order to create a new one.
					self[section] = section_data.copy()

				# create a new section
				section      = line[1:-2]
				section_data = {}

			else :
				#print 'DEBUG: %s' % line[:-1]
				d = data_re.match(line)

				if d is not None :
					if section is None :
						raise exceptions.LicornConfigurationError("%s seems corrupt on line %d: we've got a directive outside any section !" % (self.config_file, line_no))		
					else :
						g = d.groupdict()
						section_data[g['key']] = g['value']

				# else (d is None) : skip the line, it is a comment or a blank line...

			line_no += 1

		if section is not None :
			# store the last section in the data structure, 
			# in order to create a new one.
			self[section] = section_data.copy()

	def Export(self) :
		"""Rebuild the contents of the configuration file from the internal data."""

		data = '''#
# LTSP Configuration file
#
# Generated by Licorn Ltsconf parser.
#

'''
		def export_section(section) :
			# FIXME: dont put the backward compat comments, just parse the file with
			#	modern code...
			#
			# the comments are a legacy / backward compatibility system
			# with AbulEdu PHP webadmin which needs these comments.
			edata = '''#%s debut\n[%s]\n''' % (section, section)
			section_keys = self[section].keys()
			section_keys.sort()
			for key in section_keys :
				edata += '''%s%s = "%s"\n''' % ( ' '*(22 - len(key)), key, self[section][key])
			edata += '''#%s fin\n''' % section
			return edata
		
		data += export_section('Default')

		othersections = self.keys()
		othersections.remove('Default')
		othersections.sort()

		data += '\n'.join(map(export_section, othersections))

		return data
	def Write(self) :
		"""Write the configuration file on disk with the contents of the internal data structure inside."""

		f = open(self.config_file, 'w')
		f.write(self.Export())
		f.close()

if __name__ == "__main__" :
	l = LTSPConfiguration()
	#print l.Export()
