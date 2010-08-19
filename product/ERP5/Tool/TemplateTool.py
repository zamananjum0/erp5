# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2002 Nexedi SARL and Contributors. All Rights Reserved.
#                    Jean-Paul Smets-Solanes <jp@nexedi.com>
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsability of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# garantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################

from webdav.client import Resource

from App.config import getConfiguration
import os
import shutil
import sys

from Acquisition import Implicit, Explicit
from AccessControl import ClassSecurityInfo
from Products.CMFActivity.ActiveResult import ActiveResult
from Products.ERP5Type.Globals import InitializeClass, DTMLFile, PersistentMapping
from Products.ERP5Type.DiffUtils import DiffFile
from Products.ERP5Type.Tool.BaseTool import BaseTool
from Products.ERP5Type import Permissions, tarfile
from Products.ERP5.Document.BusinessTemplate import BusinessTemplateMissingDependency
from Acquisition import aq_base
from tempfile import mkstemp, mkdtemp
from Products.ERP5 import _dtmldir
from cStringIO import StringIO
from urllib import pathname2url, urlopen, splittype, urlretrieve
import urllib2
import re
from xml.dom.minidom import parse
from xml.parsers.expat import ExpatError
import struct
import cPickle
import posixpath
from base64 import b64encode, b64decode
from Products.ERP5Type.Message import translateString
from zLOG import LOG, INFO
from base64 import decodestring
import subprocess


WIN = os.name == 'nt'

_MARKER = []

class BusinessTemplateUnknownError(Exception):
  """ Exception raised when the business template
      is impossible to find in the repositories
  """
  pass

class UnsupportedComparingOperator(Exception):
  """ Exception when the comparing string is unsupported
  """
  pass

class BusinessTemplateIsMeta(Exception):
  """ Exception when the business template is provided by another one
  """
  pass

class TemplateTool (BaseTool):
    """
      TemplateTool manages Business Templates.

      TemplateTool provides some methods to deal with Business Templates:
        - download
        - publish
        - install
        - update
        - save
    """
    id = 'portal_templates'
    title = 'Template Tool'
    meta_type = 'ERP5 Template Tool'
    portal_type = 'Template Tool'
    allowed_types = ( 'ERP5 Business Template',)

    # This stores information on repositories.
    repository_dict = {}

    # Declarative Security
    security = ClassSecurityInfo()

    security.declareProtected( Permissions.ManagePortal, 'manage_overview' )
    manage_overview = DTMLFile( 'explainTemplateTool', _dtmldir )

    def getInstalledBusinessTemplate(self, title, **kw):
      """
        Return an installed version of business template of a certain title.

        It not "installed" business template is found, look at replaced ones.
        This is mostly usefull if we are looking for the installed business
        template in a transaction replacing an existing business template
      """
      # This can be slow if, say, 10000 business templates are present.
      # However, that unlikely happens, and using a Z SQL Method has a
      # potential danger because business templates may exchange catalog
      # methods, so the database could be broken temporarily.
      replaced_list = []
      replaced_list_append = replaced_list.append
      for bt in self.contentValues(filter={'portal_type':'Business Template'}):
        if bt.getTitle() == title:
          installation_state = bt.getInstallationState()
          if installation_state == 'installed':
            return bt
          elif installation_state == 'replaced':
            replaced_list_append((bt.getId(), bt.getRevision()))
      # still there means that we might search for a replaced bt
      if len(replaced_list):
        replaced_list.sort(key=lambda x: -int(x[1]))
        return self._getOb(replaced_list[0][0])
      return None

    def getInstalledBusinessTemplatesList(self):
      """Deprecated.
      """
      DeprecationWarning('getInstalledBusinessTemplatesList is deprecated; Use getInstalledBusinessTemplateList instead.', DeprecationWarning)
      return self.getInstalledBusinessTemplateList()

    def _getInstalledBusinessTemplateList(self, only_title=0):
      """Get the list of installed business templates.
      """
      installed_bts = []
      for bt in self.contentValues(portal_type='Business Template'):
        if bt.getInstallationState() == 'installed':
          bt5 = bt
          if only_title:
            bt5 = bt.getTitle()
          installed_bts.append(bt5)
      return installed_bts

    def getInstalledBusinessTemplateList(self):
      """Get the list of installed business templates.
      """
      return self._getInstalledBusinessTemplateList(only_title=0)

    def getInstalledBusinessTemplateTitleList(self):
      """Get the list of installed business templates.
      """
      return self._getInstalledBusinessTemplateList(only_title=1)

    def getInstalledBusinessTemplateRevision(self, title, **kw):
      """
        Return the revision of business template installed with the title
        given
      """
      bt = self.getInstalledBusinessTemplate(title)
      return bt.getRevision()

    def getBuiltBusinessTemplatesList(self):
      """Deprecated.
      """
      DeprecationWarning('getBuiltBusinessTemplatesList is deprecated; Use getBuiltBusinessTemplateList instead.', DeprecationWarning)
      return self.getBuiltBusinessTemplateList()

    def getBuiltBusinessTemplateList(self):
      """Get the list of built and not installed business templates.
      """
      built_bts = []
      for bt in self.contentValues(portal_type='Business Template'):
        if bt.getInstallationState() == 'not_installed' and bt.getBuildingState() == 'built':
          built_bts.append(bt)
      return built_bts

    @property
    def asRepository(self):
      class asRepository(Explicit):
        """Export business template by their title

        Provides a view of template tool allowing a user to download the last
        revision of a business template with a URL like:
          http://.../erp5/portal_templates/asRepository/erp5_core
        """
        def __before_publishing_traverse__(self, self2, request):
          path = request['TraversalRequestNameStack']
          self.subpath = tuple(reversed(path))
          del path[:]
        def __call__(self, REQUEST, RESPONSE):
          title, = self.subpath
          last_bt = None, None
          for bt in self.aq_parent.searchFolder(title=title):
            bt = bt.getObject()
            revision = int(bt.getRevision())
            if last_bt[0] < revision and bt.getInstallationState() != 'deleted':
              last_bt = revision, bt
          if last_bt[1] is None:
            return RESPONSE.notFoundError(title)
          RESPONSE.setHeader('Content-type', 'application/data')
          RESPONSE.setHeader('Content-Disposition',
                             'inline;filename=%s-%s.zexp' % (title, last_bt[0]))
          if REQUEST['REQUEST_METHOD'] == 'GET':
            bt = last_bt[1]
            if bt.getBuildingState() != 'built':
              bt.build()
            return self.aq_parent.manage_exportObject(bt.getId(), download=1)
      return asRepository().__of__(self)

    security.declareProtected(Permissions.ManagePortal,
                              'getDefaultBusinessTemplateDownloadURL')
    def getDefaultBusinessTemplateDownloadURL(self):
      """Returns the default download URL for business templates.
      """
      return "file://%s/" % pathname2url(
                  os.path.join(getConfiguration().instancehome, 'bt5'))

    security.declareProtected( 'Import/Export objects', 'save' )
    def save(self, business_template, REQUEST=None, RESPONSE=None):
      """
        Save the BusinessTemplate in the servers's filesystem.
      """
      cfg = getConfiguration()
      path = os.path.join(cfg.clienthome,
                          '%s' % (business_template.getTitle(),))
      path = pathname2url(path)
      business_template.export(path=path, local=True)
      if REQUEST is not None:
        psm = translateString('Saved in ${path} .',
                              mapping={'path':pathname2url(path)})
        ret_url = '%s/%s?portal_status_message=%s' % \
                  (business_template.absolute_url(),
                   REQUEST.get('form_id', 'view'), psm)
        if RESPONSE is None:
          RESPONSE = REQUEST.RESPONSE
        return REQUEST.RESPONSE.redirect( ret_url )

    security.declareProtected( 'Import/Export objects', 'export' )
    def export(self, business_template, REQUEST=None, RESPONSE=None):
      """
        Export the Business Template as a bt5 file and offer the user to
        download it.
      """
      path = business_template.getTitle()
      path = pathname2url(path)
      # XXX Why is it necessary to create a temporary directory?
      tmpdir_path = mkdtemp()
      # XXX not thread safe
      current_directory = os.getcwd()
      os.chdir(tmpdir_path)
      absolute_path = os.path.abspath(path)
      export_string = business_template.export(path=absolute_path)
      os.chdir(current_directory)
      if RESPONSE is not None:
        RESPONSE.setHeader('Content-type','tar/x-gzip')
        RESPONSE.setHeader('Content-Disposition',
                           'inline;filename=%s-%s.bt5' % \
                               (path,
                                business_template.getVersion()))
      try:
        return export_string.getvalue()
      finally:
        export_string.close()

    security.declareProtected( 'Import/Export objects', 'publish' )
    def publish(self, business_template, url, username=None, password=None):
      """
        Publish the given business template at the given URL.
      """
      business_template.build()
      export_string = self.manage_exportObject(id=business_template.getId(),
                                               download=True)
      bt = Resource(url, username=username, password=password)
      bt.put(file=export_string,
             content_type='application/x-erp5-business-template')
      business_template.setPublicationUrl(url)

    def update(self, business_template):
      """
        Update an existing template from its publication URL.
      """
      url = business_template.getPublicationUrl()
      id = business_template.getId()
      bt = Resource(url)
      export_string = bt.get().get_body()
      self.deleteContent(id)
      self._importObjectFromFile(StringIO(export_string), id=id)

    def _importBT(self, path=None, id=id):
      """
        Import template from a temp file (as uploaded by the user)
      """
      file = open(path, 'rb')
      try:
        # read magic key to determine wich kind of bt we use
        file.seek(0)
        magic = file.read(5)
      finally:
        file.close()

      if magic == '<?xml': # old version
        self._importObjectFromFile(path, id=id)
        bt = self[id]
        bt.id = id # Make sure id is consistent
        bt.setProperty('template_format_version', 0, type='int')
      else: # new version
        # XXX: should really check for a magic and offer a falback if it
        # doens't correspond to anything handled.
        tar = tarfile.open(path, 'r:gz')
        try:
          # create bt object
          bt = self.newContent(portal_type='Business Template', id=id)
          prop_dict = {}
          for prop in bt.propertyMap():
            prop_type = prop['type']
            pid = prop['id']
            prop_path = posixpath.join(tar.members[0].name, 'bt', pid)
            try:
              info = tar.getmember(prop_path)
            except KeyError:
              continue
            value = tar.extractfile(info).read()
            if value is 'None':
              # At export time, we used to export non-existent properties:
              #   str(obj.getProperty('non-existing')) == 'None'
              # Discard them
              continue
            if prop_type == 'text' or prop_type == 'string' \
                                   or prop_type == 'int':
              prop_dict[pid] = value
            elif prop_type == 'lines' or prop_type == 'tokens':
              prop_dict[pid[:-5]] = value.splitlines()
          prop_dict.pop('id', '')
          bt.edit(**prop_dict)
          # import all other files from bt
          fobj = open(path, 'rb')
          try:
            bt.importFile(file=fobj)
          finally:
            fobj.close()
        finally:
          tar.close()
      return bt

    security.declareProtected( Permissions.ManagePortal, 'manage_download' )
    def manage_download(self, url, id=None, REQUEST=None):
      """The management interface for download.
      """
      if REQUEST is None:
        REQUEST = getattr(self, 'REQUEST', None)

      bt = self.download(url, id=id)

      if REQUEST is not None:
        ret_url = bt.absolute_url() + '/view'
        psm = translateString("Business template downloaded successfully.")
        REQUEST.RESPONSE.redirect("%s?portal_status_message=%s"
                                    % (ret_url, psm))

    def _download_local(self, path, bt_id):
      """Download Business Template from local directory or file
      """
      if os.path.isdir(os.path.normpath(path)):
        path = os.path.normpath(path)
        def callback(file_list, directory, files):
          for excluded_directory in ('CVS', '.svn'):
            try:
              files.remove(excluded_directory)
            except ValueError:
              pass
          for file in files:
            absolute_path = os.path.join(directory, file)
            if os.path.isfile(absolute_path):
              file_list.append(absolute_path)

        file_list = []
        os.path.walk(path, callback, file_list)
        file_list.sort()
        # import bt object
        bt = self.newContent(portal_type='Business Template', id=bt_id)
        bt_path = os.path.join(path, 'bt')

        # import properties
        prop_dict = {}
        for prop in bt.propertyMap():
          prop_type = prop['type']
          pid = prop['id']
          prop_path = os.path.join('.', bt_path, pid)
          if not os.path.exists(prop_path):
            continue
          value = open(prop_path, 'rb').read()
          if value is 'None':
            # At export time, we used to export non-existent properties:
            #   str(obj.getProperty('non-existing')) == 'None'
            # Discard them
            continue
          if prop_type in ('text', 'string', 'int', 'boolean'):
            prop_dict[pid] = value
          elif prop_type in ('lines', 'tokens'):
            prop_dict[pid[:-5]] = value.splitlines()
        prop_dict.pop('id', '')
        bt.edit(**prop_dict)
        # import all others objects
        bt.importFile(dir=True, file=file_list, root_path=path)
        return bt
      else:
        # this should be a file
        return self._importBT(path, bt_id)

    def _download_url(self, url, bt_id):
      tempid, temppath = mkstemp()
      try:
        os.close(tempid) # Close the opened fd as soon as possible.
        file_path, headers = urlretrieve(url, temppath)
        if re.search(r'<title>Revision \d+:', open(file_path, 'r').read()):
          # this looks like a subversion repository, try to check it out
          LOG('ERP5', INFO, 'TemplateTool doing a svn checkout of %s' % url)
          return self._download_svn(url, bt_id)

        return self._download_local(file_path, bt_id)
      finally:
        os.remove(temppath)

    def _download_svn(self, url, bt_id):
      svn_checkout_tmp_dir = mkdtemp()
      svn_checkout_dir = os.path.join(svn_checkout_tmp_dir, 'bt')
      try:
        import pysvn
        pysvn.Client().export(url, svn_checkout_dir)
        return self._download_local(svn_checkout_dir, bt_id)
      finally:
        shutil.rmtree(svn_checkout_tmp_dir)

    def assertBtPathExists(self, url):
      """
      Check if bt is present on the system
      """
      urltype, name = splittype(url)
      # Windows compatibility
      if WIN:
        if os.path.isdir(os.path.normpath(url)) or \
           os.path.isfile(os.path.normpath(url)):
          name = os.path.normpath(url)
      return os.path.exists(os.path.normpath(name))

    security.declareProtected( 'Import/Export objects', 'download' )
    def download(self, url, id=None, REQUEST=None):
      """
      Download Business Template from url, can be file or local directory
      """
      # For backward compatibility: If REQUEST is passed, it is likely that we
      # come from the management interface.
      if REQUEST is not None:
        return self.manage_download(url, id=id, REQUEST=REQUEST)

      if id is None:
        id = self.generateNewId()

      urltype, name = splittype(url)
      # Windows compatibility
      if WIN:
        if os.path.isdir(os.path.normpath(url)) or \
           os.path.isfile(os.path.normpath(url)):
          urltype = 'file'
          name = os.path.normpath(url)

      if urltype and urltype != 'file':
        if '/portal_templates/asRepository/' in url:
          # In this case, the downloaded BT is already built.
          bt = self._p_jar.importFile(urlopen(url))
          bt.id = id
          del bt.uid
          return self[self._setObject(id, bt)]
        bt = self._download_url(url, id)
      else:
        bt = self._download_local(name, id)

      bt.build(no_action=True)
      return bt

    def importBase64EncodedText(self, file_data=None, id=None, REQUEST=None,
                                batch_mode=False, **kw):
      """
        Import Business Template from passed base64 encoded text.
      """
      import_file = StringIO(decodestring(file_data))
      return self.importFile(import_file = import_file, id = id, REQUEST = REQUEST,
                             batch_mode = batch_mode, **kw)

    def importFile(self, import_file=None, id=None, REQUEST=None,
                   batch_mode=False, **kw):
      """
        Import Business Template from one file
      """
      if REQUEST is None:
        REQUEST = getattr(self, 'REQUEST', None)

      if id is None:
        id = self.generateNewId()

      if (import_file is None) or (len(import_file.read()) == 0):
        if REQUEST is not None:
          psm = translateString('No file or an empty file was specified.')
          REQUEST.RESPONSE.redirect("%s?portal_status_message=%s"
                                    % (self.absolute_url(), psm))
          return
        else :
          raise RuntimeError, 'No file or an empty file was specified'
      # copy to a temp location
      import_file.seek(0) #Rewind to the beginning of file
      tempid, temppath = mkstemp()
      try:
        os.close(tempid) # Close the opened fd as soon as possible
        tempfile = open(temppath, 'wb')
        try:
          tempfile.write(import_file.read())
        finally:
          tempfile.close()
        bt = self._importBT(temppath, id)
      finally:
        os.remove(temppath)
      bt.build(no_action=True)
      bt.reindexObject()

      if not batch_mode and \
         (REQUEST is not None):
        ret_url = bt.absolute_url() + '/view'
        psm = translateString("Business templates imported successfully.")
        REQUEST.RESPONSE.redirect("%s?portal_status_message=%s"
                                  % (ret_url, psm))
      elif batch_mode:
        return bt

    security.declareProtected(Permissions.ManagePortal, 'runUnitTestList')
    def runUnitTestList(self, test_list=[],
                        sql_connection_string='',
                        save=False, load=False,
                        repository_list=None,
                        REQUEST=None, RESPONSE=None, **kwd):
      """Runs Unit Tests related to this Business Template
      """
      if repository_list is None:
        repository_list = []
      # XXX: should check for file presence before trying to execute.
      # XXX: should check if the unit test file is configured in the BT
      site_configuration = getConfiguration()
      from Products.ERP5Type.tests.runUnitTest import getUnitTestFile
      import Products.ERP5
      if RESPONSE is not None:
        outfile = RESPONSE
      elif REQUEST is not None:
        outfile = RESPONSE = REQUEST.RESPONSE
      else:
        outfile =  StringIO()
      if RESPONSE is not None:
        RESPONSE.setHeader('Content-type', 'text/plain')
      current_sys_path = sys.path
      # add path with tests
      current_sys_path.append(os.path.join(site_configuration.instancehome,
        'tests'))

      test_cmd_args = [sys.executable, getUnitTestFile()]
      test_cmd_args += ['--erp5_sql_connection_string', sql_connection_string]
      if load:
        test_cmd_args += ['--load']
      if save:
        test_cmd_args += ['--save']
      # pass currently used product path to test runner
      products_path_list = site_configuration.products
      # add products from Zope, as some sites are not providing it
      zope_products_path = os.path.join(site_configuration.softwarehome, 'Products')
      if zope_products_path not in products_path_list:
        products_path_list.append(zope_products_path)
      test_cmd_args += ['--products_path', ','.join(products_path_list)]
      test_cmd_args += ['--sys_path', ','.join(current_sys_path)]
      bt5_path_list = []
      ## XXX-TODO: requires that asRepository works without security, maybe
      ##           with special key?
      # bt5_path_list.append(self.absolute_url() + '/asRepository/')
      # add passed repository list
      bt5_path_list.extend(repository_list)
      # adding locally saved Business Templates, not perfect, but helps some
      # people doing strict TTW development
      bt5_path_list.append(site_configuration.clienthome)
      test_cmd_args += ['--bt5_path', ','.join(bt5_path_list)]
      test_cmd_args += test_list
      # prepare message - intentionally without any additional formatting, as
      # only developer will read it, and they will have to understand issues in
      # case of test failures
      invoke_command_message = 'Running tests using command: %r'% test_cmd_args
      # as it is like using external interface, log what is send there
      LOG('TemplateTool.runUnitTestList', INFO, invoke_command_message)
      # inform developer how test are invoked
      outfile.write(invoke_command_message + '\n')
      outfile.flush()
      process = subprocess.Popen(test_cmd_args,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)

      # "for line in process.stdout" is cleaner but is buffered,
      # see http://bugs.python.org/issue3907
      # We use this ugly construct to avoid waiting for test
      # termination before printing content
      while True:
        line = process.stdout.readline()
        if not line:
          break
        outfile.write(line)
        outfile.flush()

      if hasattr(outfile, 'getvalue'):
        return outfile.getvalue()

    def getDiffFilterScriptList(self):
      """
      Return list of scripts usable to filter diff
      """
      # XXX-Aurel : this will be removed in a near future when script
      # will be configurable on the tool
      return [getattr(self, 'TemplateTool_filterTupleDiff'),]

    def getFilteredDiffAsHTML(self, diff):
      """
      Return the diff filtered by python scripts into html format
      """
      return self.getFilteredDiff(diff).toHTML()

    def getFilteredDiff(self, diff):
      """
      Filter the diff using python scripts
      """
      diff_file_object = DiffFile(diff)
      diff_block_list = diff_file_object.getModifiedBlockList()
      if len(diff_block_list):
        for script in self.getDiffFilterScriptList():
          for block, line_tuple in diff_block_list:
            if script(line_tuple[0], line_tuple[1]):
              diff_file_object.children.remove(block)
      # XXX-Aurel : this method should return a text diff but
      # DiffFile does not provide yet such feature
      return diff_file_object

    def diffObjectAsHTML(self, REQUEST, **kw):
      """
        Convert diff into a HTML format before reply
        This is compatible with ERP5Subversion look and feel but
        it is preferred in future we use more difflib python library.
      """
      return DiffFile(self.diffObject(REQUEST, **kw)).toHTML()

    def diffObject(self, REQUEST, **kw):
      """
        Make diff between two objects, whose paths are stored in values bt1
        and bt2 in the REQUEST object.
      """
      bt1_id = getattr(REQUEST, 'bt1', None)
      bt2_id = getattr(REQUEST, 'bt2', None)
      if bt1_id is not None and bt2_id is not None:
        bt1 = self._getOb(bt1_id)
        bt2 = self._getOb(bt2_id)
        if self.compareVersions(bt1.getVersion(), bt2.getVersion()) < 0:
          return bt2.diffObject(REQUEST, compare_with=bt1_id)
        else:
          return bt1.diffObject(REQUEST, compare_with=bt2_id)
      else:
        object_id = getattr(REQUEST, 'object_id', None)
        bt1_id = object_id.split('|')[0]
        bt1 = self._getOb(bt1_id)
        REQUEST.set('object_id', object_id.split('|')[1])
        return bt1.diffObject(REQUEST)

    security.declareProtected( 'Import/Export objects',
                               'updateRepositoryBusinessTemplateList' )

    def updateRepositoryBusinessTemplateList(self, repository_list,
                                             REQUEST=None, RESPONSE=None, **kw):
      """
        Update the information on Business Templates from repositories.
      """
      self.repository_dict = PersistentMapping()
      property_list = ('title', 'version', 'revision', 'description', 'license',
                       'dependency', 'provision', 'copyright')
      #LOG('updateRepositoryBusiessTemplateList', 0,
      #    'repository_list = %r' % (repository_list,))
      for repository in repository_list:
        url = '/'.join([repository, 'bt5list'])
        f = urlopen(url)
        property_dict_list = []
        try:
          try:
            doc = parse(f)
          except ExpatError:
            if REQUEST is not None:
              psm = translateString('Invalid repository: ${repo}',
                                    mapping={'repo':repository})
              REQUEST.RESPONSE.redirect("%s?portal_status_message=%s"
                                       % (self.absolute_url(), psm))
              return
            else:
              raise RuntimeError, 'Invalid repository: %s' % repository
          try:
            root = doc.documentElement
            for template in root.getElementsByTagName("template"):
              id = template.getAttribute('id')
              if type(id) == type(u''):
                id = id.encode('utf-8')
              temp_property_dict = {}
              for node in template.childNodes:
                if node.nodeName in property_list:
                  value = ''
                  for text in node.childNodes:
                    if text.nodeType == text.TEXT_NODE:
                      value = text.data
                      if type(value) == type(u''):
                        value = value.encode('utf-8')
                      break
                  temp_property_dict.setdefault(node.nodeName, []).append(value)

              property_dict = {}
              property_dict['id'] = id
              property_dict['title'] = temp_property_dict.get('title', [''])[0]
              property_dict['version'] = \
                  temp_property_dict.get('version', [''])[0]
              property_dict['revision'] = \
                  temp_property_dict.get('revision', [''])[0]
              property_dict['description'] = \
                  temp_property_dict.get('description', [''])[0]
              property_dict['license'] = \
                  temp_property_dict.get('license', [''])[0]
              property_dict['dependency_list'] = \
                  temp_property_dict.get('dependency', ())
              property_dict['provision_list'] = \
                  temp_property_dict.get('provision', ())
              property_dict['copyright_list'] = \
                  temp_property_dict.get('copyright', ())

              property_dict_list.append(property_dict)
          finally:
            doc.unlink()
        finally:
          f.close()

        self.repository_dict[repository] = tuple(property_dict_list)

      if REQUEST is not None:
        ret_url = self.absolute_url() + '/' + REQUEST.get('dialog_id', 'view')
        psm = translateString("Business templates updated successfully.")
        REQUEST.RESPONSE.redirect("%s?cancel_url=%s&portal_status_message=%s&dialog_category=object_exchange&selection_name=business_template_selection"
                                  % (ret_url, REQUEST.form.get('cancel_url', ''), psm))

    security.declareProtected( Permissions.AccessContentsInformation,
                               'getRepositoryList' )
    def getRepositoryList(self):
      """
        Get the list of repositories.
      """
      return self.repository_dict.keys()

    security.declarePublic( 'decodeRepositoryBusinessTemplateUid' )
    def decodeRepositoryBusinessTemplateUid(self, uid):
      """
        Decode the uid of a business template from a repository.
        Return a repository and an id.
      """
      return cPickle.loads(b64decode(uid))

    security.declarePublic( 'encodeRepositoryBusinessTemplateUid' )
    def encodeRepositoryBusinessTemplateUid(self, repository, id):
      """
        encode the repository and the id of a business template.
        Return an uid.
      """
      return b64encode(cPickle.dumps((repository, id)))

    def compareVersionStrings(self, version, comparing_string):
      """
       comparing_string is like "<= 0.2" | "operator version"
       operators supported: '<=', '<' or '<<', '>' or '>>', '>=', '=' or '=='
      """
      operator, comp_version = comparing_string.split(' ')
      diff_version = self.compareVersions(version, comp_version)
      if operator == '<' or operator == '<<':
        if diff_version < 0:
          return True;
        return False;
      if operator == '<=':
        if diff_version <= 0:
          return True;
        return False;
      if operator == '>' or operator == '>>':
        if diff_version > 0:
          return True;
        return False;
      if operator == '>=':
        if diff_version >= 0:
          return True;
        return False;
      if operator == '=' or operator == '==':
        if diff_version == 0:
          return True;
        return False;
      raise UnsupportedComparingOperator, 'Unsupported comparing operator: %s'%(operator,)

    security.declareProtected(Permissions.AccessContentsInformation,
                              'IsOneProviderInstalled')
    def IsOneProviderInstalled(self, title):
      """
        return true if a business template that
        provides the bt with the given title is
        installed
      """
      installed_bt_list = self.getInstalledBusinessTemplatesList()
      for bt in installed_bt_list:
        provision_list = bt.getProvisionList()
        if title in provision_list:
          return True
      return False

    security.declareProtected(Permissions.AccessContentsInformation,
                               'getLastestBTOnRepos')
    def getLastestBTOnRepos(self, title, version_restriction=None):
      """
       It's possible we have different versions of the same BT
       available on various repositories or on the same repository.
       This function returns the latest one that meet the version_restriction
       (i.e "<= 0.2") in the following form :
       tuple (repository, id)
      """
      result = None
      for repository, property_dict_list in self.repository_dict.items():
        for property_dict in property_dict_list:
          provision_list = property_dict.get('provision_list', [])
          if title in provision_list:
            raise BusinessTemplateIsMeta, 'Business Template %s is provided by another one'%(title,)
          if title == property_dict['title']:
            if (version_restriction is None) or (self.compareVersionStrings(property_dict['version'], version_restriction)):
              if (result is None) or (self.compareVersions(property_dict['version'], result[2]) > 0):
                result = (repository,  property_dict['id'], property_dict['version'])
      if result is not None:
        return (result[0], result[1])
      else:
        raise BusinessTemplateUnknownError, 'Business Template %s (%s) could not be found in the repositories'%(title, version_restriction or '')

    security.declareProtected(Permissions.AccessContentsInformation,
                              'getProviderList')
    def getProviderList(self, title):
      """
       return a list of business templates that provides
       the given business template
      """
      result_list = []
      for repository, property_dict_list in self.repository_dict.items():
        for property_dict in property_dict_list:
          provision_list = property_dict['provision_list']
          if (title in provision_list) and (property_dict['title'] not in result_list):
            result_list.append(property_dict['title'])
      return result_list

    security.declareProtected(Permissions.AccessContentsInformation,
                               'getDependencyList')
    def getDependencyList(self, bt):
      """
       Return the list of missing dependencies for a business
       template, given a tuple : (repository, id)
      """
      # We do not take into consideration the dependencies
      # for meta business templates
      if bt[0] == 'meta':
        return []
      result_list = []
      for repository, property_dict_list in self.repository_dict.items():
        if repository == bt[0]:
          for property_dict in property_dict_list:
            if property_dict['id'] == bt[1]:
              dependency_list = property_dict['dependency_list']
              for dependency_couple in dependency_list:
                # dependency_couple is like "erp5_xhtml_style (>= 0.2)"
                dependency_couple_list = dependency_couple.split(' ', 1)
                dependency = dependency_couple_list[0]
                version_restriction = None
                if len(dependency_couple_list) > 1:
                  version_restriction = dependency_couple_list[1]
                  if version_restriction.startswith('('):
                    # Something like "(>= 1.0rc6)".
                    version_restriction = version_restriction[1:-1]
                require_update = False
                installed_bt = self.portal_templates.getInstalledBusinessTemplate(dependency)
                if version_restriction is not None:
                  if installed_bt is not None:
                    # Check if the installed version require an update
                    if not self.compareVersionStrings(installed_bt.getVersion(), version_restriction):
                      operator = version_restriction.split(' ')[0]
                      if operator in ('<', '<<', '<='):
                        raise BusinessTemplateMissingDependency, '%s (%s) is present but %s require: %s (%s)'%(dependency, installed_bt.getVersion(), property_dict['title'], dependency, version_restriction)
                      else:
                        require_update = True
                if (require_update or installed_bt is None) \
                  and dependency not in result_list:
                  # Get the lastest version of the dependency on the
                  # repository that meet the version restriction
                  provider_installed = False
                  try:
                    bt_dep = self.getLastestBTOnRepos(dependency, version_restriction)
                  except BusinessTemplateUnknownError:
                    raise BusinessTemplateMissingDependency, 'The following dependency could not be satisfied: %s (%s)\nReason: Business Template could not be found in the repositories'%(dependency, version_restriction or '')
                  except BusinessTemplateIsMeta:
                    provider_list = self.getProviderList(dependency)
                    for provider in provider_list:
                      if self.portal_templates.getInstalledBusinessTemplate(provider) is not None:
                        provider_installed = True
                        break
                    if not provider_installed:
                      bt_dep = ('meta', dependency)
                  if not provider_installed:
                    sub_dep_list = self.getDependencyList(bt_dep)
                    for sub_dep in sub_dep_list:
                      if sub_dep not in result_list:
                        result_list.append(sub_dep)
                    result_list.append(bt_dep)
              return result_list
      raise BusinessTemplateUnknownError, 'The Business Template %s could not be found on repository %s'%(bt[1], bt[0])

    def findProviderInBTList(self, provider_list, bt_list):
      """
       Find one provider in provider_list which is present in
       bt_list and returns the found tuple (repository, id)
       in bt_list.
      """
      for provider in provider_list:
        for repository, id in bt_list:
          if id.startswith(provider):
            return (repository, id)
      raise BusinessTemplateUnknownError, 'Provider not found in bt_list'

    security.declareProtected(Permissions.AccessContentsInformation,
                              'sortBusinessTemplateList')
    def sortBusinessTemplateList(self, bt_list):
      """
       Sort a list of bt according to dependencies
      """
      result_list = []
      for repository, id in bt_list:
        dependency_list = self.getDependencyList((repository, id))
        dependency_list.append((repository, id))
        for dependency in dependency_list:
          if dependency[0] == 'meta':
            provider_list = self.getProviderList(dependency[1])
            dependency = self.findProviderInBTList(provider_list, bt_list)
          if dependency not in result_list:
            result_list.append(dependency)
      return result_list

    security.declareProtected( Permissions.AccessContentsInformation,
                               'getRepositoryBusinessTemplateList' )
    def getRepositoryBusinessTemplateList(self, update_only=False, **kw):
      """Get the list of Business Templates in repositories.
      """
      version_state_title_dict = { 'new' : 'New', 'present' : 'Present',
                                   'old' : 'Old' }

      from Products.ERP5Type.Document import newTempBusinessTemplate
      template_list = []

      template_item_list = []
      if update_only:
        # First of all, filter Business Templates in repositories.
        template_item_dict = {}
        for repository, property_dict_list in self.repository_dict.items():
          for property_dict in property_dict_list:
            title = property_dict['title']
            if title not in template_item_dict:
              # If this is the first time to see this business template,
              # insert it.
              template_item_dict[title] = (repository, property_dict)
            else:
              # If this business template has been seen before, insert it only
              # if this business template is newer.
              previous_repository, previous_property_dict = \
                  template_item_dict[title]
              diff_version = self.compareVersions(previous_property_dict['version'],
                                                  property_dict['version'])
              if diff_version < 0:
                template_item_dict[title] = (repository, property_dict)
              elif diff_version == 0 \
                   and previous_property_dict['revision'] \
                   and property_dict['revision'] \
                   and int(previous_property_dict['revision']) < int(property_dict['revision']):
                      template_item_dict[title] = (repository, property_dict)
        # Next, select only updated business templates.
        for repository, property_dict in template_item_dict.values():
          installed_bt = \
              self.getInstalledBusinessTemplate(property_dict['title'])
          if installed_bt is not None:
            diff_version = self.compareVersions(installed_bt.getVersion(),
                                                property_dict['version'])
            if diff_version < 0:
              template_item_list.append((repository, property_dict))
            elif diff_version == 0 \
                 and installed_bt.getRevision() \
                 and property_dict['revision'] \
                 and int(installed_bt.getRevision()) < int(property_dict['revision']):
                   template_item_list.append((repository, property_dict))
      else:
        for repository, property_dict_list in self.repository_dict.items():
          for property_dict in property_dict_list:
            template_item_list.append((repository, property_dict))

      # Create temporary Business Template objects for displaying.
      for repository, property_dict in template_item_list:
        property_dict = property_dict.copy()
        id = property_dict['id']
        del property_dict['id']
        version = property_dict['version']
        version_state = 'new'
        installed_bt = \
            self.getInstalledBusinessTemplate(property_dict['title'])
        if installed_bt is not None:
          installed_version = installed_bt.getVersion()
          installed_revision = installed_bt.getRevision()
          result = self.compareVersions(version, installed_version)
          if result == 0:
            version_state = 'present'
          elif result < 0:
            version_state = 'old'
        else:
          installed_version = ''
          installed_revision = ''
        version_state_title = version_state_title_dict[version_state]
        uid = b64encode(cPickle.dumps((repository, id)))
        obj = newTempBusinessTemplate(self, 'temp_' + uid,
                                      version_state = version_state,
                                      version_state_title = version_state_title,
                                      installed_version = installed_version,
                                      installed_revision = installed_revision,
                                      repository = repository, **property_dict)
        obj.setUid(uid)
        template_list.append(obj)
      template_list.sort(key=lambda x: x.getTitle())
      return template_list

    security.declareProtected( Permissions.AccessContentsInformation,
                               'getUpdatedRepositoryBusinessTemplateList' )
    def getUpdatedRepositoryBusinessTemplateList(self, **kw):
      """Get the list of updated Business Templates in repositories.
      """
      #LOG('getUpdatedRepositoryBusinessTemplateList', 0, 'kw = %r' % (kw,))
      return self.getRepositoryBusinessTemplateList(update_only=True, **kw)

    def compareVersions(self, version1, version2):
      """
        Return negative if version1 < version2, 0 if version1 == version2,
        positive if version1 > version2.

      Here is the algorithm:
        - Non-alphanumeric characters are not significant, besides the function
          of delimiters.
        - If a level of a version number is missing, it is assumed to be zero.
        - An alphabetical character is less than any numerical value.
        - Numerical values are compared as integers.

      This implements the following predicates:
        - 1.0 < 1.0.1
        - 1.0rc1 < 1.0
        - 1.0a < 1.0.1
        - 1.1 < 2.0
        - 1.0.0 = 1.0
      """
      r = re.compile('(\d+|[a-zA-Z])')
      v1 = r.findall(version1)
      v2 = r.findall(version2)

      def convert(v, i):
        """Convert the ith element of v to an interger for a comparison.
        """
        #LOG('convert', 0, 'v = %r, i = %r' % (v, i))
        try:
          e = v[i]
          try:
            e = int(e)
          except ValueError:
            # ASCII code is one byte, so this produces negative.
            e = struct.unpack('b', e)[0] - 0x200
        except IndexError:
          e = 0
        return e

      for i in xrange(max(len(v1), len(v2))):
        e1 = convert(v1, i)
        e2 = convert(v2, i)
        result = cmp(e1, e2)
        if result != 0:
          return result

      return 0

    def _getBusinessTemplateUrlDict(self):
      business_template_url_dict = {}
      for bt in self.getRepositoryBusinessTemplateList():
        url, name = self.decodeRepositoryBusinessTemplateUid(bt.getUid())
        business_template_url_dict[name[:-4]] = {
          'url':  '%s/%s' % (url, name),
          'revision': bt.getRevision()
          }
      return business_template_url_dict

    security.declareProtected(Permissions.ManagePortal,
        'installBusinessTemplatesFromRepositories' )
    def installBusinessTemplatesFromRepositories(self, template_list,
        only_newer=True, update_catalog=_MARKER):
      """Installs template_list from configured repositories by default only newest"""
      # XXX-Luke: This method could replace
      # TemplateTool_installRepositoryBusinessTemplateList while still being
      # possible to reuse by external callers
      opreation_log = []
      template_dict = self._getBusinessTemplateUrlDict()
      for template_name in template_list:
        if template_name in template_dict:
          installed_bt = self.getInstalledBusinessTemplate(template_name)
          if installed_bt is None or not only_newer or \
              installed_bt.getRevision() < template_dict[
              template_name]['revision']:
            template_document = self.download(template_dict[template_name][
              'url'])
            if update_catalog is _MARKER:
              template_document.install()
            else:
              template_document.install(update_catalog=update_catalog)
            opreation_log.append('Installed %s with revision %s' % (
              template_document.getTitle(), template_document.getRevision()))
          else:
            opreation_log.append('Skipped %s' % template_name)
        else:
          opreation_log.append('Not found in repositories %s' % template_name)
      return opreation_log

    security.declareProtected(Permissions.ManagePortal,
            'updateBusinessTemplateFromUrl')
    def updateBusinessTemplateFromUrl(self, download_url, id=None,
                                         keep_original_list=[],
                                         before_triggered_bt5_id_list=[],
                                         after_triggered_bt5_id_list=[],
                                         update_catalog=0,
                                         reinstall=False,
                                         active_process=None):
      """ 
        This method download and install a bt5, from a URL.
      """
      if active_process is None:
        installed_dict = {}
        def log(msg):
          LOG('TemplateTool.updateBusinessTemplateFromUrl', INFO, msg)
      else:
        active_process = self.unrestrictedTraverse(active_process)
        if getattr(aq_base(active_process), 'installed_dict', None) is None:
          active_process.installed_dict = PersistentMapping()
        installed_dict = active_process.installed_dict
        message_list = []
        log = message_list.append

      log("Installing %s ..." % download_url)
      imported_bt5 = self.download(url = download_url, id = id)
      bt_title = imported_bt5.getTitle()
      BusinessTemplate_getModifiedObject = \
        aq_base(getattr(self, 'BusinessTemplate_getModifiedObject'))

      listbox_object_list = BusinessTemplate_getModifiedObject.__of__(imported_bt5)()
      if reinstall:
        log('Reinstall all items')
        install_kw = dict.fromkeys(imported_bt5.getItemsList(), 'install')
      else:
        install_kw = {}
      for listbox_line in listbox_object_list:
        item = listbox_line.object_id
        state = listbox_line.object_state
        removed = state.startswith('Removed')
        if removed:
          # The following condition could not be used to automatically decide
          # if an item must be kept or not. For example, this would not work
          # for items installed by PortalTypeWorkflowChainTemplateItem.
          maybe_moved = installed_dict.get(listbox_line.object_id, '')
          log('%s: %s%s' % (state, item,
            maybe_moved and ' (moved to %s ?)' % maybe_moved))
        else:
          installed_dict[item] = bt_title
        # if a bt5 item is removed we may still want to keep it
        if ((removed or state in ('Modified', 'New'))
            and item in keep_original_list):
          install_kw[item] = 'nothing'
          log("Keep %r" % item)
        else:
          install_kw[item] = listbox_line.choice_item_list[0][1]

      # Run before script list
      for before_triggered_bt5_id in before_triggered_bt5_id_list:
        log('Execute %r' % before_triggered_bt5_id)
        imported_bt5.unrestrictedTraverse(before_triggered_bt5_id)()

      imported_bt5.install(object_to_update=install_kw,
                           update_catalog=update_catalog)

      # Run After script list
      for after_triggered_bt5_id in after_triggered_bt5_id_list:
        log('Execute %r' % after_triggered_bt5_id)
        imported_bt5.unrestrictedTraverse(after_triggered_bt5_id)()
      if active_process is not None:
        active_process.postResult(ActiveResult(
          '%03u. %s' % (len(active_process.getResultList()) + 1, bt_title),
          detail='\n'.join(message_list)))
      else:
        log("Updated %s from %s" % (bt_title, download_url))

    security.declareProtected(Permissions.ManagePortal,
            'getBusinessTemplateUrl')
    def getBusinessTemplateUrl(self, base_url_list, bt5_title):
      """
        This method verify if the business template are available
        into one url (repository).
      """
      # This list could be preconfigured at some properties or
      # at preferences.
      for base_url in base_url_list:
        url = "%s/%s" % (base_url, bt5_title)
        if base_url == "INSTANCE_HOME_REPOSITORY":
          url = "file://%s/bt5/%s" % (getConfiguration().instancehome, 
                                      bt5_title)
          LOG('ERP5', INFO, "TemplateTool: INSTANCE_HOME_REPOSITORY is %s." \
              % url)
        try:
          urllib2.urlopen(url)
          return url
        except (urllib2.HTTPError, OSError):
          # XXX Try again with ".bt5" in case the folder format be used
          # Instead tgz one.
          url = "%s.bt5" % url
          try:
            urllib2.urlopen(url)
            return url
          except (urllib2.HTTPError, OSError):
            pass
      LOG('ERP5', INFO, 'TemplateTool: %s was not found into the url list: ' 
                        '%s.' % (bt5_title, base_url_list))
      return None

InitializeClass(TemplateTool)
