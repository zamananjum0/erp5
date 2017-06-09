if brain.payment_uid:
  result_list = context.getPortalObject().portal_catalog(uid=brain.payment_uid)
  if result_list:
    bank_account = result_list[0].getObject()
    # XXX use preference ?
    if bank_account.getReference():
      return '%s - %s' % (bank_account.getReference(), bank_account.getTitle())
    return bank_account.getTitle()
