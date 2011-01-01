# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2010 Nexedi SA and Contributors. All Rights Reserved.
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsibility of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# guarantees and support are strongly adviced to contract a Free Software
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
##############################################################################

from DateTime import DateTime
from zLOG import LOG, PROBLEM
from Products.ERP5Type.Globals import InitializeClass
from AccessControl import ClassSecurityInfo
from AccessControl.SecurityManagement import getSecurityManager,\
                                             newSecurityManager,\
                                             setSecurityManager

from Products.PageTemplates.PageTemplateFile import PageTemplateFile

from Products.PluggableAuthService.interfaces import plugins
from Products.PluggableAuthService.utils import classImplements
from Products.PluggableAuthService.permissions import ManageUsers
from Products.PluggableAuthService.plugins.BasePlugin import BasePlugin

from Products.ERP5Type.Cache import CachingMethod
from Products.ERP5Security.ERP5UserManager import ERP5UserManager,\
     SUPER_USER, _AuthenticationFailure

#Form for new plugin in ZMI
manage_addERP5ExternalAuthenticationPluginForm = PageTemplateFile(
  'www/ERP5Security_addERP5ExternalAuthenticationPlugin', globals(),
  __name__='manage_addERP5ExternalAuthenticationPluginForm')

def addERP5ExternalAuthenticationPlugin(dispatcher, id, title=None, user_id_key='',
                              REQUEST=None):
  """ Add a ERP5ExternalAuthenticationPlugin to a Pluggable Auth Service. """

  plugin = ERP5ExternalAuthenticationPlugin(id, title, user_id_key)
  dispatcher._setObject(plugin.getId(), plugin)

  if REQUEST is not None:
      REQUEST['RESPONSE'].redirect(
          '%s/manage_workspace'
          '?manage_tabs_message='
          'ERP5ExternalAuthenticationPlugin+added.'
          % dispatcher.absolute_url())

class ERP5ExternalAuthenticationPlugin(ERP5UserManager):
  """
  External authentification PAS plugin which extracts the user id from HTTP
  request header, like REMOTE_USER, openAMid, etc.
  """

  meta_type = "ERP5 External Authentication Plugin"
  security = ClassSecurityInfo()
  user_id_key = ''

  manage_options = (({'label': 'Edit',
                      'action': 'manage_editERP5ExternalAuthenticationPluginForm',},
                     )
                    + BasePlugin.manage_options[:]
                    )

  _properties = (({'id':'user_id_key',
                   'type':'string',
                   'mode':'w',
                   'label':'HTTP request header key where the user_id is stored'
                   },
                  )
                 + BasePlugin._properties[:]
                 )

  def __init__(self, id, title=None, user_id_key=''):
    #Register value
    self._setId(id)
    self.title = title
    self.user_id_key = user_id_key

  ####################################
  #ILoginPasswordHostExtractionPlugin#
  ####################################
  security.declarePrivate('extractCredentials')
  def extractCredentials(self, request):
    """ Extract credentials from the request header. """
    creds = {}
    user_id = getattr(request, 'getHeader', request.get_header)(self.user_id_key)
    if user_id is not None:
      creds['external_login'] = user_id

    #Complete credential with some informations
    if creds:
      creds['remote_host'] = request.get('REMOTE_HOST', '')
      try:
        creds['remote_address'] = request.getClientAddr()
      except AttributeError:
        creds['remote_address'] = request.get('REMOTE_ADDR', '')

    return creds

  ################################
  #     IAuthenticationPlugin    #
  ################################
  security.declarePrivate('authenticateCredentials')
  def authenticateCredentials(self, credentials):
    """Authentificate with credentials"""
    login = credentials.get('external_login', None)
    # Forbidden the usage of the super user.
    if login == SUPER_USER:
      return None

    #Function to allow cache
    def _authenticateCredentials(login):
      if not login:
        return None

      #Search the user by his login
      user_list = self.getUserByLogin(login)
      if len(user_list) != 1:
        raise _AuthenticationFailure()
      user = user_list[0]

      #We need to be super_user
      sm = getSecurityManager()
      if sm.getUser().getId() != SUPER_USER:
        newSecurityManager(self, self.getUser(SUPER_USER))
        try:
          # get assignment list
          assignment_list = [x for x in user.objectValues(portal_type="Assignment") \
                             if x.getValidationState() == "open"]
          valid_assignment_list = []
          # check dates if exist
          login_date = DateTime()
          for assignment in assignment_list:
            if assignment.getStartDate() is not None and \
                   assignment.getStartDate() > login_date:
              continue
            if assignment.getStopDate() is not None and \
                   assignment.getStopDate() < login_date:
              continue
            valid_assignment_list.append(assignment)

          # validate
          if len(valid_assignment_list) > 0:
            return (login,login)
        finally:
          setSecurityManager(sm)

        raise _AuthenticationFailure()

    #Cache Method for best performance
    _authenticateCredentials = CachingMethod(
      _authenticateCredentials,
      id='ERP5ExternalAuthenticationPlugin_authenticateCredentials',
      cache_factory='erp5_content_short')
    try:
      return _authenticateCredentials(login=login)
    except _AuthenticationFailure:
      return None
    except StandardError,e:
      #Log standard error
      LOG('ERP5ExternalAuthenticationPlugin.authenticateCredentials', PROBLEM, str(e))
      return None

  ################################
  # Properties for ZMI managment #
  ################################

  #'Edit' option form
  manage_editERP5ExternalAuthenticationPluginForm = PageTemplateFile(
      'www/ERP5Security_editERP5ExternalAuthenticationPlugin',
      globals(),
      __name__='manage_editERP5ExternalAuthenticationPluginForm')

  security.declareProtected(ManageUsers, 'manage_editERP5ExternalAuthenticationPlugin')
  def manage_editERP5ExternalAuthenticationPlugin(self, user_id_key, RESPONSE=None):
    """Edit the object"""
    error_message = ''

    #Save user_id_key
    if user_id_key == '' or user_id_key is None:
      error_message += 'Invalid key value '
    else:
      self.user_id_key = user_id_key

    #Redirect
    if RESPONSE is not None:
      if error_message != '':
        self.REQUEST.form['manage_tabs_message'] = error_message
        return self.manage_editERP5ExternalAuthenticationPluginForm(RESPONSE)
      else:
        message = "Updated"
        RESPONSE.redirect('%s/manage_editERP5ExternalAuthenticationPluginForm'
                          '?manage_tabs_message=%s'
                          % (self.absolute_url(), message)
                          )

#List implementation of class
classImplements(ERP5ExternalAuthenticationPlugin,
                plugins.IAuthenticationPlugin,
                plugins.ILoginPasswordHostExtractionPlugin)

InitializeClass(ERP5ExternalAuthenticationPlugin)
