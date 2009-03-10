##############################################################################
#
# Copyright (c) 2002-2009 Nexedi SA and Contributors. All Rights Reserved.
#                    Jean-Paul Smets-Solanes <jp@nexedi.com>
#                    Vincent Pelletier <vincent@nexedi.com>
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

from Interface import Interface

class ISearchKey(Interface):
  """
    A SearchKey generates Query instances.
    It is responsible for parsing (or not) input value and generating the
    appropriate Query structure to match the intended search.

    This class is designed as a "singleton per column".
  """

  def __init__(column):
    """
      column (string)
        The column this SearchKey is instanciated for.
    """

  def getColumn():
    """
      Returns: string
        The column this SearchKey is instanciated for.
    """

  def buildSQLExpression(operator, value, column_map, only_group_columns, group):
    """
      This method passes on SQLExpression creation to operator, giving it the
      resolved column of this RelatedKey.

      operator (Operator)
        A comparison operator. It is used to render value, column and itself
        as valid SQL.
      value (anything)
      column_map (ColumnMap)
        The (built) column map to render our column.
      group (string)
        The group our column was part of.

      Returns: SQLExpression
        SQLExpression build by operator for current Query.
    """

  def buildSearchTextExpression(operator, value, column=None):
    """
      Render comparison using operator between value and our column as
      SearchText.

      operator (Operator)
        A comparison operator. It is used to render value as value SearchText.
      value (anything)
      column (string)
        If given, it overrides our column in SearchText rendering. This is
        useful when SearchText rendering is done for a virtual column,
        because the name of the virtual column must appear when rendered as
        SearchText.
    """

  def registerColumnMap(column_map, group, simple_query):
    """
      Register the column of this SearchKey to given column map.

      column_map (ColumnMap)
        The ColumnMap instance to register to.
      group (string)
        The group registration will be part of.
      simple_query (SimpleQuery)
        The SimpleQuery being registered.

      Returns: string
        The group assigned to caller. See ColumnMap for methods redefining
        caller's group.
    """

  def buildQuery(search_value, group=None, logical_operator=None, comparison_operator=None):
    """
      Generate queries from given search_value.
      logical_operator ('and', 'or', 'not', None)
        If no logical operator can be found in search_value, it will use given
        default operator.
      comparison_operator (string, None)
        If given, expresses the comparison between column and value.
    """

  def parseSearchText(value, is_column):
    """
      Parse given value to generate an Abstract Syntax Tree representing its
      logical structure, or None if there is no obvious structure in given
      value.
      See SearchText for parsing code.

      value (string)
        The string to parse.
      is_column (function taking one parameter)
        This function will be called with a single parameter, being a column
        name candidate.
        It must return a boolean:
        True: value is a valid column name
        False: value is not a valid column name

      Returns: (None, AbstratSyntaxNode)
        AbstratSyntaxNode complies with the IAbstractSyntaxNode interface.
    """

class IRelatedKey(ISearchKey):
  """
    A RelatedKey is a special variation of a SearchKey.
    Only a small set of methods differ. They are defined in this class.
  """

  def registerColumnMap(column_map, table_alias_list=None):
    """
      This is slightly different for regular registerColumnMap in that it must
      register multiple tables (and not columns, since RelatedKeys do not
      provide this information).
      Also, it must register namely "catalog" table and resolve its alias,
      angain since it's hardcoded in RelatedKey ZSQLMethods and not provided
      by their definitions.

      column_map (ColumnMap)

      Deprecated:
        table_alias_list (None, list of 2-tuples of strings)
          This list must have the exact same length as the list of tables 
    """

  def buildSQLExpression(sql_catalog, column_map, only_group_columns, group):
    """
      operator and value parameters are useless, since this type of SearhKey
      does not compare a value to any column, but uses a ZSQLMethod.
      To reach that ZSQLMethod, it also required a new sql_catalog parameter.

      sql_catalog (SQLCatalog)
        Used to retrieve related key's ZSQLMethod.
    """

  def buildQuery(sql_catalog, related_key_definition, search_value=None):
    """
      group is useless here, since group is determined by ColumnMap at
      registration time. search_value becomes optional.

      sql_catalog (SQLCatalog)
        Used to retrieve real column's SearchKey. For example, a RelatedKey
        used to compare with a "title" column will retrieve title's default
        SearchKey (which should be a KeywordKey).
      related_key_definition (string)
        Describes parameters of a RelatedKey. It is composed of 3 mains parts,
        separated by '/':
        - a list of table names
          Table names are separated by ','
        - a column name
        - the name of the related key ZSQLMethod
      search_value (None or Query)
        If given, a condition on real column will be generated.
        Otherwise, only the SQL required to reach that column will be
        generated. This is useful when sorting on a virtual column, for
        example.
    """

