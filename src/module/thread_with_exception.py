import threading
import ctypes
import time


class ThreadWithException(threading.Thread):
    run_flag = False

    def __init__(self, function, *argv):
        threading.Thread.__init__(self)
        self.function = function
        self.argv = argv

    def run(self):
        # target function of the thread class
        try:
            self.run_flag = True
            if len(self.argv) == 0:
                self.function()
            else:
                self.function(self.argv)
        finally:
            self.run_flag = False

    def get_id(self):

        # returns id of the respective thread
        if hasattr(self, '_thread_id'):
            return self._thread_id
        for id, thread in threading._active.items():
            if thread is self:
                return id

    def raise_exception(self):
        print('Exception raise Start')
        thread_id = self.get_id()
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id,
                                                         ctypes.py_object(SystemExit))
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            print('Exception raise failure')
        print('Exception raise End')