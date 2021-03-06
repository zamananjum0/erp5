# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2015 Nexedi SA and Contributors. All Rights Reserved.
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
import json
import jsonschema
from Products.ERP5Type.XMLObject import XMLObject

class JSONType(XMLObject):
  """
  Represents a portal type with JSON Schema
  """
  
  def validateJsonSchema(self):
    """
    Validate contained JSON with the Schema defined in the Portal Type.
    """
    portal = self.getPortalObject()
    defined_schema = json.loads(portal.portal_types[self.getPortalType()].getTextContent())
    text_content = self.getTextContent()
	
    if text_content is None:
      return False
    current_schema = json.loads(text_content)
    try:
      jsonschema.validate(current_schema, defined_schema)
    except jsonschema.exceptions.ValidationError as err:
      return err
    return True