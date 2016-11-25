##############################################################################
#
# Copyright (c) 2016 Nexedi SA and Contributors. All Rights Reserved.
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
ENABLE_JOBLIB = True

import transaction
import time

from zLOG import LOG, INFO, WARNING

try:
  from sklearn.externals.joblib import register_parallel_backend
  from sklearn.externals.joblib.parallel import ParallelBackendBase, parallel_backend
  from sklearn.externals.joblib.parallel import FallbackToBackend, SequentialBackend
  from sklearn.externals.joblib._parallel_backends import SafeFunction
except ImportError:
  LOG("CMFActivityBackend", WARNING, "Fail to import joblib from sklearn!!!")
  ENABLE_JOBLIB = False


class CMFActivityResult(object):
  """ XXX Write doc string. 
  """
  def __init__(self, active_process, callback):
    self.active_process = active_process
    self.callback = callback

  def get(self, timeout=None):
    while not self.active_process.getResultList():
      time.sleep(1)
      if timeout is not None:
        timeout -= 1
        if timeout < 0:
          raise RuntimeError('Timeout reached')
      transaction.commit()
    result = self.active_process.getResultList()[0].result
    if self.callback is not None:
      self.callback(result)
    return result

if ENABLE_JOBLIB:
  class CMFActivityBackend(ParallelBackendBase):
    """ Implementation of a backend for joblib using CMFActivities
    """

    def __init__(self, *args, **kwargs):
      self.zope_context = kwargs['zope_context']

    def effective_n_jobs(self, n_jobs):
      # TODO
      return n_jobs

    def apply_async(self, batch, callback=None):
      """Schedule a func to be run"""
      portal_activities = self.zope_context.portal_activities
      
      # the creation of activitiy process here, might be removed, and 
      # we may consider to receive it, in the same way we get the
      # context. 
      active_process = portal_activities.newActiveProcess()
      
      # XXX Why we have to create a safe function?
      save_function = SafeFunction(batch)

      joblib_result = portal_activities.activate(activity='SQLJoblib',
          active_process=active_process).Base_callSafeFunction(safe_function)

      # While activate() don't return the joblib_result
      if joblib_result is None:
        # Transaction commit, is a code crime.
        transaction.commit()
        joblib_result = CMFActivityResult(active_process, callback)
        
      return joblib_result

    def configure(self, n_jobs=1, parallel=None, **backend_args):
      """Reconfigure the backend and return the number of workers. This
      makes it possible to reuse an existing backend instance for successive
      independent calls to Parallel with different parameters."""
      LOG("CMFActivityBackend", INFO, 'n_jobs={}'.format(n_jobs))
      LOG("CMFActivityBackend", INFO, 'parallel={}'.format(parallel))

      if n_jobs == 1:
        raise FallbackToBackend(SequentialBackend())

      self.parallel = parallel
      # self.zope_context = backend_args['zope_context']
      return self.effective_n_jobs(n_jobs)

  # Register the Backend in order to use this backend on ERP5.
  register_parallel_backend('CMFActivity', CMFActivityBackend)
  
else:
  class CMFActivityBackend(object):
    pass

