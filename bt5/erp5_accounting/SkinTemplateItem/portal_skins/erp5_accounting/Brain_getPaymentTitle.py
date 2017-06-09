request = container.REQUEST
payment_title = ''
try:
  return request.other[context.payment_uid]
except KeyError:
  if context.payment_uid:
    brain_list = context.getPortalObject().portal_catalog(uid=context.payment_uid)
    if brain_list:
      payment_title = brain_list[0].getObject().getTitle()
  
request.other[context.payment_uid] = payment_title
return payment_title
