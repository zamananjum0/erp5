##############################################################################
#
# Copyright (c) 2006 Nexedi SARL and Contributors. All Rights Reserved.
#                    Romain Courteaud <romain@nexedi.com>
#                    Ivan Tyagov <ivan@nexedi.com>
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

from AccessControl import ClassSecurityInfo
from ZPublisher.HTTPRequest import FileUpload
from Globals import InitializeClass, DTMLFile
from Products.ERP5Type.Tool.BaseTool import BaseTool
from Products.ERP5Type import Permissions
from Products.ERP5Wizard import _dtmldir
from Products.CMFCore.utils import getToolByName
from zLOG import LOG, INFO, WARNING, ERROR, DEBUG
from cStringIO import StringIO
from UserDict import UserDict
import xmlrpclib, socket, sys, traceback, urllib, urllib2, base64, cgi
from AccessControl.SecurityManagement import newSecurityManager, noSecurityManager
import zLOG
import cookielib

# global (RAM) cookie storage
cookiejar = cookielib.CookieJar()
referer  = None

def _setSuperSecurityManager(self):
  """ Change to super user account. """
  user = self.getWrappedOwner()
  newSecurityManager(self.REQUEST, user)

class GeneratorCall(UserDict):
  """ Class use to generate/interpret XML-RPC call for the wizard. """
  
  _binary_keys = ("data", "filedata", "previous", "next",)
  _string_keys = ( "command", "server_buffer",)

  def __init__(self, *args, **kw):
    UserDict.__init__(self, *args, **kw)
    self.convert_data = {}
    for key in (self._binary_keys + self._string_keys):
      self.setdefault(key, None)
      
  def load(self, xmlrpccall):
    """ Convert the xmlrpccall into the object. """
    self.convert_data = xmlrpclib.loads(xmlrpccall)[0][0]
    for binary_key in self._binary_keys:
      if self.convert_data[binary_key] is not None:
        if isinstance(self.convert_data[binary_key], list):
          self[binary_key] = []
          for item in self.convert_data[binary_key]:
            self[binary_key].append(self._decodeData(item[16:-18]))
        else:
          self[binary_key] = self._decodeData(self.convert_data[binary_key][16:-18])
    ## load string keys 
    for string_key in self._string_keys:
      self[string_key] = self.convert_data[string_key]

  def dump(self):
    """ Dump object to a xmlrpccall. """
    for binary_key in self._binary_keys:
      if isinstance(self[binary_key], list):
        ## we have list of values 
        self.convert_data[binary_key] = []
        for item in self[binary_key]:
          self.convert_data[binary_key].append(self._encodeData(item))
      else:
        if self[binary_key] is not None:
          self.convert_data[binary_key] = self._encodeData(self[binary_key])
        else:
          self.convert_data[binary_key] = None
    for string_key in self._string_keys:
      self.convert_data[string_key] = self[string_key]
    return xmlrpclib.dumps((self.convert_data,), 'GeneratorAnswer', allow_none=1)

  def _decodeData(self, data):
    """ Decode data. """
    binary_decoder = xmlrpclib.Binary()
    binary_decoder.decode(data)
    return binary_decoder.data
    
  def _encodeData(self, data):
    """ Encode data to transmitable text. """
    fp = StringIO()
    try:
      xmlrpclib.Binary(data=data).encode(fp)
      return fp.getvalue()
    finally:
      fp.close()

def getPicklableRequest(REQUEST):
  """ Return 'pickable' request """
  picklable_request = {}
  for key, value in REQUEST.items():
    picklable_request[key] = str(value)
  return picklable_request

def _generateErrorXML(error_message):
  """ Generate HTML for displaying an error. """
  log_message = traceback.format_exc()
  return '<table><tr><td class="error">%s</td></tr></table>' % error_message
      
## server to local preferences id translation table
_server_to_preference_ids_map = {'client_id': 'preferred_express_client_uid',
                                 'current_bc_index': 'preferred_express_erp5_uid',
                                 'password': 'preferred_express_password',
                                 'user_id': 'preferred_express_user_id',}


class WizardTool(BaseTool):
  """ WizardTool is able to generate custom business templates. """
  
  id = 'portal_wizard'
  meta_type = 'ERP5 Wizard Tool'
  portal_type = 'Wizard Tool'
  isPortalContent = 1 
  isRADContent = 1
  property_sheets = ()
  security = ClassSecurityInfo()
  security.declareProtected(Permissions.ManagePortal, 'manage_overview')
  manage_overview = DTMLFile('explainWizardTool', _dtmldir )
  
  # Stop traversing a concatenated path after the proxy method.
  def __before_publishing_traverse__(self, self2, request):
    path = request['TraversalRequestNameStack']
    if path and path[-1] == 'proxy':
      subpath = path[:-1]
      subpath.reverse()
      request.set('traverse_subpath', subpath)
      # initialize our root proxy URL which we use for a referer
      global referer
      path[:-1] = []
      if referer is None:
        referer = '%s/portal_wizard/proxy/%s/view' %(self.getPortalObject().absolute_url(), \
                                                                                   '/'.join(subpath[:3]))      

  def _getProxyURL(self, subpath='', query=''):
    # Helper method to construct an URL appropriate for proxying a request.
    # This makes sure that URLs generated by absolute_url at a remote site
    # will be always towards the proxy method again.
    # 
    # Note that the code assumes that VirtualHostBase is visible. The setting
    # of a front-end server must allow this.
    # 
    # This should generate an URL like this:
    # 
    # http://remotehost:9080/VirtualHostBase/http/localhost:8080/VirtualHostRoot/_vh_erp5/_vh_portal_wizard/_vh_proxy/erp5/person_module/2
    part_list = []

    server_url = self.getServerUrl().rstrip('/')
    part_list.append(server_url)

    part_list.append('VirtualHostBase')

    portal_url = self.getPortalObject().absolute_url()
    scheme, rest = urllib.splittype(portal_url)
    addr, path = urllib.splithost(rest)
    host, port = urllib.splitnport(addr, scheme == 'http' and 80 or 443)
    part_list.append(scheme)
    part_list.append('%s:%s' % (host, port))

    part_list.append('VirtualHostRoot')

    method_path = self.absolute_url_path() + '/proxy'
    part_list.extend(('_vh_' + p for p in method_path.split('/') if p))

    server_root = self.getServerRoot().strip('/')

    if isinstance(subpath, (list, tuple)):
      subpath = '/'.join(subpath)

    if not subpath.startswith(server_root):
      part_list.append(server_root)

    part_list.append(subpath)

    url = '/'.join((p for p in part_list if p))
    if query:
      url = url + '?' + query
    return url

  def _getSubsribedUserAndPassword(self):
    """Retrieve the username and password for the subscription from
    the system."""
    user = self.getExpressConfigurationPreference('preferred_express_user_id', '')
    pw =  self.getExpressConfigurationPreference('preferred_express_password', '')
    return (user, pw)

  # This is a custom opener director for not handling redirections
  # and errors automatically. This is necessary because the proxy
  # should pass all results to a client as they are.
  simple_opener_director = urllib2.OpenerDirector()
  for name in ('ProxyHandler', 'UnknownHandler', \
               'HTTPHandler', 'FTPHandler', 
               'FileHandler', 'HTTPSHandler',):
    handler = getattr(urllib2, name, None)
    if handler is not None:
      simple_opener_director.add_handler(handler())
  # add cookie support
  simple_opener_director.add_handler(urllib2.HTTPCookieProcessor(cookiejar))
 
  security.declareProtected(Permissions.View, 'proxy')
  def proxy(self, **kw):
    """Proxy a request to a server."""
    global cookiejar, referer
    if self.REQUEST['REQUEST_METHOD'] != 'GET':
      # XXX this depends on the internal of HTTPRequest.
      pos = self.REQUEST.stdin.tell()
      self.REQUEST.stdin.seek(0)
      # XXX if filesize is too big, this might cause a problem.
      data = self.REQUEST.stdin.read()
      self.REQUEST.stdin.seek(pos)
    else:
      data = None

    content_type = self.REQUEST.get_header('content-type')
  
    # XXX if ":method" trick is used, then remove it from subpath.
    if self.REQUEST.traverse_subpath:
      if data is not None:
        user_input = data
      else:
        user_input = self.REQUEST.QUERY_STRING
      if user_input:
        mark = ':method'
        content_type_value = None
        content_type_dict = None
        if content_type:
          content_type_value, content_type_dict = cgi.parse_header(content_type)
        if content_type_value == 'multipart/form-data':
          fp = StringIO(user_input)
          user_input_dict = cgi.parse_multipart(fp, content_type_dict)
        else:
          user_input_dict = cgi.parse_qs(user_input)

        for i in user_input_dict:
          if i.endswith(mark):
            method_name = i[:-len(mark)]
            method_path = method_name.split('/')
            if self.REQUEST.traverse_subpath[-len(method_path):]==method_path:
              del self.REQUEST.traverse_subpath[-len(method_path):]
              break

    url = self._getProxyURL(self.REQUEST.traverse_subpath,
                            self.REQUEST['QUERY_STRING'])

    # XXX this will send the password unconditionally!
    # I hope https will be good enough.
    header_dict = {}
    user_and_password = self._getSubsribedUserAndPassword()
    if (len(user_and_password)==2 and
        user_and_password[0] and user_and_password[1]):
      auth = 'Basic %s' % base64.standard_b64encode('%s:%s' % user_and_password)
      header_dict['Authorization'] = auth

    if content_type:
      header_dict['Content-Type'] = content_type

    # send locally saved cookies to remote web server
    if not header_dict.has_key('Cookie'):
      header_dict['Cookie'] = ''
    for cookie in cookiejar:
      # unconditionally send all cookies (no matter if expired or not) as URL is always the same
      header_dict['Cookie']  +=  '%s=%s;' %(cookie.name, cookie.value)
    # XXX: include cookies from local browser (like show/hide tabs) which are set directly
    # by client JavaScript code (i.e. not sent from server)
    
    # add HTTP referer (especially useful in Localizer when changing language)
    header_dict['REFERER'] = self.REQUEST.get('HTTP_REFERER', None) or referer
    request = urllib2.Request(url, data, header_dict)
    f = self.simple_opener_director.open(request)

    try:
      data = f.read()
      metadata = f.info()
      response = self.REQUEST.RESPONSE
      if f.code> 300 and f.code <400:
        # ignore 'location' header for redirects from server. If server requires redirect then 
        # redirect it ONLY to root web siteor current location
        response['location'] =  header_dict['REFERER']
      response.setStatus(f.code, f.msg)
      response.setHeader('content-type', metadata.getheader('content-type'))
      # FIXME this list should be confirmed with the RFC 2616.
      for k in ('uri', 'cache-control', 'last-modified',
                'etag', 'if-matched', 'if-none-match',
                'if-range', 'content-language', 'content-range'
                'content-location', 'content-md5', 'expires',
                'content-encoding', 'vary', 'pragma', 'content-disposition',
                'content-length', 'age'):
        if k in metadata:
          response.setHeader(k, metadata.getheader(k))
      return data
    finally:
      f.close()

  def _getRemoteWitchTool(self, server_url):
    """ Return remote generator tool interface. """
    server = xmlrpclib.ServerProxy(server_url, allow_none=1)
    witch_tool = server.portal_witch
    return witch_tool

  def _callRemoteMethod(self, distant_method, server_url=None):
    """ Call remote method on server and get result. """
    result_call = GeneratorCall()
    if server_url is None:
      # calculate it
      server_url = self.getServerUrl() + self.getServerRoot()
    witch_tool = self._getRemoteWitchTool(server_url)
    parameter_dict = self.REQUEST.form
    ## add client arguments
    self._updateParameterDictWithServerInfo(parameter_dict)
    ## handle file upload
    self._updateParameterDictWithFileUpload(parameter_dict)
    ## call remote method 
    try:
      method = getattr(witch_tool, distant_method)
      html = method(parameter_dict)
    except socket.error, message:
      html = _generateErrorXML("""Cannot contact the server: %s.
                                  Please check your network settings."""  %server_url)
      zLOG.LOG('Wizard Tool socket error', zLOG.ERROR, message)
      result_call.update({"command": "show",
                          "data": html,
                          "next": None,
                          "previous": None})
    except xmlrpclib.ProtocolError, message:
      html = _generateErrorXML("""The server %s refused to reply.
                                  Please contact erp5-dev@erp5.org""" % server_url)
      zLOG.LOG('Wizard Tool xmlrpc protocol error', zLOG.ERROR, message)
      result_call.update({"command": "show",
                          "data": html,
                          "next": None,
                          "previous": None})
    except xmlrpclib.Fault, message:
      html = _generateErrorXML("Error/bug inside the server: %s." % server_url)
      zLOG.LOG('Wizard Tool xmlrpc fault', zLOG.ERROR, message)
      result_call.update({"command": "show",
                          "data": html,
                          "next": None,
                          "previous": None})
    else:
      result_call.load(html)
      command = result_call["command"]
      html = result_call["data"]
    return result_call

  def _setServerInfo(self, **kw):
    """ Save to local Zope client address info. """
    global _server_to_preference_ids_map
    for item, value in kw.items():
      if item in _server_to_preference_ids_map.keys():
        ## save persistently (as preference)
        self.setExpressConfigurationPreference(_server_to_preference_ids_map[item],
                                               value)
      
  def _updateParameterDictWithServerInfo(self, parameter_dict):
    """Updates parameter_dict to include local saved server info settings. """
    global _server_to_preference_ids_map
    for key, value in _server_to_preference_ids_map.items():
      parameter_dict[key] = self.getExpressConfigurationPreference(value, None)
    ## add local ERP5 instance url
    parameter_dict['erp5_url'] = self.getPortalObject().absolute_url()
    # add user preffered language
    parameter_dict['user_preferred_language'] = getattr(self, 'user_preferred_language', 'en')
      
  def _updateParameterDictWithFileUpload(self, parameter_dict):
    """Updates parameter_dict to replace file upload with their file content,
    encoded as XML-RPC Binary
    """
    for key, value in parameter_dict.items():
      if isinstance(value, FileUpload):
        pos = value.tell()
        value.seek(0)
        parameter_dict[key] = xmlrpclib.Binary(value.read())
        value.seek(pos)

  def _importBT5FileData(self, bt5_filename, bt5_filedata):
    """ Import bt5 file content. """
    bt5_io = StringIO(bt5_filedata)
    portal_templates =  getToolByName(self.getPortalObject(), 'portal_templates')
    try:
      business_template = portal_templates.importFile(import_file=bt5_io, batch_mode=1)
    except:
      ## importing of generated bt5 failed
      business_template = None
      LOG("Wizard", ERROR, "[FAIL] Import of Nexedi Configurator bt5 file(%s)" %bt5_filename)
      raise
    bt5_io.close()
    #install bt5
    portal_workflow =  getToolByName(self.getPortalObject(), 'portal_workflow')
    business_template.install()
  
  security.declareProtected(Permissions.ModifyPortalContent,
                            'installBT5FilesFromServer')
  def installBT5FilesFromServer(self,
                                server_response,
                                execute_after_setup_script=True,
                                install_standard_bt5=True,
                                install_customer_bt5=True,
                                use_super_manager=True):
    """ Install or update BT5 files which we get from remote server. """
    if use_super_manager:
      # set current security manager to owner of site
      _setSuperSecurityManager(self.getPortalObject())

    portal = self.getPortalObject()
    bt5_files = server_response.get("filedata", [])
    bt5_filenames = server_response["server_buffer"].get("filenames", [])
    portal_templates = getToolByName(portal, 'portal_templates')
    counter = 0
    LOG("Wizard", INFO,
        "Starting installation for %s" %' '.join(bt5_filenames))
    #execute_after_setup_script = install_standard_bt5 =  install_customer_bt5 = False # dev mode
    for bt5_id in bt5_filenames:
      if bt5_id.startswith('http://'):
        ## direct download of bt5 files available
        if install_standard_bt5:
          bt  = portal_templates.download(bt5_id)
          bt.install()
          LOG("Wizard", INFO,
              "[OK] standard bt5 installation (HTTP) from %s" %bt5_id)
      else:
        ## remote system supplied file content
        if install_customer_bt5:
          bt5_filedata = bt5_files[counter]
          self._importBT5FileData(bt5_id, bt5_filedata)
          LOG("Wizard", INFO,
              "[OK] customized bt5 installation (XML-RPC) %s, %s bytes" %
               (bt5_id, len(bt5_filedata)))
      ## ..
      counter += 1
    ## can we execute after setup script that will finish installation on client side?
    bt5_after_setup_script_id = server_response["server_buffer"].get("after_setup_script_id", None)
    if bt5_after_setup_script_id is None and \
        self.getExpressConfigurationPreference(
                           'preferred_express_configuration_status', False):
      ## we already have stored after setup script id
      bt5_after_setup_script_id = self.getExpressConfigurationPreference(
                           'preferred_express_after_setup_script_id', None)
      
    if execute_after_setup_script and bt5_after_setup_script_id is not None:
      ## Execute script provided (if) in customer specific business template.
      bt5_customer_template_id = server_response["server_buffer"]['filenames'][-1]
      bt5_customer_template_id = bt5_customer_template_id.replace('.bt5', '')
      after_script = getattr(self, bt5_after_setup_script_id, None)
      if after_script is not None:
        after_script_result = after_script(customer_template_id = bt5_customer_template_id)
        LOG("Wizard", INFO,"[OK] execution of afer setup script %s (for bt5 %s)\n%s"
             %(after_script.getId(), bt5_customer_template_id, after_script_result))
    ## mark this ERP5 instance as configured
    self.setExpressConfigurationPreference(
        'preferred_express_configuration_status', 1)
    self.setExpressConfigurationPreference(
        'preferred_express_after_setup_script_id', bt5_after_setup_script_id)
    # Make sure that the site status is reloaded.
    portal.portal_caches.clearAllCache()
    LOG("Wizard", INFO,
              "Completed installation for %s" %' '.join(bt5_filenames))
    if use_super_manager:
      noSecurityManager()
                  
  ######################################################
  ##               Navigation                         ##
  ######################################################
  security.declareProtected(Permissions.ModifyPortalContent, 'init')
  def init(self, REQUEST=None, **kw):
    """ Unconditionaly reset client_id and start new configuration process. """
    #user_id = REQUEST.get('field_my_ac_name', '')
    #password = REQUEST.get('field_my_ac_password', '')
    return self.next(REQUEST, **kw)
    
  security.declareProtected(Permissions.ModifyPortalContent, 'login')
  def login(self, REQUEST):
    """ Login client and show next form. """
    client_id = None
    user_id = REQUEST.get('field_my_ac_name', '')
    password = REQUEST.get('field_my_ac_password', '')
    came_from_method = REQUEST.get('field_my_came_from_method', '')
    ## call remote server
    response = self._callRemoteMethod("getIdentification")
    command = response["command"]
    if command == "show":
      ## server wants some more info - i.e possible 
      ## selection of working business configuration
      if response.get('server_buffer', None) is not None:
        client_id = response['server_buffer'].get('client_id', None)
      self._setServerInfo(user_id=user_id,
                          password=password,
                          client_id=client_id)
      return self.WizardTool_dialogForm(form_html=response["data"])
    elif command == "next":
      self._setServerInfo(user_id=user_id, \
                          password=password, \
                          client_id=response['server_buffer'].get('client_id', None), \
                          current_bc_index=response['server_buffer'].get('current_bc_index', None))
      return self.next(REQUEST=REQUEST)
    elif command == "login":
      ## invalid user/password
      self.REQUEST.RESPONSE.redirect( \
          'portal_wizard/%s?field_my_ac_name=%s&portal_status_message=%s' \
            %(came_from_method, user_id, response['server_buffer']['message']))
      return 
              
  security.declareProtected(Permissions.ModifyPortalContent, 'next')
  def next(self, REQUEST):
    """ Validate settings and return a new form to the user.  """
    response = self._callRemoteMethod("next")
    if isinstance(response['server_buffer'], dict):
      ## Remote server may request us to save some data.
      self._setServerInfo(**response['server_buffer'])
    ## Parse server response
    command = response["command"]
    html = response["data"]
    if command == "show":
      return self.WizardTool_dialogForm(previous=response['previous'],
                                        form_html=html,
                                        next = response['next'])
    elif command == "update":
      return self.next(REQUEST=REQUEST)
    elif command == "login":
      REQUEST.set('portal_status_message', html)
      return self.view(REQUEST=REQUEST)
    elif command == "install":
      return self.startInstallation(REQUEST=REQUEST)
            
  security.declareProtected(Permissions.ModifyPortalContent, 'previous')
  def previous(self, REQUEST):
    """ Display the previous form. """
    response = self._callRemoteMethod('previous')
    command = response["command"]
    html = response['data']
    if command == "show":
      return self.WizardTool_dialogForm(previous=response['previous'],
                                        form_html=html,
                                        next=response['next'])
    elif command == "login":
      REQUEST.set('portal_status_message', html)
      return self.view(REQUEST=REQUEST)
      
  security.declarePublic(Permissions.AccessContentsInformation,
                         'getInstallationStatusReportFromClient')
  def getInstallationStatusReportFromClient(self,
                          active_process_id=None, REQUEST=None):
    """ Query local ERP5 instance for installation status.
        If installation is over the installation activities and reindexing
        activities should not exists.
    """
    portal_activities = getToolByName(self.getPortalObject(), 'portal_activities')
    if 0 == len(portal_activities.getMessageList()) and \
       0 == portal_activities.countMessageWithTag('initialERP5Setup'):
      html = self.WizardTool_successfulConfiguration()
    else:
      html = self.WizardTool_viewRunningInstallationMessageRenderer()
    return html
    
  security.declarePublic(Permissions.AccessContentsInformation, 'getInstallationStatusReportFromServer')
  def getInstallationStatusReportFromServer(self, active_process_id=None, REQUEST=None):
    """ Query remote server (usually only once for some installation status report """
    response = self._callRemoteMethod("getInstallationStatusReport")
    html = response["data"]
    return html
      
  security.declareProtected(Permissions.ModifyPortalContent, 'startInstallation')
  def startInstallation(self, REQUEST):
    """ Start installation process as an activity which will query generation server and
       download/install bt5 template files and meanwhile offer user a nice GUI to observe 
       what's happening. """
    active_process = self.portal_activities.newActiveProcess()
    REQUEST.set('active_process_id', active_process.getId())
    self.activate(active_process=active_process, tag = 'initialERP5Setup').initialERP5Setup()
    return self.Wizard_viewInstallationStatus(REQUEST)

  security.declareProtected(Permissions.ModifyPortalContent, 'initialERP5Setup')
  def initialERP5Setup(self):
    """ Get from remote generation server customized bt5 template files 
        and then install them. """
    # TODO: the installation have to be splitted into 1 activity per business
    # template install.
    self.REQUEST.form['wizard_request_type'] = 'initial_setup'
    # calculate server_url, because after bt5 installation reindexing is started
    # which will make it impossible to get preferences items    
    server_url = self.getServerUrl() + self.getServerRoot()
    server_response = self._callRemoteMethod('getBT5FilesForBusinessConfiguration', server_url)
    ## save erp5_uid which will make it possible to distingush different business conf for client
    current_bc_index = server_response['server_buffer']['current_bc_index']
    self._setServerInfo(current_bc_index = current_bc_index)
    self.installBT5FilesFromServer(server_response, True)
    server_response = self._callRemoteMethod('finalizeInstallation', server_url)
    LOG("Wizard", INFO,
        "Successfuly installed generated business configuration from %s" %self.getServerUrl())

  security.declareProtected(Permissions.ModifyPortalContent, 'repair')
  def repair(self):
    """ Repair broken ERP5 instance. This will install all business templates 
    for ERP5 instance as specified in its business configuration. """
    self.REQUEST.form['wizard_request_type'] = 'repair'
    server_response = self._callRemoteMethod('getBT5FilesForBusinessConfiguration')
    if server_response['command'] == "install":
      active_process = self.portal_activities.newActiveProcess()
      self.activate(active_process=active_process).installBT5FilesFromServer(server_response, True)
    html = server_response['data']
    LOG("Wizard", INFO,
        "Start repair process for ERP5 instance from %s" %self.getServerUrl())
    return self.WizardTool_dialogForm(form_html = html)

  security.declareProtected(Permissions.ModifyPortalContent, 'update')
  def update(self):
    """ Update ERP5's instance standard business templates. """
    self.REQUEST.form['wizard_request_type'] = 'update'
    server_response = self._callRemoteMethod('getBT5FilesForBusinessConfiguration')
    if server_response['command'] == "install":
      active_process = self.portal_activities.newActiveProcess()
      self.activate(active_process=active_process).installBT5FilesFromServer(server_response,
                                                                             execute_after_setup_script = False)
    html = server_response['data']
    LOG("Wizard", INFO,
        "Start update process for ERP5 instance from %s" %self.getServerUrl())
    return self.WizardTool_dialogForm(form_html = html)

  security.declareProtected(Permissions.View, 'getServerUrl')
  def getServerUrl(self):
    return self.getExpressConfigurationPreference('preferred_witch_tool_server_url', '')

  security.declareProtected(Permissions.View, 'getServerRoot')
  def getServerRoot(self):
    return self.getExpressConfigurationPreference('preferred_witch_tool_server_root', '')
  
  security.declareProtected(Permissions.View, 'getExpressConfigurationPreference')
  def getExpressConfigurationPreference(self, preference_id, default = None):
    """ Get Express configuration preference """
    portal_preferences = getToolByName(self, 'portal_preferences')
    return portal_preferences.getPreference(preference_id, default)
  
  security.declareProtected(Permissions.ModifyPortalContent, 'setExpressConfigurationPreference')
  def setExpressConfigurationPreference(self, preference_id, value):
    """ Set Express configuration preference """
    portal_preferences = getToolByName(self, 'portal_preferences')
    if portal_preferences.getActivePreference() is not None:
      portal_preferences.setPreference(preference_id, value)
