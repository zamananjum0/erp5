request = container.REQUEST
project_title = ''
try:
  return request.other[context.project_uid]
except KeyError:
  if context.project_uid:
    brain_list = context.getPortalObject().portal_catalog(uid=context.project_uid)
    if brain_list:
      project_title = brain_list[0].getObject().getTitle()

request.other[context.project_uid] = project_title
return project_title
